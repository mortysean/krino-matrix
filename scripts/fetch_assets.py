"""下载运行时需要、但不进 git 的素材，放到 data/models/。已存在就跳过。

    python scripts/fetch_assets.py              # 全部
    python scripts/fetch_assets.py tts          # 只下本地语音模型（Kokoro-82M 中文版，Apache-2.0，约 360MB）
    python scripts/fetch_assets.py live2d       # 只下 Live2D 示例模型 Hiyori（Live2D 免费素材许可，见下）

Hugging Face 主站连不上时自动换 hf-mirror.com；可以用 HF_ENDPOINT 指定。境内用 MODEL_SOURCE=modelscope 从魔搭下载语音模型。只用标准库。

Live2D 示例模型 Hiyori 来自 Live2D 官方 CubismWebSamples，适用《Live2D 免费素材使用许可协议》：
个人和年销售额低于 1000 万日元的小企业可以商用；必须保留版权标注；原始文件不能再分发，所以不进 git。
https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "data" / "models"

KOKORO_REPO = "hexgrad/Kokoro-82M-v1.1-zh"
LIVE2D_BASE = "https://raw.githubusercontent.com/Live2D/CubismWebSamples/develop/Samples/Resources/Hiyori"
LIVE2D_FILES = ["Hiyori.model3.json", "Hiyori.moc3", "Hiyori.physics3.json", "Hiyori.pose3.json", "Hiyori.cdi3.json",
                "Hiyori.userdata3.json", "Hiyori.2048/texture_00.png", "Hiyori.2048/texture_01.png",
                *[f"motions/Hiyori_m{i:02d}.motion3.json" for i in range(1, 11)]]


def get(url: str, timeout: float = 600) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "krino-world-fetch"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def save(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(get(url))
    tmp.replace(dest)


def hf_endpoint() -> str:
    if os.getenv("HF_ENDPOINT"):
        return os.environ["HF_ENDPOINT"].rstrip("/")
    for ep in ("https://huggingface.co", "https://hf-mirror.com"):
        try:
            get(f"{ep}/api/models/{KOKORO_REPO}", timeout=15)
            return ep
        except Exception:  # noqa: BLE001  证书错误、超时都换下一个
            continue
    raise SystemExit("连不上 Hugging Face 和 hf-mirror.com，请检查网络或设置 HF_ENDPOINT")


MODELSCOPE = "https://modelscope.cn"
MODELSCOPE_REPO = "AI-ModelScope/Kokoro-82M-v1.1-zh"  # 同一份模型在魔搭的镜像，境内快得多


def _wanted(name: str) -> bool:
    return name in ("config.json", "kokoro-v1_1-zh.pth") or name.startswith(("voices/zf_", "voices/zm_", "voices/af_", "voices/bf_"))


def fetch_tts() -> None:
    out = MODELS / "kokoro-zh"
    if os.getenv("MODEL_SOURCE") == "modelscope":
        info = json.loads(get(f"{MODELSCOPE}/api/v1/models/{MODELSCOPE_REPO}/repo/files?Recursive=true", timeout=30))
        files = [f["Path"] for f in info["Data"]["Files"] if f["Type"] == "blob" and _wanted(f["Path"])]
        url = lambda f: f"{MODELSCOPE}/models/{MODELSCOPE_REPO}/resolve/master/{f}"  # noqa: E731
    else:
        ep = hf_endpoint()
        info = json.loads(get(f"{ep}/api/models/{KOKORO_REPO}", timeout=30))
        files = [s["rfilename"] for s in info["siblings"] if _wanted(s["rfilename"])]
        url = lambda f: f"{ep}/{KOKORO_REPO}/resolve/main/{f}"  # noqa: E731
    for i, f in enumerate(files, 1):
        if not (out / f).exists():  # 已经下好的跳过，断了可以接着下
            save(url(f), out / f)
        print(f"\r语音模型 {i}/{len(files)}", end="", flush=True)
    (out / "SOURCE.md").write_text(f"来源：https://huggingface.co/{KOKORO_REPO}\n许可：Apache-2.0\n", encoding="utf-8")
    print(f"\n语音模型就绪：{out}")


def fetch_live2d() -> None:
    out = MODELS / "live2d" / "hiyori"
    for i, f in enumerate(LIVE2D_FILES, 1):
        save(f"{LIVE2D_BASE}/{f}", out / f)
        print(f"\rLive2D 示例模型 {i}/{len(LIVE2D_FILES)}", end="", flush=True)
    (out / "LICENSE.md").write_text(
        "桃瀬ひより（Hiyori Momose）© Live2D Inc.\n"
        "适用《Live2D 免费素材使用许可协议》：https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html\n"
        "个人与年销售额 1000 万日元以下的小企业可商用；必须保留本版权标注；不得再分发原始文件。\n", encoding="utf-8")
    print(f"\nLive2D 示例模型就绪：{out}")


if __name__ == "__main__":
    which = set(sys.argv[1:]) or {"tts", "live2d"}
    for name, fn in (("tts", fetch_tts), ("live2d", fetch_live2d)):
        if name in which:
            try:
                fn()
            except Exception as e:  # noqa: BLE001  一项失败不影响另一项；应用会退回浏览器朗读 / 静态立绘
                print(f"\n{name} 下载失败：{e}", file=sys.stderr)
