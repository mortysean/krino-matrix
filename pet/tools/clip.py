"""桌宠素材第 2 步：用万相首尾帧生视频做一段动作。首帧和尾帧都是同一张基础姿势，
所以每段动作都从这个姿势开始、回到这个姿势结束，任意两段首尾相接都不会跳。

    python pet/tools/clip.py <基础姿势.png> <输出.mp4> "<动作描述>" [480P|720P]

费用：wan2.2-kf2v-flash 480P 0.1 元/秒，720P 0.2 元/秒，一段固定 5 秒。
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

MODEL = "wan2.2-kf2v-flash"
STYLE = ("Q 版动漫桌面宠物短动画，日系赛璐璐风格，动作圆润、有弹性、可爱，节奏轻快但不急促，像精心制作的动漫小短片。"
         "镜头完全固定不动，不推拉不摇移，人物始终在画面中央、大小不变、全身入画。背景始终是纯绿色，保持不变。")
NEGATIVE = ("镜头移动，镜头推拉，缩放，画面抖动，背景变化，背景出现物体，地面，阴影，文字，水印，多余的人物，"
            "人物变形，脸部崩坏，多余的手指，肢体扭曲，画风变化，闪烁，模糊，低质量")


def data_uri(path: Path) -> str:
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> None:
    base, out, action = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
    res = sys.argv[4] if len(sys.argv) > 4 else "720P"
    style = sys.argv[5] if len(sys.argv) > 5 else STYLE  # 角色自己的动作风格（actions.py 里按角色给）
    img = data_uri(base)
    api = settings.dashscope_base_url.rstrip("/")
    h = {"Authorization": f"Bearer {settings.dashscope_api_key}"}
    body = {"model": MODEL, "input": {"first_frame_url": img, "last_frame_url": img, "prompt": f"{style}{action}",
                                      "negative_prompt": NEGATIVE},
            "parameters": {"resolution": res, "prompt_extend": False, "watermark": False}}
    with httpx.Client(timeout=httpx.Timeout(120, connect=15)) as c:
        r = c.post(api + "/services/aigc/image2video/video-synthesis", json=body, headers={**h, "X-DashScope-Async": "enable"})
        r.raise_for_status()
        task = r.json()["output"]["task_id"]
        print("task", task, flush=True)
        while True:
            time.sleep(10)
            d = c.get(f"{api}/tasks/{task}", headers=h).json()["output"]
            if d["task_status"] in ("SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"):
                break
        if d["task_status"] != "SUCCEEDED":
            raise SystemExit(f"失败：{d}")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(c.get(d["video_url"]).content)
        print(out)


if __name__ == "__main__":
    main()
