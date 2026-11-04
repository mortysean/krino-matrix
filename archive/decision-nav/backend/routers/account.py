import os

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from krino.common.tracing import model_configured
from krino.style import Style
from ..config import settings
from ..db import get_db
from ..models import Conversation, ModelCall, User, UserSettings, now
from ..security import COOKIE, current_user, hash_password, verify_password
from ..turns import turns_today, user_style
from .auth import check_password

router = APIRouter(prefix="/api/account", tags=["account"])


class PasswordChange(BaseModel):
    current: str
    new: str


class Confirm(BaseModel):
    password: str


@router.post("/password")
def change_password(body: PasswordChange, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not verify_password(body.current, user.password_hash):
        raise HTTPException(403, "invalid_credentials")
    check_password(body.new)
    user.password_hash = hash_password(body.new)
    db.commit()
    return {"ok": True}


@router.get("/style")
def get_style(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """How Krino talks to this user: reply style (tone), personality (persona), conversation style (pace)."""
    return user_style(db, user.id)


@router.put("/style")
def set_style(body: Style, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.get(UserSettings, user.id) or UserSettings(user_id=user.id)
    row.style = body.model_dump()
    row.updated_at = now()
    db.add(row)
    db.commit()
    return body


@router.delete("/history")
def delete_history(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Every conversation and with it every decision and feedback; memories are kept, they are managed apart."""
    db.execute(delete(Conversation).where(Conversation.user_id == user.id))
    db.commit()
    return {"ok": True}


@router.delete("")
def delete_account(body: Confirm, response: Response, user: User = Depends(current_user),
                   db: Session = Depends(get_db)):
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(403, "invalid_credentials")
    db.delete(user)
    db.commit()
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Model, evaluator and usage, for the settings page. Balance and top-up are not live yet."""
    calls = db.execute(select(func.count(), func.sum(ModelCall.duration_ms), func.sum(ModelCall.input_tokens),
                              func.sum(ModelCall.output_tokens))
                       .where(ModelCall.user_id == user.id)).one()
    failed = db.scalar(select(func.count()).select_from(ModelCall)
                       .where(ModelCall.user_id == user.id, ModelCall.ok.is_(False)))
    return {
        "model": {"configured": model_configured(), "name": os.getenv("LLM_DEFAULT") or None},
        "evaluator": {"experimental": True},
        "usage": {"turns_today": turns_today(db, user.id), "daily_quota": settings.daily_quota,
                  "calls": calls[0], "failed_calls": failed,
                  "avg_latency_ms": int(calls[1] / calls[0]) if calls[0] else None,
                  "input_tokens": calls[2] or 0, "output_tokens": calls[3] or 0},
        "billing": {"live": False},
    }
