"""给自己创建的角色做“动图”：会做动作的 Q 版小人，和两位官方角色同一套做法（做法来自 pet/tools/）。

  1. 以角色的立绘为参考，用千问图像画一张 Q 版基础姿势（纯绿幕背景，方便抠）
  2. 每个动作一段 5 秒视频：万相首尾帧生视频，首帧、尾帧都是这张基础姿势 → 任意两段首尾相接都不跳
  3. 按色相抠掉绿幕 → 透明 WebM（VP9），所有片段同一个裁切框，换动作时人物位置大小不变
  4. 写 chibi.json（动作清单：聊天里的动作、表情各对应哪几段），和官方角色的格式一样，前端 chibi.js 直接播

文件放在 data/media/u/<用户>/<随机名>/，地址 /media/u/<用户>/<随机名>/chibi.json。
花的钱：一张图（IMAGE_PRICE_CNY）+ 每段视频 MOTION_CLIP_PRICE_CNY（wan2.2-kf2v-flash 720P 5 秒约 1 元），
默认 8 段约 8 元。大约 10 分钟（视频三段一组同时做，一组 3~4 分钟）。只用百炼（视频没有自建）。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import secrets
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

from .config import settings

log = logging.getLogger("krino.motion")

VIDEO_MODEL = "wan2.2-kf2v-flash"
RESOLUTION = "720P"
HEIGHT = 576   # 页面上显示不到更大
FPS = 24
CRF = "40"
WORKERS = 3    # 百炼视频同时做几段
END = "最后回到一开始的姿势。"

BASE_PROMPT = ("把这个角色画成 Q 版（chibi）小人：2.5 头身，大头小身体，圆润可爱，日系动漫赛璐璐风格，线条干净，上色柔和。"
               "保留角色的长相、发型、发色、服装和标志性的配饰，物种和体型特征也要保留（不是人就不要画成人）。"
               "全身入画，正面站立，双脚着地，双手自然放在身体两侧，表情平静温和、带一点点微笑，眼睛看向前方。"
               "人物居中，四周留出空白，占画面高度约 70%。背景是完全平整的纯绿色（#00FF00），没有阴影、没有渐变、没有地面、"
               "没有任何其他物体和文字。人物身上不要出现绿色。")
STYLE = ("Q 版动漫角色短动画，日系赛璐璐风格，动作圆润、有弹性、可爱，节奏轻快但不急促，表情生动。"
         "镜头完全固定不动，不推拉不摇移，人物始终在画面中央、大小不变、全身入画。背景始终是纯绿色，保持不变。")
NEGATIVE = ("镜头移动，镜头推拉，缩放，画面抖动，背景变化，背景出现物体，地面，阴影，文字，水印，多余的人物，"
            "人物变形，脸部崩坏，多余的手指，肢体扭曲，画风变化，闪烁，模糊，低质量")

# 通用动作（谁都能做）。前 8 段是默认做的；顺序就是重要程度（钱不够时少做几段，从后面砍）
ACTIONS = {
    "idle": "角色安静地站着，随呼吸身体轻轻起伏，偶尔眨眨眼，头发和衣角被微风轻轻吹动，神情自然放松，" + END,
    "talk": "角色对着前方说话，嘴巴自然地一张一合，一只手在胸前随着话语做了一两个小手势，表情生动，说完手放下，" + END,
    "wave": "角色开心地抬起右手朝前方挥手打招呼，笑得眼睛弯弯，身体随着挥手轻轻左右摇摆，挥了几下后手放下，" + END,
    "nod": "角色认真地点了两下头表示同意，表情温和可靠，" + END,
    "happy": "角色非常开心，原地轻快地蹦跳了两下，双手握拳放在胸前，眼睛笑成弯月，头发和衣服在空中弹起又落下，落地后" + END,
    "shy": "角色害羞地用双手捂住红红的脸颊，身体扭扭捏捏地左右晃了晃，然后从指缝里偷看一眼，放下手，" + END,
    "think": "角色歪着头，一只手托着下巴，眼睛往上看，努力地思考，头顶冒出一个小问号，然后眼睛一亮，手放下，" + END,
    "surprised": "角色被吓了一跳，身体往上一缩，眼睛睁得圆圆的，头发微微竖起，然后拍拍胸口松了口气，" + END,
    "sad": "角色委屈地瘪着嘴，眼睛里泪汪汪的，肩膀耷拉下来，揉了揉眼睛，然后重新打起精神，" + END,
    "bow": "角色右手放在胸前，礼貌地微微鞠躬，再直起身，露出一个微笑，" + END,
}
# 聊天里的动作名、表情 → 片段（没做的片段自动跳过）
MOVES = {"wave": ["wave"], "nod": ["nod"], "think": ["think"], "happy": ["happy"], "cheer": ["happy"], "shy": ["shy"],
         "surprised": ["surprised"], "sad": ["sad"], "bow": ["bow"], "tilt_head": ["think"]}
FACES = {"happy": ["happy"], "shy": ["shy"], "sad": ["sad"], "worried": ["sad"], "surprised": ["surprised"], "focused": ["think"]}


class MotionError(RuntimeError):
    pass


def clip_names() -> list[str]:
    n = max(2, min(len(ACTIONS), settings.motion_clips))
    return list(ACTIONS)[:n]


def cost_cny() -> float:
    """做一套动图大概花多少钱（一张基础姿势 + 每段视频）。"""
    return settings.image_price_cny + len(clip_names()) * settings.motion_clip_price_cny


# ---------- 百炼 ----------

def _key() -> str:
    if not settings.dashscope_api_key:
        raise MotionError("没有配置 DASHSCOPE_API_KEY，做不了动图")
    return settings.dashscope_api_key


def _data_uri(img, fmt: str = "PNG") -> str:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, fmt)
    return f"data:image/{fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


def base_pose(portrait) -> "Image.Image":  # noqa: F821
    """以立绘为参考画 Q 版基础姿势（绿幕）。"""
    from PIL import Image

    ref = Image.new("RGB", portrait.size, "white")
    rgba = portrait.convert("RGBA")
    ref.paste(rgba, mask=rgba.split()[3])
    ref.thumbnail((1024, 1024))
    body = {"model": settings.image_model,
            "input": {"messages": [{"role": "user", "content": [{"image": _data_uri(ref, "JPEG")}, {"text": BASE_PROMPT}]}]},
            "parameters": {"n": 1, "size": "1024*1024", "watermark": False}}
    with httpx.Client(timeout=httpx.Timeout(300, connect=15)) as c:
        for wait in (3, 6, 12, 24, None):
            r = c.post(settings.dashscope_base_url.rstrip("/") + "/services/aigc/multimodal-generation/generation",
                       json=body, headers={"Authorization": f"Bearer {_key()}"})
            if r.status_code != 429 or wait is None:
                break
            time.sleep(wait)
        if r.status_code != 200:
            raise MotionError(f"Q 版基础姿势没画出来（{r.status_code}）")
        urls = [x["image"] for ch in r.json()["output"]["choices"] for x in ch["message"]["content"] if x.get("image")]
        if not urls:
            raise MotionError("Q 版基础姿势没画出来")
        return Image.open(io.BytesIO(c.get(urls[0]).content)).convert("RGB")


def clip(base_uri: str, action: str, out: Path) -> None:
    """一段 5 秒动作视频（首尾帧都是基础姿势），存成 mp4。"""
    api = settings.dashscope_base_url.rstrip("/")
    h = {"Authorization": f"Bearer {_key()}"}
    body = {"model": VIDEO_MODEL, "input": {"first_frame_url": base_uri, "last_frame_url": base_uri, "prompt": STYLE + action,
                                            "negative_prompt": NEGATIVE},
            "parameters": {"resolution": RESOLUTION, "prompt_extend": False, "watermark": False}}
    with httpx.Client(timeout=httpx.Timeout(120, connect=15)) as c:
        for wait in (5, 15, 30, None):  # 同时提交的任务太多会被限流
            r = c.post(api + "/services/aigc/image2video/video-synthesis", json=body, headers={**h, "X-DashScope-Async": "enable"})
            if r.status_code != 429 or wait is None:
                break
            time.sleep(wait)
        if r.status_code != 200:
            raise MotionError(f"动作视频提交失败（{r.status_code}）：{r.text[:200]}")
        task = r.json()["output"]["task_id"]
        deadline = time.time() + 900
        while True:
            time.sleep(8)
            d = c.get(f"{api}/tasks/{task}", headers=h).json()["output"]
            if d["task_status"] in ("SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN") or time.time() > deadline:
                break
        if d.get("task_status") != "SUCCEEDED":
            raise MotionError(f"动作视频没做出来：{d.get('message') or d.get('task_status')}")
        out.write_bytes(c.get(d["video_url"]).content)


# ---------- 绿幕 → 透明 WebM ----------

def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as e:
        raise MotionError("服务器上没有 ffmpeg（pip install imageio-ffmpeg）") from e


def _frames(path: Path):
    import numpy as np

    ff = _ffmpeg()
    probe = subprocess.run([ff, "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"(\d{3,5})x(\d{3,5})", probe.split("Video:")[1]) if "Video:" in probe else None
    if not m:
        raise MotionError("动作视频打不开")
    w, h = map(int, m.groups())
    raw = subprocess.run([ff, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)


def _alpha(rgb):
    """绿得越明显越透明：g 比 r、b 中较大的那个高出多少（亮绿背景、脚下深绿的影子都去掉，人物身上的白黑灰不受影响）。"""
    import numpy as np

    f = rgb.astype(np.int16)
    excess = f[..., 1] - np.maximum(f[..., 0], f[..., 2])
    return np.clip(1.0 - (excess - 18) / 40.0, 0, 1)


def _despill(rgb):
    import numpy as np

    f = rgb.astype(np.int16)
    f[..., 1] = np.minimum(f[..., 1], np.maximum(f[..., 0], f[..., 2]) + 6)  # 边上的绿色反光压掉
    return f.astype(np.uint8)


def _box(clips: list) -> tuple[int, int, int, int]:
    """所有片段里人物出现过的范围（统一裁切框），四周留一点边。"""
    import numpy as np

    union = None
    for frames in clips:
        for fr in frames[:: max(1, len(frames) // 20)]:
            m = _alpha(fr) > 0.5
            union = m if union is None else union | m
    ys, xs = np.nonzero(union)
    if not len(ys):
        raise MotionError("动作视频里找不到人物")
    H, W = union.shape
    px, py = int((xs.max() - xs.min()) * 0.06) + 4, int((ys.max() - ys.min()) * 0.03) + 4
    left, right = max(0, xs.min() - px), min(W, xs.max() + px)
    top, bottom = max(0, ys.min() - py), min(H, ys.max() + py)
    return int(left), int(top), int(right - left), int(bottom - top)


def _encode(frames, box, out: Path):
    """裁切、抠图、缩放，编码成带透明通道的 VP9 WebM；返回第一帧（RGBA，做封面）。"""
    import numpy as np
    from PIL import Image, ImageFilter

    left, top, bw, bh = box
    size = (round(bw * HEIGHT / bh / 2) * 2, HEIGHT)
    src_fps = 30  # 万相输出 30 帧
    keep = [frames[min(len(frames) - 1, round(i * src_fps / FPS))] for i in range(round(len(frames) * FPS / src_fps))]
    p = subprocess.Popen([_ffmpeg(), "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{size[0]}x{size[1]}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", CRF,
                          "-row-mt", "1", "-deadline", "good", "-cpu-used", "2", "-auto-alt-ref", "0", "-an", str(out)],
                         stdin=subprocess.PIPE)
    first = None
    for fr in keep:
        fr = fr[top:top + bh, left:left + bw]
        a = Image.fromarray((_alpha(fr) * 255).astype(np.uint8), "L").filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
        im = Image.fromarray(np.dstack([_despill(fr), np.asarray(a)]), "RGBA").resize(size, Image.LANCZOS)
        first = first or im
        p.stdin.write(im.tobytes())
    p.stdin.close()
    if p.wait():
        raise MotionError("动作视频编码失败")
    return first


# ---------- 一整套 ----------

def make(user_id: str, portrait_path: Path, progress=None) -> dict:
    """做一整套动图，返回形象 {kind: chibi, src, still} 和实际做成的片段数。progress(done, total) 每做完一段报一次。
    片段做失败几段没关系（少几个动作）；待机（idle）没做出来就算整套失败。"""
    from PIL import Image

    names = clip_names()
    work = settings.media_dir / "u" / user_id / ("m" + secrets.token_hex(8))
    work.mkdir(parents=True, exist_ok=True)
    tmp = work / "_raw"
    tmp.mkdir()
    try:
        base = base_pose(Image.open(portrait_path))
        base.save(tmp / "base.png")
        base_uri = _data_uri(base)
        done, made = [0], {}

        def one(name: str):
            try:
                clip(base_uri, ACTIONS[name], tmp / f"{name}.mp4")
                made[name] = tmp / f"{name}.mp4"
            except Exception as e:  # noqa: BLE001
                log.warning("动作 %s 没做出来：%s", name, e)
            done[0] += 1
            if progress:
                progress(done[0], len(names))

        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(one, names))
        if "idle" not in made:
            raise MotionError("待机动作没做出来，动图做不成")
        clips = {n: _frames(p) for n, p in made.items()}
        box = _box(list(clips.values()))
        still = None
        for n, frames in clips.items():
            first = _encode(frames, box, work / f"{n}.webm")
            if n == "idle":
                still = first
        still.save(work / "still.webp", "WEBP", quality=88)
        have = set(clips)
        spec = {"name": "", "style": "自己创建的角色", "rest": "idle", "talk": "talk" if "talk" in have else "idle",
                "clips": {n: f"{n}.webm" for n in clips},
                "idle": [n for n in ("happy", "think", "nod") if n in have],
                "moves": {k: [x for x in v if x in have] for k, v in MOVES.items() if any(x in have for x in v)},
                "faces": {k: [x for x in v if x in have] for k, v in FACES.items() if any(x in have for x in v)},
                "still": "still.webp", "encoded": f"vp9 h{HEIGHT} crf{CRF}"}
        (work / "chibi.json").write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        rel = f"/media/u/{user_id}/{work.name}"
        return {"portrait": {"kind": "chibi", "src": f"{rel}/chibi.json", "still": f"{rel}/still.webp"}, "clips": len(clips)}
    except Exception:
        import shutil
        shutil.rmtree(work, ignore_errors=True)
        raise
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
