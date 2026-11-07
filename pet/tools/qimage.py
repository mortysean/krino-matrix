"""桌宠素材第 1 步：以一张立绘为参考，用千问图像生成 Q 版基础姿势（纯绿幕背景，方便后面抠图）。

    python pet/tools/qimage.py <参考图> <输出目录> "<要保留的标志>" [张数] [补充] [体型] [表情]

密钥用项目 .env 里的 DASHSCOPE_API_KEY（复用后端的配置读取）。
"""
from __future__ import annotations

import base64
import io
import sys
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app" / "backend"))
from app.config import settings  # noqa: E402

GREEN = (0, 255, 0)

PROMPT = ("把这个角色画成 Q 版（chibi）桌面宠物：{body}，日系动漫赛璐璐风格，线条干净，上色柔和。"
          "保留她的标志：{keep}。全身入画，正面站立，双脚着地，双手自然放在身体两侧，{face}，眼睛看向前方。"
          "人物居中，四周留出空白，占画面高度约 70%。背景是完全平整的纯绿色（#00FF00），没有阴影、没有渐变、没有地面、没有任何其他物体和文字。"
          "人物身上不要出现绿色。{extra}")


def reference(path: Path) -> str:
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.split()[3])
    bg.thumbnail((1024, 1024))
    buf = io.BytesIO()
    bg.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def generate(ref: str, text: str, n: int, size: str = "1024*1024") -> list[bytes]:
    body = {"model": settings.image_model, "input": {"messages": [{"role": "user", "content": [{"image": ref}, {"text": text}]}]},
            "parameters": {"n": n, "size": size, "watermark": False}}
    with httpx.Client(timeout=httpx.Timeout(300, connect=15)) as c:
        for wait in (3, 6, 12, 24, None):
            r = c.post(settings.dashscope_base_url.rstrip("/") + "/services/aigc/multimodal-generation/generation", json=body,
                       headers={"Authorization": f"Bearer {settings.dashscope_api_key}"})
            if r.status_code != 429 or wait is None:
                break
            time.sleep(wait)
        r.raise_for_status()
        urls = [x["image"] for ch in r.json()["output"]["choices"] for x in ch["message"]["content"] if x.get("image")]
        return [c.get(u).content for u in urls]


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    keep, n = sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 2
    extra = sys.argv[5] if len(sys.argv) > 5 else ""
    body = sys.argv[6] if len(sys.argv) > 6 else "2.5 头身，大头小身体，圆润可爱"
    face = sys.argv[7] if len(sys.argv) > 7 else "表情平静温柔、带一点点微笑"
    out.mkdir(parents=True, exist_ok=True)
    ref = reference(src)
    start = len(list(out.glob("base-*.png")))
    for i, data in enumerate(generate(ref, PROMPT.format(keep=keep, extra=extra, body=body, face=face), n)):
        p = out / f"base-{start + i + 1}.png"
        Image.open(io.BytesIO(data)).convert("RGB").save(p)
        print(p)


if __name__ == "__main__":
    main()
