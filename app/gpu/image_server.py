"""自建生图服务（算力服务器上跑）：Qwen-Image-2512 文生图 + Qwen-Image-Edit-2511 参考图修改，都用 Lightning 少步数加速。

接口和百炼的 multimodal-generation 一样，后端只要把 IMAGE_BASE_URL 指过来：

    POST /api/v1/services/aigc/multimodal-generation/generation
         {"model": "...", "input": {"messages": [{"role": "user", "content": [{"image": "data:..."}, {"text": "..."}]}]},
          "parameters": {"n": 1, "size": "768*1152"}}
      → {"output": {"choices": [{"message": {"content": [{"image": "http://.../files/xxx.png"}]}}]}}
    content 里有 image 就走修改，没有就是文生图。

显存安排（只用一张卡，和语音分开，出图时不拖慢语音）：
  启动时把两个 20B 扩散模型融合 Lightning、量化成 FP8（各约 20G），处理好以后放在内存里。
  来请求才把要用的那个扩散模型 + 文本编码器（Qwen2.5-VL，bf16 约 16G）+ VAE 搬上卡，约 37G；
  文生图和修改不同时在卡上；闲置 IDLE_SECONDS（默认 5 分钟）就全部退回内存，卡上只剩几百兆。
  这张卡别人也可能在用：上卡前先看空出的显存够不够 NEED_GB，不够等最多 WAIT_SECONDS，还不够就返回 503。

    CUDA_VISIBLE_DEVICES=2 uvicorn image_server:app --host 0.0.0.0 --port 8641
"""
from __future__ import annotations

import base64
import io
import logging
import math
import os
import threading
import time
import uuid
from pathlib import Path

import httpx
import torch
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image

HERE = Path(__file__).resolve().parent
MODELS = Path(os.getenv("MODELS_DIR", HERE.parent / "models"))
GEN_DIR = MODELS / os.getenv("GEN_MODEL", "Qwen-Image-2512")
EDIT_DIR = MODELS / os.getenv("EDIT_MODEL", "Qwen-Image-Edit-2511")
STEPS = int(os.getenv("STEPS", "8"))  # 4 或 8，对应 Lightning 的两种权重
LORA_DIR = MODELS / "lightning"
OUT_DIR = Path(os.getenv("OUT_DIR", HERE.parent / "outputs"))
API_KEY = os.getenv("IMAGE_API_KEY", "")  # 设了就要求 Authorization: Bearer <它>
PUBLIC_URL = os.getenv("PUBLIC_URL", "")  # 返回的图片地址前缀；空 = 用请求里的地址
QUANT = os.getenv("QUANT", "fp8")  # fp8 | none
MAIN, CPU = torch.device("cuda:0"), torch.device("cpu")
IDLE_SECONDS = float(os.getenv("IDLE_SECONDS", "300"))  # 闲置多久退回内存；0 = 一直留在卡上
NEED_GB = float(os.getenv("NEED_GB", "40"))  # 上卡前卡上至少要空出这么多：模型 35G + 出图时的中间结果（实测峰值约 38G）
WAIT_SECONDS = float(os.getenv("WAIT_SECONDS", "60"))  # 卡被别人占着时最多等多久，等不到就告诉后端“忙”
MAX_SIDE = 1536

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s image: %(message)s")
log = logging.getLogger("image")
app = FastAPI(title="KRINO image")
_lock = threading.Lock()
_pipes: dict = {}
_ready = threading.Event()
_on_gpu: str | None = None  # 现在在卡上的是哪个："gen" / "edit" / None
_last_used = 0.0
_pinned: dict[int, list] = {}  # 模块 → 它每个权重在内存里的锁页副本（权重不会变，退回内存时不用拷回来）
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Lightning 权重要求的采样器配置（来自 lightx2v/Qwen-Image-Lightning 的说明）
SCHEDULER = {
    "base_image_seq_len": 256, "base_shift": math.log(3), "invert_sigmas": False, "max_image_seq_len": 8192,
    "max_shift": math.log(3), "num_train_timesteps": 1000, "shift": 1.0, "shift_terminal": None,
    "stochastic_sampling": False, "time_shift_type": "exponential", "use_beta_sigmas": False,
    "use_dynamic_shifting": True, "use_exponential_sigmas": False, "use_karras_sigmas": False,
}


@torch.no_grad()
def _fuse_lora(model, path: Path) -> None:
    """把 Lightning 的 LoRA 直接加进权重：W += up @ down * alpha / rank。
    不走 diffusers/peft 的 load_lora_weights：改图模型用那条路合并后会留下空参数（meta tensor），量化时报错。"""
    from safetensors.torch import load_file

    sd = load_file(str(path))
    mods = dict(model.named_modules())
    n = 0
    for key in sd:
        if not key.endswith(".lora_down.weight"):
            continue
        name = key[: -len(".lora_down.weight")]
        down, up = sd[key].float(), sd[f"{name}.lora_up.weight"].float()
        alpha = float(sd.get(f"{name}.alpha", torch.tensor(down.shape[0])))
        w = mods[name].weight
        w.add_((up @ down * (alpha / down.shape[0])).to(device=w.device, dtype=w.dtype))
        n += 1
    log.info("已合并 %s：%d 层", path.name, n)


def _prepare(pipe, lora: str):
    """融合 Lightning 权重 → 在卡上量化 → 退回内存，用的时候再搬上卡。"""
    from diffusers import FlowMatchEulerDiscreteScheduler

    pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(SCHEDULER)
    tr = pipe.transformer
    _fuse_lora(tr, LORA_DIR / lora)
    if QUANT == "fp8":
        from torchao.quantization import Float8WeightOnlyConfig, quantize_

        # 只把权重存成 FP8，计算还是 bf16：激活也量化成 FP8 会溢出成 NaN，出全黑图（2026-11-07 实测）
        quantize_(tr, Float8WeightOnlyConfig(), device=MAIN)
    tr.to(CPU)
    torch.cuda.empty_cache()
    type(pipe)._execution_device = property(lambda self: MAIN)
    return pipe


def _pin(module) -> None:
    """把模块的权重换成锁页内存：上卡能快几倍（普通内存拷 35G 要四五十秒）。"""
    slots = []
    for sub in module.modules():
        for table in (sub._parameters, sub._buffers):
            for k, t in list(table.items()):
                if t is None:
                    continue
                cpu = t.data.to(CPU).pin_memory()
                table[k] = torch.nn.Parameter(cpu, requires_grad=False) if table is sub._parameters else cpu
                slots.append((table, k, cpu, table is sub._parameters))
    _pinned[id(module)] = slots


def _move(module, to_gpu: bool) -> None:
    for table, k, cpu, is_param in _pinned[id(module)]:
        t = cpu.to(MAIN, non_blocking=True) if to_gpu else cpu
        table[k] = torch.nn.Parameter(t, requires_grad=False) if is_param else t


def _load_all() -> None:
    from diffusers import QwenImageEditPlusPipeline, QwenImagePipeline

    t = time.time()
    gen = QwenImagePipeline.from_pretrained(str(GEN_DIR), torch_dtype=torch.bfloat16)
    _prepare(gen, f"Qwen-Image-2512-Lightning-{STEPS}steps-V1.0-bf16.safetensors")
    log.info("文生图模型就绪（%.0fs）", time.time() - t)
    t = time.time()
    # 两个模型用的是同一个 Qwen2.5-VL 文本编码器和 VAE，共用一份
    edit = QwenImageEditPlusPipeline.from_pretrained(str(EDIT_DIR), torch_dtype=torch.bfloat16,
                                                     text_encoder=gen.text_encoder, vae=gen.vae)
    _prepare(edit, f"Qwen-Image-Edit-2511-Lightning-{STEPS}steps-V1.0-bf16.safetensors")
    log.info("修改模型就绪（%.0fs），都放在内存里，卡上已用 %.1fG", time.time() - t, torch.cuda.memory_allocated(MAIN) / 2**30)
    t = time.time()
    for m in (gen.transformer, edit.transformer, gen.text_encoder, gen.vae):
        _pin(m)
    log.info("锁页内存准备好（%.0fs）", time.time() - t)
    _pipes.update(gen=gen, edit=edit)
    _ready.set()


def _use(kind: str):
    """把要用的模型搬上卡（另一个退回内存），返回它的 pipeline。调用方要持有 _lock。"""
    global _on_gpu
    if not _ready.wait(timeout=900):
        raise HTTPException(503, "生图模型还在加载，过几分钟再试")
    pipe = _pipes[kind]
    if _on_gpu != kind:
        if _on_gpu:
            _offload()
        _wait_for_room()
        t = time.time()
        _move(pipe.transformer, True)
        _move(pipe.text_encoder, True)
        _move(pipe.vae, True)
        torch.cuda.synchronize()
        log.info("%s模型上卡用时 %.1fs，卡上已用 %.1fG", "修改" if kind == "edit" else "文生图",
                 time.time() - t, torch.cuda.memory_allocated(MAIN) / 2**30)
        _on_gpu = kind
    return pipe


def _free_gb() -> float:
    """卡上还能给我们用多少：整卡空闲（别的程序占的已经扣掉）+ 我们自己缓存着没用的。"""
    free, _ = torch.cuda.mem_get_info(MAIN)
    return (free + torch.cuda.memory_reserved(MAIN) - torch.cuda.memory_allocated(MAIN)) / 2**30


def _wait_for_room() -> None:
    """这张卡别人也能用：上卡前确认空得够，不够就等一会儿，还不够就放弃，不去挤别人的程序。"""
    deadline = time.time() + WAIT_SECONDS
    while (free := _free_gb()) < NEED_GB:
        if time.time() > deadline:
            log.warning("卡上只空出 %.1fG（要 %.0fG），等了 %.0f 秒还不够，这次不画", free, NEED_GB, WAIT_SECONDS)
            raise HTTPException(503, "显卡正被别的任务占用，过一会儿再试")
        time.sleep(5)


def _offload() -> None:
    """全部退回内存，把显存还给别人。调用方要持有 _lock。"""
    global _on_gpu
    if not _on_gpu:
        return
    p = _pipes[_on_gpu]
    for m in (p.transformer, p.text_encoder, p.vae):
        _move(m, False)
    torch.cuda.empty_cache()
    log.info("模型退回内存，卡上剩 %.1fG", torch.cuda.memory_reserved(MAIN) / 2**30)
    _on_gpu = None


def _idle_watch() -> None:
    while True:
        time.sleep(15)
        if _on_gpu and time.time() - _last_used > IDLE_SECONDS and _lock.acquire(blocking=False):
            try:
                if time.time() - _last_used > IDLE_SECONDS:
                    log.info("闲置 %.0f 分钟", IDLE_SECONDS / 60)
                    _offload()
            finally:
                _lock.release()


def _load_image(src: str) -> Image.Image:
    if src.startswith("data:"):
        data = base64.b64decode(src.split(",", 1)[1])
    elif src.startswith(("http://", "https://")):
        data = httpx.get(src, timeout=30).content
    else:
        raise HTTPException(400, "参考图只支持 data URL 或 http 地址")
    return Image.open(io.BytesIO(data)).convert("RGB")


def _size(s: str) -> tuple[int, int]:
    try:
        w, h = (int(x) for x in s.replace("x", "*").split("*"))
    except ValueError:
        raise HTTPException(400, "size 要写成 宽*高") from None
    k = min(1.0, MAX_SIDE / max(w, h))
    return max(256, int(w * k) // 16 * 16), max(256, int(h * k) // 16 * 16)


def _cleanup():
    cut = time.time() - 24 * 3600
    for f in OUT_DIR.glob("*.png"):
        if f.stat().st_mtime < cut:
            f.unlink(missing_ok=True)


@app.get("/health")
def health():
    return {"ok": True, "loaded": _ready.is_set(), "on_gpu": _on_gpu, "steps": STEPS, "quant": QUANT}


@app.get("/files/{name}")
def files(name: str):
    p = OUT_DIR / Path(name).name
    if not p.exists():
        raise HTTPException(404, "图片已过期")
    return FileResponse(p, media_type="image/png")


@app.post("/api/v1/services/aigc/multimodal-generation/generation")
def generation(body: dict, request: Request, authorization: str = Header("")):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(401, "密钥不对")
    try:
        content = body["input"]["messages"][0]["content"]
    except (KeyError, IndexError, TypeError):
        raise HTTPException(400, "请求格式不对") from None
    params = body.get("parameters") or {}
    n = 1  # 只出一张：一个角色一个形象（请求里的 n 忽略）
    w, h = _size(str(params.get("size", "1024*1024")))
    text = " ".join(x["text"] for x in content if x.get("text"))
    refs = [_load_image(x["image"]) for x in content if x.get("image")]
    if not text:
        raise HTTPException(400, "没有描述文字")
    seed = params.get("seed")
    g = torch.Generator(device=MAIN).manual_seed(int(seed)) if seed is not None else None
    t = time.time()
    global _last_used
    with _lock:  # 一次只画一张
        pipe = _use("edit" if refs else "gen")
        if refs:
            out = pipe(image=refs, prompt=text, negative_prompt=" ", width=w, height=h, num_inference_steps=STEPS,
                            true_cfg_scale=1.0, num_images_per_prompt=1, generator=g).images
        else:
            out = pipe(prompt=text, negative_prompt=" ", width=w, height=h, num_inference_steps=STEPS,
                           true_cfg_scale=1.0, num_images_per_prompt=1, generator=g).images
        torch.cuda.empty_cache()
        _last_used = time.time()
    log.info("%s %dx%d ×%d，用时 %.1fs", "修改" if refs else "文生图", w, h, n, time.time() - t)
    base = (PUBLIC_URL or str(request.base_url)).rstrip("/")
    items = []
    for img in out:
        name = f"{uuid.uuid4().hex}.png"
        img.save(OUT_DIR / name)
        items.append({"image": f"{base}/files/{name}"})
    _cleanup()
    return {"output": {"choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": items}}]},
            "usage": {"width": w, "height": h, "image_count": n}, "request_id": uuid.uuid4().hex}


@app.on_event("startup")
def warmup():
    threading.Thread(target=lambda: (_load_all(), log.info("预热完成")), daemon=True).start()
    if IDLE_SECONDS > 0:
        threading.Thread(target=_idle_watch, daemon=True).start()
