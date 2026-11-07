"""积分：把每个人花掉的钱（对话的 token、生成的图片、云端语音）折算成积分，按天限额。

1 元 = CREDITS_PER_CNY 积分（默认 10）。每次花钱记一条 world_events（kind = "credit"，payload.points），
当天花了多少就是把这些加起来。限额：CREDIT_USER_LIMITS 里单独设了的账号按它来（比如测试账号），
其余按 CREDIT_DAILY_LIMIT（0 = 不限）。花的钱按单价估算，单价都在 .env 里可以改：
- 对话：OpenRouter 返回的实际花费（美元，按 USD_CNY 换成人民币）；没有返回时按 LLM_PRICE_IN / LLM_PRICE_OUT（元 / 百万 token）
- 图片：IMAGE_PRICE_CNY 元 / 张
- 语音：TTS_PRICE_CNY 元 / 万字（本地 Kokoro、浏览器朗读不花钱）
超了限额：已经在进行的这一次照常完成，下一次请求直接拒绝。
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import events
from .auth import current_user
from .config import settings
from .db import get_db
from .models import User, WorldEvent

log = logging.getLogger("krino.credits")
router = APIRouter(prefix="/api/credits", tags=["credits"])


def points(cny: float) -> float:
    return round(cny * settings.credits_per_cny, 4)


def daily_limit(user: User) -> float:
    """每天能花多少积分；0 = 不限。"""
    return float(settings.credit_user_limits.get(user.username, settings.credit_daily_limit))


def spent_today(db: Session, user_id: str) -> float:
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    total = db.scalar(select(func.sum(WorldEvent.payload["points"].as_float())).where(
        WorldEvent.user_id == user_id, WorldEvent.kind == "credit", WorldEvent.created_at >= start))
    return round(float(total or 0), 2)


def check(db: Session, user: User, need: float = 0) -> None:
    """要花钱之前问一句：今天的积分还够不够（need = 这次大概要花的积分，算不出来就是 0）。"""
    limit = daily_limit(user)
    spent = spent_today(db, user.id) if limit else 0
    if limit and (spent >= limit or spent + need > limit):
        raise HTTPException(429, f"今天的积分用完了（每天 {limit:g} 积分），明天再来")


def charge(user_id: str | None, what: str, cny: float, **detail) -> None:
    """记一笔花费。没有用户（后台任务找不到人）或不花钱的就不记。"""
    if not user_id or cny <= 0:
        return
    events.record("credit", what, user_id=user_id, payload={"points": points(cny), "cny": round(cny, 6), **detail})


def llm_cost_cny(usage: dict) -> float:
    """OpenRouter 返回的 usage：有 cost（美元）就用它，没有就按 token 数和配置的单价估。"""
    if usage.get("cost") is not None:
        return float(usage["cost"]) * settings.usd_cny
    tin, tout = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
    return (tin * settings.llm_price_in + tout * settings.llm_price_out) / 1_000_000


def charge_llm(user_id: str | None, usage: dict | None, model: str = "") -> None:
    if usage:
        charge(user_id, "llm", llm_cost_cny(usage), model=model,
               tokens=(usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0))


def image_points(n: int) -> float:
    return points(n * settings.image_price_cny)


def charge_images(user_id: str, n: int) -> None:
    charge(user_id, "image", n * settings.image_price_cny, n=n)


def tts_cny(chars: int) -> float:
    return chars / 10_000 * settings.tts_price_cny if settings.tts_provider not in ("local", "browser", "mock", "qwen") else 0.0


@router.get("")
def info(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"limit": daily_limit(user), "spent": spent_today(db, user.id), "per_cny": settings.credits_per_cny,
            "image": image_points(1)}
