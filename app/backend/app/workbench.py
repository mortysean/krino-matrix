"""外观工作台：用一句话设计角色立绘，接着用一句话改，再一键生成整套表情（换表情时换图）。

dashscope：百炼千问图像（IMAGE_MODEL，默认 qwen-image-3.0），文生图和“参考图 + 修改说明”都走同一个接口。
self：自建生图服务（app/gpu/image_server.py，IMAGE_BASE_URL），接口和百炼一样；出错时有百炼密钥就退回百炼。
mock：测试用，生成纯色块，不调外部服务。
生成的图片去掉白底、缩到 768×1152 以内，存成 WebP 放在 data/media/u/<用户>/，通过 /media/... 访问（文件名随机，不可猜）。
每人每天最多生成 IMAGE_DAILY_LIMIT 张，按 world_events 里的记录数。
"""
from __future__ import annotations

import base64
import io
import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
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


def _process(data: bytes):
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise ImageError("生成的图片打不开") from e
    img.thumbnail((MAX_W, MAX_H))
    return cut_background(img)


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
    return {"ready": ready, "provider": settings.image_provider, "model": settings.image_model,
            "limit": daily_limit(user), "used": _used_today(db, user.id), "expressions": list(EXPRESSIONS),
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
    content = [{"text": PROMPTS[lang]["design"].format(prompt=body.prompt)}]
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
    prompt: str = Field(min_length=1, max_length=500)
    character_id: str | None = Field(default=None, max_length=32)  # 在哪个角色的工作台上点的；不给 = 新建一个角色


@router.post("/character")
def character(body: CharacterIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """先写灵魂（人设、开场白、对话示例，顺便挑好音色、写好外貌），再按外貌画一张形象。
    在官方角色（KRINO、大肥鱼）的工作台上点：新建一个角色，官方角色保持不变；
    在自己的角色上点：直接换成新的（旧的留在版本历史里，可以恢复）。"""
    from . import personas

    c = personas.get_owned(db, user, body.character_id) if body.character_id else None
    try:
        check_content(body.prompt)
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    official = c is None or personas.template_of(c) is not None  # 新建（官方角色不覆盖）
    if official:
        try:
            personas.check_slot(db, user)
        except PersonaError as e:
            raise HTTPException(400, str(e)) from e
    _check_quota(db, user, 1)
    try:
        d = personas.generate_draft(body.prompt, None, payer=user.id)
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    lang = "en" if locale() == "en" else "zh"
    look = f"{body.prompt}。{d.get('appearance') or ''}" if lang == "zh" else f"{body.prompt}. {d.get('appearance') or ''}"
    image = _run(user, "design", [{"text": PROMPTS[lang]["design"].format(prompt=look[:800])}], 1, f"{MAX_W}*{MAX_H}")[0]
    behavior = {**d["behavior"], "portrait": {"kind": "image", "src": image}}
    try:
        if official:
            new = personas.create(db, user, persona=d["persona"], behavior=behavior, lore=d["lore"],
                                  origin={"source": "created", "prompt": body.prompt[:200]})
        else:
            keep = {k: v for k, v in (c.behavior or {}).items() if k not in ("portrait", "voice", "animations")}
            new = personas.save(db, c, persona=d["persona"], behavior={**keep, "portrait": behavior["portrait"], "voice": behavior["voice"]},
                                lore=d["lore"], note="一句话重新生成")
    except PersonaError as e:
        raise HTTPException(400, str(e)) from e
    db.commit()
    return {"character": personas.full(new), "created": official, "used": _used_today(db, user.id)}
