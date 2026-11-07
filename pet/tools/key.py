"""桌宠素材第 3 步：绿幕视频 → 透明 WebM（VP9 带透明通道），桌宠直接播放。

    python pet/tools/key.py <输入.mp4|目录> <输出目录> [高度=400]

抠图按色相判断“绿”：亮绿背景和脚下的深绿阴影都会去掉，人物身上的白、黑、灰不受影响；边缘的绿色反光压掉（去溢色）。
所有片段用同一个裁切框（按基础姿势算），保证换动作时人物位置、大小完全不变。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageFilter

FF = imageio_ffmpeg.get_ffmpeg_exe()
import os
CRF = os.getenv("KEY_CRF", "34")  # 越大文件越小、画质越糊；网页上用 40 左右
FPS = int(os.getenv("KEY_FPS", "30"))


def read_frames(path: Path) -> tuple[np.ndarray, int, int]:
    probe = subprocess.run([FF, "-i", str(path)], capture_output=True, text=True).stderr
    import re
    w, h = map(int, re.search(r"(\d{3,5})x(\d{3,5})", probe.split("Video:")[1]).groups())
    raw = subprocess.run([FF, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3), w, h


def alpha_of(rgb: np.ndarray) -> np.ndarray:
    """绿得越明显越透明：g 比 r、b 中较大的那个高出多少。"""
    f = rgb.astype(np.int16)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    excess = g - np.maximum(r, b)
    a = np.clip(1.0 - (excess - 18) / 40.0, 0, 1)  # 高出 18 以内算人物，高出 58 以上全透明
    return a


def despill(rgb: np.ndarray) -> np.ndarray:
    f = rgb.astype(np.int16)
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    f[..., 1] = np.minimum(g, np.maximum(r, b) + 6)
    return f.astype(np.uint8)


def clean(a: np.ndarray) -> np.ndarray:
    """去掉零星噪点、边缘收一点再羽化。"""
    m = Image.fromarray((a * 255).astype(np.uint8), "L")
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    return np.asarray(m)


def crop_box(frames: np.ndarray, pad: float = 0.06) -> tuple[int, int, int, int]:
    """所有帧里人物出现过的范围（left, top, 宽, 高），四周留一点边。"""
    union = np.zeros(frames.shape[1:3], bool)
    for fr in frames[:: max(1, len(frames) // 30)]:
        union |= alpha_of(fr) > 0.5
    ys, xs = np.nonzero(union)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    H, W = frames.shape[1:3]
    px, py = int((x1 - x0) * pad) + 4, int((y1 - y0) * pad / 2) + 4
    left, right = max(0, x0 - px), min(W, x1 + px)
    top, bottom = max(0, y0 - py), min(H, y1 + py)
    return left, top, right - left, bottom - top


def encode(frames_rgba: list[Image.Image], out: Path, size: tuple[int, int], fps: int = 30) -> None:
    args = [FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{size[0]}x{size[1]}", "-r", str(fps), "-i", "-",
            "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", CRF, "-row-mt", "1", "-deadline", "good",
            "-auto-alt-ref", "0", "-an", str(out)]
    p = subprocess.Popen(args, stdin=subprocess.PIPE)
    for im in frames_rgba:
        p.stdin.write(im.tobytes())
    p.stdin.close()
    if p.wait():
        raise SystemExit(f"编码失败：{out}")


def convert(src: Path, out: Path, box: tuple[int, int, int, int], height: int) -> None:
    frames, _, _ = read_frames(src)
    left, top, bw, bh = box
    size = (round(bw * height / bh / 2) * 2, height)  # VP9 要求偶数边长
    imgs = []
    for fr in frames:
        fr = fr[top:top + bh, left:left + bw]
        a = clean(alpha_of(fr))
        rgba = np.dstack([despill(fr), a])
        imgs.append(Image.fromarray(rgba, "RGBA").resize(size, Image.LANCZOS))
    out.parent.mkdir(parents=True, exist_ok=True)
    encode(imgs[:: max(1, 30 // FPS)], out, size, FPS)
    imgs[0].save(out.with_suffix(".png"))  # 第一帧：视频还没加载出来时先显示这张，也当封面


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    files = sorted(src.glob("*.mp4")) if src.is_dir() else [src]
    ref = next((f for f in files if f.stem == "idle"), files[0])
    box = crop_box(read_frames(ref)[0])
    for f in files:  # 统一裁切框：动作大一点的片段也要放得下 → 取所有片段的并集
        b = crop_box(read_frames(f)[0])
        l, t = min(box[0], b[0]), min(box[1], b[1])
        box = (l, t, max(box[0] + box[2], b[0] + b[2]) - l, max(box[1] + box[3], b[1] + b[3]) - t)
    print("裁切框", box)
    for f in files:
        convert(f, out / f"{f.stem}.webm", box, size)
        print(out / f"{f.stem}.webm", (out / f"{f.stem}.webm").stat().st_size // 1024, "KB", flush=True)


if __name__ == "__main__":
    main()
