"""运行状态：结构化事件写进 world_events，请求延迟和错误留一份内存统计，给 /api/status 和设置页用。"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .auth import current_user
from .config import service_status, settings
from .db import SessionLocal, get_db
from .models import User, WorldEvent

log = logging.getLogger("krino.events")
router = APIRouter(prefix="/api", tags=["status"])

STARTED = time.time()
_lock = threading.Lock()
_latency: dict[str, deque] = defaultdict(lambda: deque(maxlen=200))
_errors: deque = deque(maxlen=50)


def record(kind: str, name: str, *, user_id: str | None = None, character_id: str | None = None,
           payload: dict | None = None, latency_ms: float | None = None, db: Session | None = None) -> None:
    """写一条运行事件。用独立的会话写，失败只记日志：事件记录不能影响业务。"""
    row = WorldEvent(kind=kind, name=name[:48], user_id=user_id, character_id=character_id, payload=payload,
                     latency_ms=round(latency_ms, 1) if latency_ms is not None else None)
    own = db is None
    s = SessionLocal() if own else db
    try:
        s.add(row)
        if own:
            s.commit()
    except Exception:  # noqa: BLE001
        log.exception("写运行事件失败 %s/%s", kind, name)
        if own:
            s.rollback()
    finally:
        if own:
            s.close()


def observe(route: str, ms: float, status: int) -> None:
    with _lock:
        _latency[route].append(ms)
    if status >= 500:
        error(route, f"HTTP {status}")


def error(where: str, message: str) -> None:
    with _lock:
        _errors.append({"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "where": where,
                        "message": message[:300]})


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(len(xs) * p))], 1)


def latency_summary() -> list[dict]:
    with _lock:
        items = {k: list(v) for k, v in _latency.items()}
    rows = [{"route": k, "count": len(v), "p50_ms": _pct(v, .5), "p95_ms": _pct(v, .95)} for k, v in items.items()]
    return sorted(rows, key=lambda r: -r["count"])[:20]


@router.get("/health")
def health():
    return {"ok": True, "mock": settings.llm_provider == "mock", "policy": settings.policy_mode}


@router.get("/services")
def services(user: User = Depends(current_user)):
    """模型服务配置状态（不含密钥）+ 互动策略状态。"""
    from .policy import policy_status

    return {**service_status(), "policy": policy_status(user)}


@router.get("/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    counts = dict(db.execute(select(WorldEvent.kind, func.count()).where(WorldEvent.created_at > since)
                             .group_by(WorldEvent.kind)).all())
    with _lock:
        errors = list(_errors)[-10:]
    from .devices import hub

    return {"uptime_s": round(time.time() - STARTED), "latency": latency_summary(), "errors": errors,
            "events_24h": counts, "device": hub.status(user.id)}


@router.get("/events")
def recent_events(kind: str | None = None, limit: int = 50, user: User = Depends(current_user),
                  db: Session = Depends(get_db)):
    q = select(WorldEvent).where(WorldEvent.user_id == user.id)
    if kind:
        q = q.where(WorldEvent.kind == kind)
    rows = db.scalars(q.order_by(WorldEvent.id.desc()).limit(min(200, max(1, limit)))).all()
    return [{"id": r.id, "kind": r.kind, "name": r.name, "payload": r.payload, "latency_ms": r.latency_ms,
             "at": r.created_at.isoformat()} for r in rows]
