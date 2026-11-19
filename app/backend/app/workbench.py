"""外观工作台：用一句话设计角色立绘，接着用一句话改，再一键生成整套表情（换表情时换图）。

dashscope：百炼千问图像（IMAGE_MODEL，默认 qwen-image-3.0），文生图和“参考图 + 修改说明”都走同一个接口。
self：自建生图服务（app/gpu/image_server.py，IMAGE_BASE_URL），接口和百炼一样；出错时有百炼密钥就退回百炼。
mock：测试用，生成纯色块，不调外部服务。
新画的形象都参考两位官方角色的立绘（只学画风，不照搬长相），画风和官方统一。
生成的图片用二次元抠图模型（anime-seg / isnetis，data/models/anime-seg/）去掉背景，没有模型时退回“去掉和边缘连通的白底”；
缩到 768×1152 以内，存成 WebP 放在 data/media/u/<用户>/，通过 /media/... 访问（文件名随机，不可猜）。
每人每天最多生成 IMAGE_DAILY_LIMIT 张，按 world_events 里的记录数。
"""
from __future__ import annotations

import base64
import io
import json
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import credits, events, media
from .auth import current_user
from .config import locale, settings
from .db import get_db
from .models import User, WorldEvent
from .persona_io import check_content
from .personas import EXPRESSIONS, PersonaError

log = logging.getLogger("krino.workbench")
router = APIRouter(prefix="/api/workbench", tags=["workbench"])

MAX_W, MAX_H = 768, 1152
EXPRESSION_PROMPTS = {
    "zh": {"neutral": "平静自然、没有特别情绪的表情", "calm": "温和放松的浅浅微笑", "happy": "开心地笑，眼睛弯成月牙，嘴巴张开",
           "shy": "害羞：脸颊通红，眼睛看向一边，嘴角微微抿着", "sad": "难过：眉毛下垂，眼角含着泪光，嘴角向下",
           "worried": "担心：眉头微皱，眼神不安", "angry": "生气：皱眉瞪眼，鼓起腮帮子", "surprised": "惊讶：睁大眼睛，嘴巴张成 O 形",
           "sleepy": "困倦：眼睛半眯，打着哈欠", "focused": "认真专注：目光坚定，嘴唇抿紧"},
    "en": {"neutral": "a calm, neutral expression", "calm": "a gentle, relaxed slight smile", "happy": "a big happy smile, eyes curved, mouth open",
           "shy": "shy: deeply blushing cheeks, eyes looking away, lips pressed", "sad": "sad: drooping brows, teary eyes, mouth turned down",
           "worried": "worried: slightly furrowed brows, uneasy eyes", "angry": "angry: frowning, glaring, puffed cheeks",
           "surprised": "surprised: wide eyes, mouth in an O shape", "sleepy": "sleepy: half-closed eyes, yawning",
           "focused": "focused and serious: determined eyes, lips pressed together"},
}
PROMPTS = {
    "zh": {"design": "单个角色的全身立绘，正面或微侧身站姿，从头到脚完整入画，角色居中，纯白色背景，没有文字、水印、边框和其他角色。"
                     "没有特别说明时用日系二次元画风、干净线条、柔和上色。角色不一定是人：描述的是动物、机器人、精灵或物件就照着画，"
                     "不要画成人类；是人形角色时，角色是成年人。角色设定：{prompt}",
           "edit": "保持同一个角色（长相、发型、服装、画风）和纯白色背景、构图不变，只做这个修改：{prompt}",
           "expression": "保持同一个角色（长相、发型、服装、姿势、画风）、纯白色背景和构图完全不变，只把面部表情改成：{prompt}"},
    "en": {"design": "Full-body standing portrait of a single character, front or three-quarter view, head to toe in frame, centered, "
                     "plain pure white background, no text, watermark, border or other people. Unless specified, use a clean anime style "
                     "with soft coloring. The character need not be human: if it's an animal, robot, spirit or object, draw exactly that, "
                     "not a human; a humanoid character is an adult. Character: {prompt}",
           "edit": "Keep the exact same character (face, hair, outfit, art style), the pure white background and the composition; "
                   "only make this change: {prompt}",
           "expression": "Keep the exact same character (face, hair, outfit, pose, art style), the pure white background and the "
                         "composition unchanged; only change the facial expression to: {prompt}"},
}


# 画新形象时一起发给模型的官方立绘：只用来统一画风
STYLE_REFS = ("krino.png", "whale-girl.png")
STYLE_NOTE = {
    "zh": "前两张图是本作品官方角色的立绘，只用来统一画风：照着它们的线条、上色、光影、头身比例、精致程度和构图来画，"
          "但不要照搬她们的长相、发型、发色、服装和配饰，画一个全新的角色。",
    "en": "The first two images are official character art from this product, given only as a style guide: match their line work, "
          "coloring, lighting, proportions, level of detail and composition, but do not copy their faces, hair, colors, outfits "
          "or accessories. Draw a brand-new character. ",
}
_style_refs: list[str] | None = None


def style_content(lang: str, prompt: str) -> list[dict]:
    """画一个新角色：官方立绘当画风参考 + 设定。参考图读不到（比如测试环境）就只发文字。"""
    global _style_refs
    if _style_refs is None:
        from PIL import Image
        try:
            _style_refs = [_as_reference(Image.open(settings.frontend_dir / "assets" / n))[0] for n in STYLE_REFS]
        except OSError:
            _style_refs = []
    text = PROMPTS[lang]["design"].format(prompt=prompt)
    if not _style_refs:
        return [{"text": text}]
    return [*({"image": r} for r in _style_refs), {"text": STYLE_NOTE[lang] + text}]


RETRY_WAITS = (3, 6, 12)  # 限流时依次等几秒再试
EXPRESSION_WORKERS = 2  # 整套表情同时发几个请求：太多会触发百炼限流


class ImageError(RuntimeError):
    pass


# ---------- 生成 ----------

def _dashscope(content: list[dict], n: int, size: str, base_url: str | None = None, key: str | None = None) -> list[bytes]:
    """百炼生图；自建服务接口一样，传 base_url / key 就打到自建服务。"""
    base_url = base_url or settings.dashscope_base_url
    key = key if base_url != settings.dashscope_base_url else settings.dashscope_api_key
    if base_url == settings.dashscope_base_url and not key:
        raise ImageError("没有配置 DASHSCOPE_API_KEY，外观工作台用不了")
    body = {"model": settings.image_model, "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"n": n, "size": size, "watermark": False}}
    try:
        with httpx.Client(timeout=httpx.Timeout(180, connect=10), trust_env=base_url == settings.dashscope_base_url) as c:
            for wait in (*RETRY_WAITS, None):  # 百炼按每秒请求数限流（429）：等一等再试，不直接报错
                r = c.post(base_url.rstrip("/") + "/services/aigc/multimodal-generation/generation",
                           json=body, headers={"Authorization": f"Bearer {key}"} if key else {})
                if r.status_code != 429 or wait is None:
                    break
                log.warning("百炼生图限流，%s 秒后重试", wait)
                time.sleep(wait + random.random())
            if r.status_code in (429, 503):  # 503：自建服务那张卡正被别的任务占着，或模型还在加载
                raise ImageError("图像服务太忙了，过一会儿再点一次")
            if r.status_code != 200:
                log.error("百炼生图 %s: %s", r.status_code, r.text[:300])
                code = (r.json() if r.headers.get("content-type", "").startswith("application/json") else {}).get("code", "")
                if code in ("DataInspectionFailed", "data_inspection_failed") or "Inspection" in code:
                    raise ImageError("描述或图片没有通过内容审核，换个说法试试")
                raise ImageError(f"生成图片出错（{r.status_code}）")
            urls = [x["image"] for ch in r.json()["output"]["choices"] for x in ch["message"]["content"] if x.get("image")]
            if not urls:
                raise ImageError("没有生成出图片，换个说法试试")
            return [c.get(u).content for u in urls]
    except httpx.HTTPError as e:
        raise ImageError("无法连接图像服务") from e
    except (KeyError, ValueError, TypeError) as e:
        raise ImageError("图像服务返回的格式不对") from e


def _mock(n: int, size: str) -> list[bytes]:
    from PIL import Image

    w, h = (int(x) for x in size.split("*"))
    out = []
    for _ in range(n):
        img = Image.new("RGB", (w, h), "white")
        img.paste(tuple(random.randint(40, 200) for _ in range(3)), (w // 4, h // 8, w * 3 // 4, h * 7 // 8))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        out.append(buf.getvalue())
    return out


def _generate(content: list[dict], n: int, size: str) -> tuple[list[bytes], str]:
    """返回图片和实际用的服务（mock / self / dashscope），收费只算百炼。"""
    p = settings.image_provider
    if p == "mock":
        return _mock(n, size), "mock"
    if p == "self":
        if not settings.image_base_url:
            raise ImageError("没有配置 IMAGE_BASE_URL（自建生图服务地址）")
        try:
            return _dashscope(content, n, size, settings.image_base_url, settings.image_api_key), "self"
        except ImageError as e:
            if not settings.dashscope_api_key:
                raise
            log.warning("自建生图不可用，改用百炼：%s", e)
        return _dashscope(content, n, size), "dashscope"
    if p != "dashscope":
        raise ImageError("服务端没有配置图像生成（IMAGE_PROVIDER）")
    return _dashscope(content, n, size), "dashscope"


# ---------- 处理和保存 ----------

def cut_background(img):
    """去掉和画面边缘连通的纯白背景，变成透明。阈值很严（接近纯白才算），人物身上的白色（米饭、白衣服）基本不受影响；
    边缘往里收 2 像素再羽化，去掉白边。"""
    import numpy as np
    from PIL import Image, ImageDraw, ImageFilter

    img = img.convert("RGB")
    a = np.asarray(img).astype(np.int16)
    lo, hi = a.min(2), a.max(2)
    mask = Image.fromarray(((lo >= 250) & (hi - lo <= 10)).astype(np.uint8) * 255, "L").copy()
    w, h = mask.size
    for x, y in [(x, 0) for x in range(0, w, 3)] + [(x, h - 1) for x in range(0, w, 3)] + \
                [(0, y) for y in range(0, h, 3)] + [(w - 1, y) for y in range(0, h, 3)]:
        if mask.getpixel((x, y)) == 255:
            ImageDraw.floodfill(mask, (x, y), 128)
    bg = mask.point(lambda v: 255 if v == 128 else 0).filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(1.2))
    out = img.convert("RGBA")
    out.putalpha(bg.point(lambda v: 255 - v))
    return out


SEG_MODEL = "anime-seg/isnetis.onnx"
SEG_SIZE = 1024
_seg = None  # onnxruntime 会话；None = 还没试着加载，False = 加载不了（没装 onnxruntime 或没有模型）


def _segmenter():
    global _seg
    if _seg is None:
        path = settings.models_dir / SEG_MODEL
        try:
            import onnxruntime as ort
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 2  # 网站服务器只有 4 核：抠图时别把对话都卡住
            _seg = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"]) if path.is_file() else False
        except Exception as e:  # noqa: BLE001
            log.warning("抠图模型加载不了，退回去白底：%s", e)
            _seg = False
        if _seg is False:
            log.warning("没有抠图模型（%s）：用 scripts/fetch_assets.py 下载；先退回去白底", path)
    return _seg or None


def matte(img):
    """二次元抠图：模型给出人物的透明度，再把半透明边缘里混进来的白底颜色去掉（不然头发、尾巴边上一圈白边）。
    一张 768×1152 在网站服务器上约 1~2 秒。模型用不了时退回 cut_background。"""
    import numpy as np
    from PIL import Image

    sess = _segmenter()
    if sess is None:
        return cut_background(img)
    rgb = img.convert("RGB")
    w, h = rgb.size
    k = SEG_SIZE / max(w, h)
    nw, nh = int(w * k), int(h * k)
    x = np.zeros((SEG_SIZE, SEG_SIZE, 3), np.float32)
    top, left = (SEG_SIZE - nh) // 2, (SEG_SIZE - nw) // 2
    x[top:top + nh, left:left + nw] = np.asarray(rgb.resize((nw, nh), Image.BILINEAR), np.float32) / 255
    m = sess.run(None, {sess.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0][top:top + nh, left:left + nw]
    a = np.asarray(Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.BILINEAR), np.float32) / 255
    a[a < 0.04] = 0  # 背景上零星的一点点不透明
    c = np.asarray(rgb, np.float32)
    bg = np.median(np.concatenate([c[0], c[-1], c[:, 0], c[:, -1]]), axis=0)  # 背景色（一般是白的）：取四条边的中位数
    edge = (a > 0) & (a < 0.98)
    fg = c.copy()
    fg[edge] = (c[edge] - (1 - a[edge, None]) * bg) / np.maximum(a[edge, None], 0.05)  # 去掉混进来的背景色
    out = np.dstack([np.clip(fg, 0, 255), a * 255]).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def _process(data: bytes):
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImageError("生成的图片打不开") from e
    img.thumbnail((MAX_W, MAX_H))
    return matte(img)


def _save(user_id: str, img) -> str:
    return media.save_image(user_id, img)


def _local(src: str):
    """把立绘地址（/media/... 或 /static/assets/...）对应到本地文件；只认本站的。"""
    from PIL import Image

    if ".." in src:
        raise ImageError("找不到这张图")
    if src.startswith("/media/"):
        path = settings.media_dir / src[len("/media/"):]
    elif src.startswith("/static/assets/"):
        path = settings.frontend_dir / "assets" / src[len("/static/assets/"):]
    else:
        raise ImageError("只能在本站的立绘上修改")
    if not path.is_file():
        raise ImageError("找不到这张图")
    return Image.open(path)


def _as_reference(img) -> tuple[str, str]:
    """参考图：透明处垫白底（和生成时的背景一致），转成 data URI；顺便算出输出尺寸，保持比例不变。"""
    from PIL import Image

    rgba = img.convert("RGBA")
    base = Image.new("RGB", rgba.size, "white")
    base.paste(rgba, mask=rgba.split()[3])
    base.thumbnail((MAX_W, MAX_H))
    w, h = base.size
    k = max(1.0, 512 / min(w, h))  # 接口要求每边至少 512
    size = f"{int(w * k) // 16 * 16}*{int(h * k) // 16 * 16}"
    buf = io.BytesIO()
    base.save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode(), size


# ---------- 次数 ----------

def _used_today(db: Session, user_id: str) -> int:
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(WorldEvent).where(
        WorldEvent.user_id == user_id, WorldEvent.kind == "image", WorldEvent.created_at >= start)) or 0


def daily_limit(user: User) -> int:
    """每人每天能生成几张：IMAGE_USER_LIMITS 里单独设了的账号按它来（比如测试账号），其余按 IMAGE_DAILY_LIMIT。"""
    return settings.image_user_limits.get(user.username, settings.image_daily_limit)


def _check_quota(db: Session, user: User, n: int) -> None:
    credits.check(db, user, credits.image_points(n))
    if credits.daily_limit(user):  # 设了积分上限的账号由积分来管，不再按张数限
        return
    limit = daily_limit(user)
    if limit - _used_today(db, user.id) < n:
        raise HTTPException(429, f"今天的生成次数用完了（每天 {limit} 张），明天再来")


def _record(user: User, name: str, n: int, ms: float, provider: str) -> None:
    for _ in range(n):
        events.record("image", name, user_id=user.id, latency_ms=ms,
                      payload={"provider": provider, "model": settings.image_model if provider == "dashscope" else provider})


def _run(user: User, name: str, content: list[dict], n: int, size: str) -> list[str]:
    t0 = time.perf_counter()
    try:
        raw, used = _generate(content, n, size)
        urls = [_save(user.id, _process(b)) for b in raw]
    except ImageError as e:
        raise HTTPException(503, str(e)) from e
    _record(user, name, len(urls), (time.perf_counter() - t0) * 1000, used)
    if used == "dashscope":
        credits.charge_images(user.id, len(urls))
    return urls


# ---------- 接口 ----------

@router.get("")
def info(user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = settings.image_provider
    ready = p == "mock" or (p == "dashscope" and bool(settings.dashscope_api_key)) or (p == "self" and bool(settings.image_base_url))
    from .motion import cost_cny
    return {"ready": ready, "provider": settings.image_provider, "model": settings.image_model,
            "limit": daily_limit(user), "used": _used_today(db, user.id), "expressions": list(EXPRESSIONS),
            "motion": {"ready": settings.image_provider == "mock" or bool(settings.dashscope_api_key),
                       "points": credits.points(cost_cny()), "minutes": "10"},
            "credit_limited": bool(credits.daily_limit(user))}  # 由积分来管的账号，工作台不显示张数


class DesignIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=500)
    base: str | None = Field(default=None, max_length=200)  # 有参考图 = 在这张上修改
    n: int = Field(default=1, ge=1, le=4)  # 默认一张：一个角色一个形象


@router.post("/design")
def design(body: DesignIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        check_content(body.prompt)
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    lang = "en" if locale() == "en" else "zh"
    if body.base:
        try:
            ref, size = _as_reference(_local(body.base))
        except ImageError as e:
            raise HTTPException(400, str(e)) from e
        n = min(body.n, 2)  # 修改一般看两张就够
        _check_quota(db, user, n)
        content = [{"image": ref}, {"text": PROMPTS[lang]["edit"].format(prompt=body.prompt)}]
        return {"images": _run(user, "edit", content, n, size), "used": _used_today(db, user.id)}
    _check_quota(db, user, body.n)
    content = style_content(lang, body.prompt)
    return {"images": _run(user, "design", content, body.n, f"{MAX_W}*{MAX_H}"), "used": _used_today(db, user.id)}


class ExpressionsIn(BaseModel):
    base: str = Field(max_length=200)
    expressions: list[str] = Field(min_length=1, max_length=len(EXPRESSIONS))


@router.post("/expressions")
def expressions(body: ExpressionsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """以一张立绘为底，同时生成几种表情（并发，一般一分钟左右）。失败的表情单独报错，不影响其他的。"""
    if any(x not in EXPRESSIONS for x in body.expressions):
        raise HTTPException(400, "不认识的表情")
    try:
        ref, size = _as_reference(_local(body.base))
    except ImageError as e:
        raise HTTPException(400, str(e)) from e
    wanted = list(dict.fromkeys(body.expressions))
    _check_quota(db, user, len(wanted))
    lang = "en" if locale() == "en" else "zh"

    def one(expr: str) -> tuple[str, str | None, str | None]:
        content = [{"image": ref}, {"text": PROMPTS[lang]["expression"].format(prompt=EXPRESSION_PROMPTS[lang][expr])}]
        try:
            return expr, _run(user, "expression", content, 1, size)[0], None
        except HTTPException as e:
            return expr, None, str(e.detail)

    with ThreadPoolExecutor(max_workers=EXPRESSION_WORKERS) as pool:
        results = list(pool.map(one, wanted))
    return {"images": {e: u for e, u, _ in results if u}, "errors": {e: m for e, _, m in results if m},
            "used": _used_today(db, user.id)}


class UploadIn(BaseModel):
    image: str = Field(max_length=4_500_000)


@router.post("/upload")
def upload(body: UploadIn, user: User = Depends(current_user)):
    """上传自己画的立绘：存成文件（不去背景，透明 PNG 原样保留），之后可以在它上面修改、生成表情。"""
    if not body.image.startswith("data:image/"):
        raise HTTPException(400, "只支持 PNG / JPEG / WebP")
    try:
        return {"src": media.store({"portrait": {"kind": "image", "src": body.image}}, user.id)["portrait"]["src"]}
    except media.MediaError as e:
        raise HTTPException(400, str(e)) from e


def media_root():
    return media.root()



# ---------- 一句话生成整个角色：灵魂 + 肉体 + 声音 ----------

class CharacterIn(BaseModel):
    prompt: str = Field(default="", max_length=500)       # 一句话描述（没有 draft 时用它写灵魂）
    draft: dict | None = None                              # 新角色窗口里写好 / 改好的灵魂：{persona, behavior, lore, appearance}
    character_id: str | None = Field(default=None, max_length=32)  # 在哪个角色的工作台上点的（只用来记来源，不会改她）
    wait: bool = False  # True = 画完形象、设计完声音再返回（测试用）；默认马上返回，后台补上
    motion: bool = False  # 同时做动图（会做动作的 Q 版小人）：多花约 8 元、多等 10 分钟左右


def _check_motion(db: Session, user: User) -> None:
    from . import motion

    if settings.image_provider == "mock":
        return
    if not settings.dashscope_api_key:
        raise HTTPException(400, "服务器没有配置视频生成（DASHSCOPE_API_KEY），做不了动图")
    credits.check(db, user, credits.points(motion.cost_cny()))


def _set_origin(cid: str, **kw) -> None:
    """后台任务做到哪了，写在角色的 origin 上（页面上的进度卡片读它）。用自己的数据库会话。"""
    from .db import SessionLocal
    from .models import Character

    with SessionLocal() as db:
        c = db.get(Character, cid)
        if c is not None:
            o = dict(c.origin or {})
            for k, v in kw.items():
                if v is None:
                    o.pop(k, None)
                else:
                    o[k] = v
            c.origin = o
            db.commit()


MOTION_TRIES = 3  # 同一个动图任务最多因为服务重启接着做几次，再断就放弃（免得一直重启、一直重做）


def _make_motion(cid: str, user_id: str, image_src: str, key: str, resume: dict | None = None) -> dict | None:
    """做动图（app/motion.py），进度写在 origin[key]：{done, total, started, at, dir, image, tries}；做成了按实际片段数扣钱。
    失败返回 None（角色照样用立绘）。dir 是工作目录：服务重启打断了，resume_jobs() 拿它接着做，已经下好的片段不重做。"""
    from . import motion

    total = len(motion.clip_names())
    resume = resume or {}
    started = int(resume.get("started") or time.time())  # 开始的时间只记一次：页面刷新、接着做，“已用时间”都接着算
    work = settings.media_dir / "u" / user_id / resume["dir"] if resume.get("dir") else motion.new_work(user_id)
    job = {"done": int(resume.get("done", 0)), "total": total, "started": started, "dir": work.name, "image": image_src,
           "tries": int(resume.get("tries", 0)) + (1 if resume else 0)}

    def save(d: int, t: int) -> None:
        job.update(done=d, total=t, at=int(time.time()))  # at：最近一次有进展的时间，用来判断任务还活着没有
        _set_origin(cid, **{key: dict(job)})

    save(job["done"], total)
    try:
        out = motion.make(user_id, settings.media_dir / image_src[len("/media/"):], progress=save, work=work)
    except Exception as e:  # noqa: BLE001
        log.warning("角色 %s 的动图没做出来：%s", cid, e)
        events.error("motion", f"{type(e).__name__}: {e}")
        _set_origin(cid, **{key: None, "motion_error": str(e)[:120]})
        return None
    credits.charge(user_id, "motion", settings.image_price_cny + out["clips"] * settings.motion_clip_price_cny, clips=out["clips"])
    _set_origin(cid, **{key: None, "motion_error": None})
    return out["portrait"]


def _with_motion(b: dict, chibi: dict) -> dict:
    """动图做好了：换上它，立绘留在“自己的形象”里随时换回来；动作白名单换成这套动图会的。"""
    from .motion import MOVES

    looks = [x for x in (b.get("looks") or []) if x.get("kind") != "chibi"]
    cur = b.get("portrait")
    if cur and cur.get("kind") == "image" and not any(x["src"] == cur["src"] for x in looks):
        looks.insert(0, {"kind": "image", "src": cur["src"]})
    spec = json.loads((settings.media_dir / chibi["src"][len("/media/"):]).read_text(encoding="utf-8"))
    anims = [a for a in MOVES if a in spec.get("moves", {})]
    return {**b, "portrait": chibi, "looks": [chibi, *looks][:8], **({"animations": anims} if anims else {})}


def _finish_character(cid: str, user_id: str, look_prompt: str, voice: dict, greeting: str, motion: bool = False,
                      lang: str = "zh") -> None:
    """后台给新角色补上形象和声音：两件事同时做（画图约一分钟，设计声音几秒）；勾了动图的，立绘画好再做动图（10 分钟左右）。
    全部做完写回角色、去掉“正在创建”。用自己的数据库会话；失败了也要把“正在创建”去掉，角色照样能聊
    （没有形象时显示名字首字的铭牌；动图没做成就用立绘）。"""
    from .db import SessionLocal
    from .models import Character

    t0 = time.perf_counter()
    image, error = None, None
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            return

        def draw():
            return _run(user, "design", style_content(lang, look_prompt), 1, f"{MAX_W}*{MAX_H}")[0]

        def dot():  # 像素小人：按设定和这次的外貌描述定，和画图、声音一起做（几秒）
            from . import pixel
            with SessionLocal() as pdb:
                c0 = pdb.get(Character, cid)
                return pixel.make(c0, look_prompt, payer=user_id) if c0 is not None else None

        def speak():
            with SessionLocal() as vdb:
                return _own_voice(vdb, db.get(User, user_id), dict(voice), greeting)

        done: list[str] = []

        def mark(step: str) -> None:  # 哪一步做完就记下来（页面上的“创建中”卡片按它打勾）
            done.append(step)
            _set_origin(cid, done=sorted(done))

        new_voice, look = voice, None
        with ThreadPoolExecutor(3) as pool:
            fi, fv, fp = pool.submit(draw), pool.submit(speak), pool.submit(dot)
            for f in as_completed((fi, fv, fp)):
                if f is fp:
                    try:
                        look = fp.result()
                    except Exception:  # noqa: BLE001  没定下来：打开小镇时会再补
                        log.exception("新角色 %s 的像素小人没定下来", cid)
                    continue
                if f is fi:
                    try:
                        image = fi.result()
                    except Exception as e:  # noqa: BLE001
                        error = getattr(e, "detail", str(e))
                        log.warning("新角色 %s 的形象没画出来：%s", cid, error)
                    mark("portrait")
                else:
                    try:
                        new_voice = fv.result()
                    except Exception:  # noqa: BLE001
                        log.exception("新角色 %s 的声音没设计出来", cid)
                    mark("voice")
        if motion and image:  # 动图要做十来分钟：先把立绘和声音存好，中途被重启打断了，接着做的时候也不会丢
            with SessionLocal() as sdb:
                x = sdb.get(Character, cid)
                if x is not None:
                    x.behavior = {**(x.behavior or {}), "portrait": {"kind": "image", "src": image},
                                  "looks": [{"kind": "image", "src": image}],
                                  "voice": {**((x.behavior or {}).get("voice") or {}), **new_voice}}
                    sdb.commit()
        chibi = _make_motion(cid, user_id, image, "motion") if motion and image else None
        db.expire_all()  # 进度用别的会话改过 origin
        c = db.get(Character, cid)
        if c is None:  # 等的时候被删了
            return
        b = dict(c.behavior or {})
        if image:
            b["portrait"] = {"kind": "image", "src": image}
            b["looks"] = [{"kind": "image", "src": image}]
        if chibi:
            b = _with_motion(b, chibi)
        b["voice"] = {**(b.get("voice") or {}), **new_voice}
        if look:
            b["pixel"] = look
        c.behavior = b
        o = {k: v for k, v in (c.origin or {}).items() if k not in ("pending", "done", "motion")}
        if error:
            o["portrait_error"] = str(error)[:120]
        c.origin = o
        db.commit()
    log.info("新角色 %s 补完形象和声音%s（%.0fs）%s", cid, "、动图" if chibi else "", time.perf_counter() - t0, "，形象失败" if error else "")


def _own_voice(db: Session, user: User, voice: dict, greeting: str) -> dict:
    """新角色有声音描述、还没有专属声音时，按描述设计一个（自建语音才能设计）。设计不了就照旧用默认声音，不耽误建角色。"""
    from . import personas
    from .voice import _qwen_voices

    if settings.tts_provider != "qwen" or not voice.get("style") or voice.get("voice") in _qwen_voices():
        return voice
    try:
        vid, _ = personas.design_character_voice(db, user, voice["style"], greeting)
        voice["voice"] = vid
    except (PersonaError, HTTPException) as e:
        log.warning("新角色的声音没设计出来，先用默认声音：%s", getattr(e, "detail", e))
    return voice


@router.post("/character")
def character(body: CharacterIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """设计一个新角色：灵魂（人设、开场白、对话示例、音色）+ 按外貌画一张形象，总是新建。
    已有角色的灵魂不在这里改（改了就不是她了）；灵魂只在新建时设计。"""
    from . import persona_io, personas

    if body.character_id:
        personas.get_owned(db, user, body.character_id)  # 只校验是自己的角色
    if not body.draft and not body.prompt.strip():
        raise HTTPException(400, "先描述一下你想要的角色")
    try:
        if body.prompt.strip():
            check_content(body.prompt)
        personas.check_slot(db, user)
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    _check_quota(db, user, 1)
    if body.motion:
        _check_motion(db, user)
    try:
        if body.draft:
            raw = body.draft
            d0 = persona_io.from_package({"format": persona_io.FORMAT, "persona": raw.get("persona") or {}, "lore": raw.get("lore") or []})
            if not str(d0.persona.get("name") or "").strip():
                raise PersonaError("先起个名字吧")
            beh = raw.get("behavior") if isinstance(raw.get("behavior"), dict) else {}
            d = {"persona": d0.persona, "lore": d0.lore, "appearance": str(raw.get("appearance") or "")[:500],
                 "behavior": personas.validate_behavior({k: v for k, v in beh.items() if k != "portrait"} or None)
                 if beh else personas.default_behavior()}
        else:
            d = personas.generate_draft(body.prompt, None, payer=user.id)
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    lang = "en" if locale() == "en" else "zh"
    p = d["persona"]
    who = body.prompt.strip() or f"{p.get('name', '')}，{p.get('tagline', '')}"
    look = f"{who}。{d.get('appearance') or ''}" if lang == "zh" else f"{who}. {d.get('appearance') or ''}"
    look_prompt = look[:800]  # draw() 里再套上画风参考和设计模板
    behavior = {k: v for k, v in d["behavior"].items() if k != "portrait"}  # 先没有形象：显示名字铭牌，画好了再换上
    try:  # 角色马上建好（灵魂已经定了），形象和声音在后台补；关掉窗口、刷新页面都不影响
        new = personas.create(db, user, persona=p, behavior=behavior, lore=d["lore"],
                              origin={"source": "created", "prompt": who[:200], "pending": int(time.time())})
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    db.commit()
    job = (new.id, user.id, look_prompt, dict(behavior.get("voice") or {}), p.get("greeting", ""), body.motion, lang)
    if body.wait:
        _finish_character(*job)
        db.expire_all()
        new = personas.get_owned(db, user, new.id)
    else:
        import threading

        threading.Thread(target=_finish_character, args=job, name=f"char-{new.id[:8]}", daemon=True).start()
    return {"character": personas.full(new), "created": True, "used": _used_today(db, user.id)}


class MotionIn(BaseModel):
    character_id: str = Field(max_length=32)


def _apply_motion(cid: str, chibi: dict | None) -> None:
    """已有角色补做的动图做完了：换上（做成了的话），去掉“正在做”。"""
    from .db import SessionLocal
    from .models import Character

    with SessionLocal() as db2:
        x = db2.get(Character, cid)
        if x is not None:
            if chibi:
                x.behavior = _with_motion(dict(x.behavior or {}), chibi)
                x.version += 1
            x.origin = {k: v for k, v in (x.origin or {}).items() if k != "motion_job"}
            db2.commit()


def _finish_new_with_motion(cid: str, chibi: dict | None) -> None:
    """新建角色时勾了动图、做动图那一步被重启打断又接着做完：换上动图（做成了的话），去掉“正在创建”。"""
    from .db import SessionLocal
    from .models import Character

    with SessionLocal() as db2:
        x = db2.get(Character, cid)
        if x is not None:
            if chibi:
                x.behavior = _with_motion(dict(x.behavior or {}), chibi)
            x.origin = {k: v for k, v in (x.origin or {}).items() if k not in ("pending", "done", "motion")}
            db2.commit()


def _legacy_dir(user_id: str, job: dict) -> dict:
    """这次改动之前开始的任务没记工作目录：找这个用户下还没做完（有 _raw/base.png、没有 chibi.json）的最新那个。"""
    root = settings.media_dir / "u" / user_id
    dirs = sorted((d for d in root.glob("m*") if (d / "_raw" / "base.png").is_file() and not (d / "chibi.json").is_file()),
                  key=lambda d: d.stat().st_mtime, reverse=True) if root.is_dir() else []
    return {**job, "dir": dirs[0].name} if dirs else job


def resume_jobs() -> None:
    """服务启动时：把被重启打断的动图任务接着做完（后台线程，已经下好的片段不重做）。部署、重启都会打断后台任务。"""
    import threading

    from sqlalchemy import select as _select

    from .db import SessionLocal
    from .models import Character

    if settings.image_provider == "mock" or not settings.dashscope_api_key:
        return
    with SessionLocal() as db:
        rows = db.scalars(_select(Character).where(Character.origin.has_key("motion_job") | Character.origin.has_key("motion"))).all()
        todo = []
        for c in rows:
            o = c.origin or {}
            for key in ("motion_job", "motion"):
                job = o.get(key)
                if not isinstance(job, dict):
                    continue
                img = job.get("image") or ((c.behavior or {}).get("portrait") or {}).get("src", "")
                if not str(img).startswith("/media/") or int(job.get("tries", 0)) >= MOTION_TRIES:
                    log.warning("角色 %s 的动图任务接不上了（%s），放弃", c.id, "试过太多次" if img else "没有立绘")
                    _set_origin(c.id, **{key: None, "motion_error": "做到一半被打断，没能接着做完"})
                    if key == "motion":
                        _set_origin(c.id, pending=None, done=None)
                    continue
                todo.append((c.id, c.owner_id, img, key, _legacy_dir(c.owner_id, job) if not job.get("dir") else job))

    def run(cid, uid, img, key, job):
        log.info("接着做角色 %s 的动图（%s，已有 %s 段）", cid, job.get("dir"), job.get("done"))
        chibi = _make_motion(cid, uid, img, key, resume=job)
        (_apply_motion if key == "motion_job" else _finish_new_with_motion)(cid, chibi)

    for args in todo:
        threading.Thread(target=run, args=args, name=f"motion-resume-{args[0][:8]}", daemon=True).start()


@router.post("/motion")
def make_motion(body: MotionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """给自己创建的角色补做动图（用她现在的立绘）。后台做，10 分钟左右；做的时候照常能聊，做好了自动换上。"""
    import threading

    from . import motion, personas

    c = personas.get_owned(db, user, body.character_id)
    if personas.template_of(c) is not None:
        raise HTTPException(400, "官方角色已经有自己的动图了")
    p = (c.behavior or {}).get("portrait") or {}
    img = p if p.get("kind") == "image" else next((x for x in (c.behavior or {}).get("looks") or [] if x.get("kind") == "image"), None)
    if not img or not str(img.get("src", "")).startswith("/media/"):
        raise HTTPException(400, "先给她画一张立绘（或上传一张），再做动图")
    if personas._motion_job(c):  # 正在做（最近半小时有进展）；卡死很久的不挡，让人重新做
        raise HTTPException(409, "动图已经在做了")
    _check_motion(db, user)
    _set_origin(c.id, motion_job={"done": 0, "total": 0, "started": int(time.time())})

    def run():
        chibi = _make_motion(c.id, user.id, img["src"], "motion_job") if settings.image_provider != "mock" else None
        _apply_motion(c.id, chibi)

    threading.Thread(target=run, name=f"motion-{c.id[:8]}", daemon=True).start()
    return {"ok": True, "cost": credits.points(motion.cost_cny())}

