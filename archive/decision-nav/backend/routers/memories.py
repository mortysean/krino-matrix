from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Memory, User, now
from ..security import current_user

router = APIRouter(prefix="/api/memories", tags=["memories"])

MAX_MEMORIES = 100


class MemoryIn(BaseModel):
    text: str
    source_decision_id: str | None = None


def memory_view(m: Memory) -> dict:
    return {"id": m.id, "text": m.text, "source_decision_id": m.source_decision_id,
            "created_at": m.created_at, "updated_at": m.updated_at}


def owned_memory(db: Session, user: User, memory_id: str) -> Memory:
    memory = db.get(Memory, memory_id)
    if memory is None or memory.user_id != user.id:
        raise HTTPException(404, "not_found")
    return memory


def clean(text: str) -> str:
    text = text.strip()
    if not text:
        raise HTTPException(422, "empty_memory")
    return text[:500]


@router.get("")
def list_memories(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [memory_view(m) for m in db.scalars(select(Memory).where(Memory.user_id == user.id)
                                               .order_by(Memory.created_at.desc()))]


@router.post("")
def add_memory(body: MemoryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if len(db.scalars(select(Memory.id).where(Memory.user_id == user.id)).all()) >= MAX_MEMORIES:
        raise HTTPException(409, "too_many_memories")
    memory = Memory(user_id=user.id, text=clean(body.text), source_decision_id=body.source_decision_id)
    db.add(memory)
    db.commit()
    return memory_view(memory)


@router.patch("/{memory_id}")
def edit_memory(memory_id: str, body: MemoryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    memory = owned_memory(db, user, memory_id)
    memory.text = clean(body.text)
    memory.updated_at = now()
    db.commit()
    return memory_view(memory)


@router.delete("/{memory_id}")
def delete_memory(memory_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_memory(db, user, memory_id))
    db.commit()
    return {"ok": True}
