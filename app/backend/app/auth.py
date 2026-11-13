"""账号：注册登录、令牌、个人设置。"""
from __future__ import annotations

import copy
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import DEFAULT_USER_SETTINGS, ApiKey, AuthToken, User

router = APIRouter(prefix="/api", tags=["users"])

_ITER = 240_000
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_一-鿿]{2,32}$")


# ---------- 密码与令牌 ----------

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _ITER)
    return f"pbkdf2_sha256${_ITER}${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, digest = stored.split("$")
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
    return hmac.compare_digest(dk.hex(), digest)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_token(db: Session, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    db.execute(delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.expires_at < now))
    db.add(AuthToken(token_hash=_token_hash(token), user_id=user.id,
                     expires_at=now + timedelta(hours=settings.token_ttl_hours)))
    db.commit()
    return token


API_KEY_PREFIX = "km_"
MAX_API_KEYS = 10


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    if token.startswith(API_KEY_PREFIX):  # 开发者 API 密钥：长期有效，删掉才失效
        key = db.scalar(select(ApiKey).where(ApiKey.key_hash == _token_hash(token)))
        if key is None:
            return None
        t = datetime.now(timezone.utc)
        if key.last_used_at is None or t - key.last_used_at > timedelta(minutes=5):  # 不必每个请求都写一次库
            key.last_used_at = t
            db.commit()
        return db.get(User, key.user_id)
    row = db.get(AuthToken, _token_hash(token))
    if row is None or row.expires_at < datetime.now(timezone.utc):
        return None
    return db.get(User, row.user_id)


def bearer(authorization: str | None = Header(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def current_user(token: str | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    user = user_from_token(db, token)
    if user is None:
        raise HTTPException(401, "请先登录")
    return user


def session_user(token: str | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    """只认登录的会话，不认 API 密钥：管理密钥、注销账号这类事，密钥泄露了也做不了。"""
    if token and token.startswith(API_KEY_PREFIX):
        raise HTTPException(403, "API 密钥不能做这件事，请在网页上登录后操作")
    return current_user(token, db)


# ---------- 设置 ----------

def user_settings(user: User) -> dict:
    """默认值 + 用户改过的值（按分组合并，新增的设置项老用户也能拿到默认值）。"""
    out = copy.deepcopy(DEFAULT_USER_SETTINGS)
    for k, v in (user.settings or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


def is_admin(user: User) -> bool:
    return user.username in settings.workshop_admins


def user_out(u: User) -> dict:
    s = user_settings(u)
    if "guard" in s:  # 监护人密码之类的不往外给
        s["guard"] = {k: v for k, v in s["guard"].items() if k not in ("pin", "pin_lock")}
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "settings": s,
            "workshop_admin": is_admin(u), "companion_limit": settings.companion_limit}


class Credentials(BaseModel):
    username: str
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=32)
    birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")  # 出生年月；国际站注册必填且要满 18 岁


class SettingsIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=32)
    save_sensitive: bool | None = None
    privacy: dict | None = None
    voice: dict | None = None
    interaction: dict | None = None
    evaluator: dict | None = None
    social: dict | None = None


_ALLOWED = {  # 每个分组允许的键和取值，防止前端写进任意结构
    "privacy": {"camera": bool, "microphone": bool},
    "voice": {"stt": ("auto", "browser", "server", "off"), "tts": ("auto", "browser", "server", "off"),
              "autoplay": bool, "voice": str},
    "interaction": {"proactive": bool, "idle_seconds": int, "animations": bool, "stories": bool, "web": bool},
    "evaluator": {"mode": (None, "rules", "matrix", "off")},
    "social": {"autonomy": bool, "share_life": bool},
}


def _clean_group(group: str, data: dict) -> dict:
    out = {}
    for k, v in data.items():
        rule = _ALLOWED[group].get(k)
        if rule is None:
            raise HTTPException(400, f"未知设置 {group}.{k}")
        if isinstance(rule, tuple):
            if v not in rule:
                raise HTTPException(400, f"{group}.{k} 只能是 {rule}")
        elif rule is int:
            if isinstance(v, bool) or not isinstance(v, int) or not 10 <= v <= 3600:
                raise HTTPException(400, f"{group}.{k} 必须是 10-3600 的整数")
        elif rule is str:
            if not isinstance(v, str) or len(v) > 40:
                raise HTTPException(400, f"{group}.{k} 必须是 40 字以内的文字")
        elif not isinstance(v, rule):
            raise HTTPException(400, f"{group}.{k} 类型不对")
        out[k] = v
    return out


# ---------- 接口 ----------

@router.post("/auth/register")
def register(body: Credentials, db: Session = Depends(get_db)):
    if settings.registration == "closed":
        raise HTTPException(403, "暂未开放注册")
    if not _USERNAME_RE.match(body.username):
        raise HTTPException(400, "用户名需 2-32 位字母、数字、下划线或中文")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "用户名已存在")
    guard_info = {}
    if settings.edition != "cn":  # 国际站只为成年人提供服务：注册时就确认
        from .guard import ADULT
        if not body.birth:
            raise HTTPException(400, "请选择出生年月")
        y, m = (int(x) for x in body.birth.split("-"))
        today = datetime.now(timezone.utc).date()
        if not (1900 <= y and 1 <= m <= 12 and (y, m) <= (today.year, today.month)):
            raise HTTPException(400, "出生年月不对")
        if today.year - y - (1 if today.month < m else 0) < ADULT:  # 中性的拒绝：不说年龄门槛（FTC COPPA FAQ D.7）
            raise HTTPException(403, "抱歉，无法为你创建账号。")
        guard_info = {"guard": {"birth": body.birth}}
    elif body.birth:
        guard_info = {"guard": {"birth": body.birth}}
    user = User(username=body.username, password_hash=hash_password(body.password),
                display_name=body.display_name or body.username, settings=guard_info)
    db.add(user)
    db.flush()
    from .personas import adopt_officials

    adopt_officials(db, user)  # 每个新用户都有两位官方角色：KRINO（第一位，默认打开）和大肥鱼
    db.commit()
    return {"token": issue_token(db, user), "user": user_out(user)}


@router.post("/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
    from .guard import adult_block
    if adult_block(user) == "minor":  # 国际站：登记的年龄不满 18 岁的账号不能登录（疑似的可以登录去申诉）
        raise HTTPException(403, "抱歉，这个账号不能使用 KRINO WORLD。")
    return {"token": issue_token(db, user), "user": user_out(user)}


@router.post("/auth/logout")
def logout(token: str | None = Depends(bearer), db: Session = Depends(get_db)):
    if token:
        db.execute(delete(AuthToken).where(AuthToken.token_hash == _token_hash(token)))
        db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user)


@router.patch("/me")
def update_me(body: SettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = dict(user.settings or {})
    if body.display_name is not None:
        user.display_name = body.display_name.strip() or user.username
    if body.save_sensitive is not None:
        s["save_sensitive"] = body.save_sensitive
    for group in _ALLOWED:
        data = getattr(body, group)
        if data is not None:
            s[group] = {**(s.get(group) or {}), **_clean_group(group, data)}
    user.settings = s
    db.commit()
    return user_out(user)


class DeleteIn(BaseModel):
    password: str


@router.delete("/me")
def delete_account(body: DeleteIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    """注销账号：角色、记忆、聊天、关系、上传的模型、发布的作品全部删除，不能恢复。"""
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "密码不对")
    db.delete(user)
    db.commit()
    return {"ok": True}


# ---------- 开发者 API 密钥（设置 → 开发者） ----------

class ApiKeyIn(BaseModel):
    name: str = Field(default="", max_length=40)


def _key_out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "created_at": k.created_at.isoformat(),
            "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None}


@router.get("/keys")
def list_keys(user: User = Depends(session_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(ApiKey).where(ApiKey.user_id == user.id).order_by(ApiKey.created_at.desc())).all()
    return [_key_out(k) for k in rows]


@router.post("/keys")
def create_key(body: ApiKeyIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    """新建一把密钥。原文只在这次返回里出现，服务器只存哈希，丢了就删掉重建。"""
    n = len(db.scalars(select(ApiKey.id).where(ApiKey.user_id == user.id)).all())
    if n >= MAX_API_KEYS:
        raise HTTPException(400, f"最多 {MAX_API_KEYS} 把密钥，先删掉不用的")
    raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
    k = ApiKey(user_id=user.id, name=body.name.strip() or "API key", key_hash=_token_hash(raw), prefix=raw[:10])
    db.add(k)
    db.commit()
    return {**_key_out(k), "key": raw}


@router.delete("/keys/{key_id}")
def delete_key(key_id: str, user: User = Depends(session_user), db: Session = Depends(get_db)):
    k = db.get(ApiKey, key_id)
    if k is None or k.user_id != user.id:
        raise HTTPException(404, "没有这把密钥")
    db.delete(k)
    db.commit()
    return {"ok": True}
