"""自建生图服务（算力服务器上跑）：Qwen-Image-2512 文生图 + Qwen-Image-Edit-2511 参考图修改，都用 Lightning 少步数加速。

接口和百炼的 multimodal-generation 一样，后端只要把 IMAGE_BASE_URL 指过来：

    POST /api/v1/services/aigc/multimodal-generation/generation
         {"model": "...", "input": {"messages": [{"role": "user", "content": [{"image": "data:..."}, {"text": "..."}]}]},
          "parameters": {"n": 1, "size": "768*1152"}}
      → {"output": {"choices": [{"message": {"content": [{"image": "http://.../files/xxx.png"}]}}]}}
    content 里有 image 就走修改，没有就是文生图。

显存安排（CUDA_VISIBLE_DEVICES 给两张卡，比如 2,4）：
  第一张：两个 20B 的扩散模型都量化成 FP8（各约 20G）常驻，加 VAE —— 文生图和修改切换不用重新加载。
  第二张：Qwen2.5-VL 文本编码器（bf16 约 16G），和语音服务共用这张卡。

    CUDA_VISIBLE_DEVICES=2,4 uvicorn image_server:app --host 0.0.0.0 --port 8641
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
MAIN, AUX = torch.device("cuda:0"), torch.device("cuda:1")
MAX_SIDE = 1536

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s image: %(message)s")
log = logging.getLogger("image")
app = FastAPI(title="KRINO image")
_lock = threading.Lock()
_pipes: dict = {}
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Lightning 权重要求的采样器配置（来自 lightx2v/Qwen-Image-Lightning 的说明）
SCHEDULER = {
    "base_image_seq_len": 256, "base_shift": math.log(3), "invert_sigmas": False, "max_image_seq_len": 8192,
    "max_shift": math.log(3), "num_train_timesteps": 1000, "shift": 1.0, "shift_terminal": None,
    "stochastic_sampling": False, "time_shift_type": "exponential", "use_beta_sigmas": False,
    "use_dynamic_shifting": True, "use_exponential_sigmas": False, "use_karras_sigmas": False,
}


def _prepare(pipe, lora: str):
    """融合 Lightning 权重 → 量化 → 放到主卡；文本编码器放到副卡，进出数据自动搬到主卡。"""
    from accelerate.hooks import AlignDevicesHook, add_hook_to_module
    from diffusers import FlowMatchEulerDiscreteScheduler

    pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(SCHEDULER)
    pipe.load_lora_weights(str(LORA_DIR), weight_name=lora)
    pipe.fuse_lora()
    pipe.unload_lora_weights()
    tr = pipe.transformer
    if QUANT == "fp8":
        from torchao.quantization import Float8DynamicActivationFloat8WeightConfig, PerRow, quantize_

        quantize_(tr, Float8DynamicActivationFloat8WeightConfig(granularity=PerRow()), device=MAIN)
    tr.to(MAIN)
    pipe.vae.to(MAIN)
    te = pipe.text_encoder
    if not hasattr(te, "_hf_hook"):
        te.to(AUX)
        add_hook_to_module(te, AlignDevicesHook(execution_device=AUX, io_same_device=True))
    type(pipe)._execution_device = property(lambda self: MAIN)
    return pipe


def pipes() -> dict:
    if not _pipes:
        from diffusers import QwenImageEditPlusPipeline, QwenImagePipeline

        t = time.time()
        gen = QwenImagePipeline.from_pretrained(str(GEN_DIR), torch_dtype=torch.bfloat16)
        _prepare(gen, f"Qwen-Image-2512-Lightning-{STEPS}steps-V1.0-bf16.safetensors")
        log.info("文生图模型就绪（%.0fs），主卡已用 %.1fG", time.time() - t, torch.cuda.memory_allocated(MAIN) / 2**30)
        t = time.time()
        # 两个模型用的是同一个 Qwen2.5-VL 文本编码器和 VAE，共用一份
        edit = QwenImageEditPlusPipeline.from_pretrained(str(EDIT_DIR), torch_dtype=torch.bfloat16,
                                                         text_encoder=gen.text_encoder, vae=gen.vae)
        _prepare(edit, f"Qwen-Image-Edit-2511-Lightning-{STEPS}steps-V1.0-bf16.safetensors")
        log.info("修改模型就绪（%.0fs），主卡已用 %.1fG，副卡已用 %.1fG", time.time() - t,
                 torch.cuda.memory_allocated(MAIN) / 2**30, torch.cuda.memory_allocated(AUX) / 2**30)
        _pipes.update(gen=gen, edit=edit)
    return _pipes


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
    return {"ok": True, "loaded": bool(_pipes), "steps": STEPS, "quant": QUANT}


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
    n = max(1, min(4, int(params.get("n", 1))))
    w, h = _size(str(params.get("size", "1024*1024")))
    text = " ".join(x["text"] for x in content if x.get("text"))
    refs = [_load_image(x["image"]) for x in content if x.get("image")]
    if not text:
        raise HTTPException(400, "没有描述文字")
    seed = params.get("seed")
    g = torch.Generator(device=MAIN).manual_seed(int(seed)) if seed is not None else None
    t = time.time()
    with _lock:  # 一张卡一次只画一批
        p = pipes()
        if refs:
            out = p["edit"](image=refs, prompt=text, negative_prompt=" ", width=w, height=h, num_inference_steps=STEPS,
                            true_cfg_scale=1.0, num_images_per_prompt=n, generator=g).images
        else:
            out = p["gen"](prompt=text, negative_prompt=" ", width=w, height=h, num_inference_steps=STEPS,
                           true_cfg_scale=1.0, num_images_per_prompt=n, generator=g).images
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
    threading.Thread(target=lambda: (pipes(), log.info("预热完成")), daemon=True).start()
