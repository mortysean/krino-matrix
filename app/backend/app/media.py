"""角色形象的图片文件，通过 /media/... 访问：
  data/media/u/<用户>/<随机名>.webp   工作台生成的
  data/media/c/<内容哈希>.webp        上传、导入的（同样的图只存一份）

- store：保存角色时，把 behavior.portrait 里内嵌的图片（data:image/...;base64，来自上传或导入的人设包）
  写成文件，换成 /media/... 地址。数据库里只存地址，不存图片本身。
- embed：导出人设包时反过来，把本站的 /media/... 图片内嵌成 data URI。这样导出的文件“灵魂 + 肉体”都在里面，
  换一台服务器导入、上传工坊都不丢形象。内置立绘（/static/assets/）和 Live2D 每个站点都有，保持地址。
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import secrets

from .config import settings

DATA_URI = re.compile(r"^data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/=\s]+)$")
MAX_IMAGE_BYTES = 3 * 1024 * 1024  # 单张解码后
MAX_SIDE = 1536


class MediaError(ValueError):
    pass


def root():
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    return settings.media_dir


def save_image(user_id: str, img) -> str:
    d = root() / "u" / user_id
    d.mkdir(parents=True, exist_ok=True)
    name = secrets.token_hex(12) + ".webp"
    img.save(d / name, "WEBP", quality=90, method=4)
    return f"/media/u/{user_id}/{name}"


def _from_data_uri(uri: str, user_id: str) -> str:
    from PIL import Image, UnidentifiedImageError

    m = DATA_URI.match(uri)
    if not m:
        raise MediaError("形象图片格式不对，只支持 PNG / JPEG / WebP")
    try:
        raw = base64.b64decode(m.group(2), validate=False)
    except (binascii.Error, ValueError) as e:
        raise MediaError("形象图片数据损坏") from e
    if len(raw) > MAX_IMAGE_BYTES:
        raise MediaError("单张形象图片不能超过 3MB")
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise MediaError("形象图片打不开") from e
    # 按内容命名，放在共享目录：同一个人设包被不同的人导入、上传，图片地址一样，工坊的“重复内容”检查才认得出来
    name = hashlib.sha256(raw).hexdigest()[:32]
    d = root() / "c"
    d.mkdir(parents=True, exist_ok=True)
    if not (d / f"{name}.webp").is_file():
        img.thumbnail((MAX_SIDE, MAX_SIDE))
        img.convert("RGBA").save(d / f"{name}.webp", "WEBP", quality=90, method=4)
    return f"/media/c/{name}.webp"


def store(behavior: dict | None, user_id: str) -> dict | None:
    """把内嵌图片写成文件，返回新的 behavior（不改传进来的对象）。没有内嵌图片时原样返回。"""
    p = (behavior or {}).get("portrait")
    if not isinstance(p, dict):
        return behavior
    src = p.get("src")
    ex = p.get("expressions") if isinstance(p.get("expressions"), dict) else None
    if not (isinstance(src, str) and src.startswith("data:")) and not any(isinstance(v, str) and v.startswith("data:") for v in (ex or {}).values()):
        return behavior
    p = dict(p)
    if isinstance(src, str) and src.startswith("data:"):
        p["src"] = _from_data_uri(src, user_id)
    if ex:
        if len(ex) > 16:
            raise MediaError("表情图太多了")
        p["expressions"] = {k: _from_data_uri(v, user_id) if isinstance(v, str) and v.startswith("data:") else v for k, v in ex.items()}
    return {**behavior, "portrait": p}


def _file(src: str):
    if not src.startswith("/media/") or ".." in src:
        return None
    path = settings.media_dir / src[len("/media/"):]
    return path if path.is_file() else None


def embed(behavior: dict | None) -> dict | None:
    """把本站 /media/ 图片内嵌成 data URI（导出用）。找不到的文件去掉（表情）或改成没有立绘（主图）。"""
    p = (behavior or {}).get("portrait")
    if not isinstance(p, dict):
        return behavior

    def one(src):
        path = _file(src) if isinstance(src, str) else None
        if path is None:
            return None if isinstance(src, str) and src.startswith("/media/") else src
        return "data:image/webp;base64," + base64.b64encode(path.read_bytes()).decode()

    p = dict(p)
    p["src"] = one(p.get("src"))
    if isinstance(p.get("expressions"), dict):
        p["expressions"] = {k: v for k, v in ((k, one(v)) for k, v in p["expressions"].items()) if v}
    out = {**behavior, "portrait": p if p["src"] else None}
    if out["portrait"] is None:
        out.pop("portrait")
    return out
