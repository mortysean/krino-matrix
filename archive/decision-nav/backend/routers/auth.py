import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import log, settings
from ..db import get_db
from ..models import PasswordReset, User
from ..security import (COOKIE, current_user, hash_password, hash_reset_token, limiter, make_token,
                        new_reset_token, verify_password)

router = APIRouter(prefix="/api/auth", tags=["auth"])

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD = 8


class Credentials(BaseModel):
    email: str
    password: str


class ResetRequest(BaseModel):
    email: str


class ResetConfirm(BaseModel):
    token: str
    password: str


def user_view(user: User) -> dict:
    return {"id": user.id, "email": user.email, "created_at": user.created_at}


def normalize(email: str) -> str:
    email = email.strip().lower()
    if not EMAIL_RE.match(email):
        raise HTTPException(422, "invalid_email")
    return email


def check_password(password: str):
    if len(password) < MIN_PASSWORD:
        raise HTTPException(422, "weak_password")


def set_session(response: Response, user: User):
    response.set_cookie(COOKIE, make_token(user.id), max_age=settings.session_days * 86400, httponly=True,
                        samesite="lax", secure=settings.cookie_secure, path="/")


@router.post("/register")
def register(body: Credentials, response: Response, db: Session = Depends(get_db)):
    email = normalize(body.email)
    check_password(body.password)
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "email_taken")
    user = User(email=email, password_hash=hash_password(body.password))
    db.add(user)
    db.commit()
    set_session(response, user)
    return user_view(user)


@router.post("/login")
def login(body: Credentials, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    keys = (f"email:{email}", f"ip:{request.client.host if request.client else '?'}")
    if limiter.blocked(*keys):
        raise HTTPException(429, "too_many_attempts")
    user = db.scalar(select(User).where(User.email == email))
    if user is None or not verify_password(body.password, user.password_hash):
        limiter.fail(*keys)
        raise HTTPException(401, "invalid_credentials")
    limiter.clear(keys[0])
    set_session(response, user)
    return user_view(user)


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_view(user)


@router.post("/reset/request")
def reset_request(body: ResetRequest, request: Request, db: Session = Depends(get_db)):
    """Always answers the same, so it never reveals whether an email is registered."""
    email = body.email.strip().lower()
    if limiter.blocked(f"reset:{email}"):
        raise HTTPException(429, "too_many_attempts")
    limiter.fail(f"reset:{email}")
    user = db.scalar(select(User).where(User.email == email))
    if user:
        token, token_hash = new_reset_token()
        db.add(PasswordReset(user_id=user.id, token_hash=token_hash,
                             expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
        db.commit()
        # No mail service yet: the link goes to the server log for the operator to deliver
        log.warning("Password reset link for %s: %s/reset?token=%s", email, str(request.base_url).rstrip("/"), token)
    return {"ok": True}


@router.post("/reset/confirm")
def reset_confirm(body: ResetConfirm, response: Response, db: Session = Depends(get_db)):
    check_password(body.password)
    reset = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_reset_token(body.token)))
    expires = reset.expires_at.replace(tzinfo=reset.expires_at.tzinfo or timezone.utc) if reset else None
    if reset is None or reset.used or expires < datetime.now(timezone.utc):
        raise HTTPException(400, "invalid_token")
    user = db.get(User, reset.user_id)
    user.password_hash = hash_password(body.password)
    reset.used = True
    db.commit()
    set_session(response, user)
    return user_view(user)
