"""Line art of the KRINO assistant, from the character illustration: the ink lines, and the dark fills as a
dot-matrix halftone. Both come out as alpha masks, so the page paints them in its own ink colour (black on
white, white on black) and can animate them.

    python frontend/tools/lineart.py krino_人物形象.png frontend/public/krino

Writes line.png (full figure), face.png (square head crop for avatars). Needs Pillow and numpy only.
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

WIDTH = 900            # output width of the full figure; the illustration is 1194 px wide
DOT = 7                # halftone cell, in output pixels
FACE = (330, 150, 790, 610)   # head crop in source pixels: left, top, right, bottom


def xdog(gray: np.ndarray, sigma: float = 0.9, k: float = 1.6, p: float = 22.0, eps: float = 0.18,
         phi: float = 30.0) -> np.ndarray:
    """Extended difference of Gaussians: 1 on ink lines, 0 on paper, soft in between."""
    img = Image.fromarray((gray * 255).astype(np.uint8))
    g1 = np.asarray(img.filter(ImageFilter.GaussianBlur(sigma)), float) / 255
    g2 = np.asarray(img.filter(ImageFilter.GaussianBlur(sigma * k)), float) / 255
    d = (1 + p) * g1 - p * g2
    paper = np.where(d >= eps, 1.0, 1 + np.tanh(phi * (d - eps)))
    return 1 - np.clip(paper, 0, 1)


def halftone(gray: np.ndarray, alpha: np.ndarray, cell: int) -> np.ndarray:
    """Round dots on a square grid, sized by how dark each cell is; only where the figure is dark."""
    h, w = gray.shape
    out = np.zeros((h, w))
    yy, xx = np.mgrid[0:cell, 0:cell] + 0.5
    for y in range(0, h - cell + 1, cell):
        for x in range(0, w - cell + 1, cell):
            a = alpha[y:y + cell, x:x + cell].mean()
            dark = (1 - gray[y:y + cell, x:x + cell].mean()) * a
            if dark < 0.45:
                continue
            r = cell / 2 * min(1.0, (dark - 0.35) * 1.5)
            out[y:y + cell, x:x + cell] = (((xx - cell / 2) ** 2 + (yy - cell / 2) ** 2) <= r * r)
    return out


def mask(src: Image.Image, width: int, cell: int) -> Image.Image:
    src = src.convert("RGBA")
    src = src.resize((width, round(src.height * width / src.width)), Image.LANCZOS)
    rgba = np.asarray(src, float) / 255
    alpha = rgba[..., 3]
    gray = (rgba[..., :3] @ [0.299, 0.587, 0.114]) * alpha + (1 - alpha)     # transparent = paper
    lines = xdog(gray) * (alpha > 0.05)
    ink = np.maximum(lines, halftone(gray, alpha, cell))
    # Black RGB with the ink as alpha: CSS uses it as a mask, any colour shows through
    out = np.zeros((*ink.shape, 4), np.uint8)
    out[..., 3] = (np.clip(ink, 0, 1) * 255).astype(np.uint8)
    return Image.fromarray(out)


if __name__ == "__main__":
    source, out = Path(sys.argv[1]), Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(source)
    mask(img, WIDTH, DOT).save(out / "line.png", optimize=True)
    mask(img.crop(FACE), 256, 4).save(out / "face.png", optimize=True)
    print("wrote", out / "line.png", out / "face.png")
