"""生图提速基准：同一个提示词、同一个种子、768×1152，逐个试加速办法，记下用时、显存、是不是黑图。

    CUDA_VISIBLE_DEVICES=2,4 python bench_image.py [gen|edit] [变体 ...]     # 结果在 ../outputs/bench/

模型只从硬盘读一次（放在内存里），每个变体从内存拷一份到显卡、合并 Lightning、量化、（可选）编译。
变体名：<量化>-<步数>[-compile][-cache]
  量化：fp8wo = 只把权重存成 FP8，计算仍是 bf16（现在线上的做法）
        fp8row = 权重和激活都用 FP8 计算，按行缩放（比按整个张量缩放稳，不容易溢出成 NaN）
        bf16 = 不量化（20B 要 40G，只用来对照）
"""
from __future__ import annotations

import copy
import gc
import json
import sys
import time
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import image_server as S  # noqa: E402  复用同一套采样器、LoRA 合并

OUT = S.OUT_DIR / "bench"
OUT.mkdir(parents=True, exist_ok=True)
TEXT = ("单个角色的全身立绘，正面站立，从头到脚完整入画，人物居中，纯白色背景，日系二次元画风，干净线条，柔和上色。"
        "白色长发低马尾、黑色发带、细框眼镜、菱形发夹、黑色高领上衣、敞开的白色宽袖外套，冷静的成年女研究员，抱着一本黑色笔记本。")
EDIT_TEXT = "保持同一个角色（长相、发型、服装、画风）和纯白色背景、构图不变，只做这个修改：把头发换成浅蓝色"
W, H = 768, 1152


def build(cpu_tr, steps: int, quant: str, which: str):
    tr = copy.deepcopy(cpu_tr).to(S.MAIN)
    lora = (f"Qwen-Image-2512-Lightning-{steps}steps-V1.0-bf16.safetensors" if which == "gen"
            else f"Qwen-Image-Edit-2511-Lightning-{steps}steps-V1.0-bf16.safetensors")
    S._fuse_lora(tr, S.LORA_DIR / lora)
    if quant == "fp8wo":
        from torchao.quantization import Float8WeightOnlyConfig, quantize_
        quantize_(tr, Float8WeightOnlyConfig(), device=S.MAIN)
    elif quant == "fp8row":
        from torchao.quantization import Float8DynamicActivationFloat8WeightConfig, PerRow, quantize_
        quantize_(tr, Float8DynamicActivationFloat8WeightConfig(granularity=PerRow()), device=S.MAIN)
    elif quant in ("fp8safe", "fp8safer"):
        quantize_mixed(tr, keep_mlp_down=quant == "fp8safer")
    elif quant == "fp8img":
        quantize_mixed(tr, img_only=True)
    return tr


IMG_STREAM = ("attn.to_q", "attn.to_k", "attn.to_v", "attn.to_out", "img_mlp")  # 图像那一路；文字那一路（add_*、to_add_out、txt_mlp）不碰


def fp8_compute_ok(name: str, keep_mlp_down: bool, blocks: int = 60, edge: int = 2, img_only: bool = False) -> bool:
    """哪些层用 FP8 计算：只有中间块里的注意力和 MLP 大矩阵。调制层（img_mod/txt_mod，只处理一行时间步）、
    首尾几块、输入输出层都不碰——这些地方的激活最容易溢出。"""
    parts = name.split(".")
    if parts[0] != "transformer_blocks" or not parts[1].isdigit():
        return False
    i = int(parts[1])
    if i < edge or i >= blocks - edge or parts[2] in ("img_mod", "txt_mod"):
        return False
    if keep_mlp_down and parts[2] in ("img_mlp", "txt_mlp") and name.endswith("net.2"):
        return False
    if img_only and not any(".".join(parts[2:]).startswith(k) for k in IMG_STREAM):
        return False  # 文字有补齐的全零行：按行算缩放会除以 0 变成 NaN
    return True


def quantize_mixed(tr, keep_mlp_down: bool = False, img_only: bool = False):
    """FP8 计算 + 其余层只存 FP8 权重（显存和现在一样，速度接近全 FP8）。"""
    from torchao.quantization import Float8DynamicActivationFloat8WeightConfig, Float8WeightOnlyConfig, PerRow, quantize_
    quantize_(tr, Float8DynamicActivationFloat8WeightConfig(granularity=PerRow()), device=S.MAIN,
              filter_fn=lambda m, fqn: isinstance(m, torch.nn.Linear) and fp8_compute_ok(fqn, keep_mlp_down, img_only=img_only))
    quantize_(tr, Float8WeightOnlyConfig(), device=S.MAIN,
              filter_fn=lambda m, fqn: isinstance(m, torch.nn.Linear) and not fp8_compute_ok(fqn, keep_mlp_down, img_only=img_only))


def run(pipe, steps: int, which: str, ref):
    g = torch.Generator(device=S.MAIN).manual_seed(1234)
    kw = dict(negative_prompt=" ", width=W, height=H, num_inference_steps=steps, true_cfg_scale=1.0, generator=g)
    if which == "edit":
        return pipe(image=[ref], prompt=EDIT_TEXT, **kw).images[0]
    return pipe(prompt=TEXT, **kw).images[0]


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "gen"
    variants = sys.argv[2:] or ["fp8wo-8", "fp8wo-4", "fp8row-8", "fp8row-4", "fp8row-4-compile", "fp8row-8-cache"]
    from accelerate.hooks import AlignDevicesHook, add_hook_to_module
    from diffusers import FlowMatchEulerDiscreteScheduler, QwenImageEditPlusPipeline, QwenImagePipeline

    t = time.time()
    cls, path = (QwenImagePipeline, S.GEN_DIR) if which == "gen" else (QwenImageEditPlusPipeline, S.EDIT_DIR)
    pipe = cls.from_pretrained(str(path), torch_dtype=torch.bfloat16)
    pipe.scheduler = FlowMatchEulerDiscreteScheduler.from_config(S.SCHEDULER)
    cpu_tr = pipe.transformer
    pipe.vae.to(S.MAIN)
    pipe.text_encoder.to(S.AUX)
    add_hook_to_module(pipe.text_encoder, AlignDevicesHook(execution_device=S.AUX, io_same_device=True))
    type(pipe)._execution_device = property(lambda self: S.MAIN)
    print(f"模型读入内存 {time.time() - t:.0f}s", flush=True)
    ref = None
    if which == "edit":
        from PIL import Image
        ref = Image.open(S.HERE / "bench_ref.png").convert("RGB") if (S.HERE / "bench_ref.png").exists() else None
        if ref is None:
            raise SystemExit("改图要参考图：services/bench_ref.png")

    results = []
    for v in variants:
        parts = v.split("-")
        quant, steps = parts[0], int(parts[1])
        flags = set(parts[2:])
        rec = {"variant": v}
        try:
            t = time.time()
            tr = build(cpu_tr, steps, quant, which)
            pipe.transformer = tr
            if "compile" in flags:
                pipe.transformer = torch.compile(tr, dynamic=False)  # 默认模式：编译一两分钟；max-autotune 要半小时以上
            if "cache" in flags:
                import cache_dit
                cache_dit.enable_cache(pipe)
            rec["prepare_s"] = round(time.time() - t, 1)
            torch.cuda.reset_peak_memory_stats(S.MAIN)
            t = time.time(); run(pipe, steps, which, ref); rec["first_s"] = round(time.time() - t, 2)  # 第一次（含编译）
            times = []
            for _ in range(2):
                torch.cuda.synchronize(S.MAIN); t = time.time()
                img = run(pipe, steps, which, ref)
                torch.cuda.synchronize(S.MAIN); times.append(time.time() - t)
            rec["seconds"] = round(min(times), 2)
            rec["peak_gb"] = round(torch.cuda.max_memory_allocated(S.MAIN) / 2**30, 1)
            import numpy as np
            a = np.asarray(img).astype(float)
            rec["mean"] = round(a.mean(), 1)
            rec["black"] = bool(a.mean() < 5)
            img.save(OUT / f"{which}-{v}.png")
            if "cache" in flags:
                import cache_dit
                cache_dit.disable_cache(pipe)
        except Exception as e:  # noqa: BLE001  一个变体失败不影响后面的
            rec["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        results.append(rec)
        pipe.transformer = None
        tr = None
        gc.collect(); torch.cuda.empty_cache()
        torch._dynamo.reset()
    (OUT / f"{which}-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
