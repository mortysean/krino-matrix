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
from .models import DEFAULT_USER_SETTINGS, AuthToken, User

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


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
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
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "settings": user_settings(u),
            "workshop_admin": is_admin(u), "companion_limit": settings.companion_limit}


class Credentials(BaseModel):
    username: str
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=32)


class SettingsIn(BaseModel):
    display_name: str | None = Field(default=None, max_length=32)
    save_sensitive: bool | None = None
    privacy: dict | None = None
    voice: dict | None = None
    interaction: dict | None = None
    evaluator: dict | None = None


_ALLOWED = {  # 每个分组允许的键和取值，防止前端写进任意结构
    "privacy": {"camera": bool, "microphone": bool},
    "voice": {"stt": ("auto", "browser", "server", "off"), "tts": ("auto", "browser", "server", "off"),
              "autoplay": bool, "voice": str},
    "interaction": {"proactive": bool, "idle_seconds": int, "animations": bool, "stories": bool},
    "evaluator": {"mode": (None, "rules", "matrix", "off")},
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
    if not _USERNAME_RE.match(body.username):
        raise HTTPException(400, "用户名需 2-32 位字母、数字、下划线或中文")
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(409, "用户名已存在")
    user = User(username=body.username, password_hash=hash_password(body.password),
                display_name=body.display_name or body.username, settings={})
    db.add(user)
    db.flush()
    from .personas import adopt_official

    adopt_official(db, user)  # 每个新用户都有一位默认官方角色 WHALE GIRL
    db.commit()
    return {"token": issue_token(db, user), "user": user_out(user)}


@router.post("/auth/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码错误")
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
