from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Decision, Feedback, User, now
from ..security import current_user

router = APIRouter(prefix="/api/decisions", tags=["decisions"])


class FeedbackIn(BaseModel):
    """Only the fields sent are changed, so feedback can be filled in over several visits."""
    chosen_action: str | None = None
    reason: str | None = None
    status: Literal["chosen", "later", "unsuitable", "done"] | None = None
    executed: Literal["yes", "no"] | None = None
    helpful: Literal["yes", "partly", "no"] | None = None
    outcome: str | None = None


def feedback_view(f: Feedback | None) -> dict | None:
    if f is None:
        return None
    return {"chosen_action": f.chosen_action, "chose_recommended": f.chose_recommended, "reason": f.reason,
            "status": f.status, "executed": f.executed, "helpful": f.helpful, "outcome": f.outcome,
            "created_at": f.created_at, "updated_at": f.updated_at}


def decision_view(d: Decision) -> dict:
    return {"id": d.id, "conversation_id": d.conversation_id, "created_at": d.created_at,
            "objective_input": d.objective_input, "answers": d.answers, "model_version": d.model_version,
            "response": d.response, "feedback": feedback_view(d.feedback)}


def owned_decision(db: Session, user: User, decision_id: str) -> Decision:
    decision = db.get(Decision, decision_id)
    if decision is None or decision.user_id != user.id:
        raise HTTPException(404, "not_found")
    return decision


@router.get("")
def recent_decisions(limit: int = 10, user: User = Depends(current_user), db: Session = Depends(get_db)):
    decisions = db.scalars(select(Decision).where(Decision.user_id == user.id)
                           .order_by(Decision.created_at.desc()).limit(min(limit, 100)))
    return [decision_view(d) for d in decisions]


@router.get("/{decision_id}")
def get_decision(decision_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return decision_view(owned_decision(db, user, decision_id))


@router.put("/{decision_id}/feedback")
def put_feedback(decision_id: str, body: FeedbackIn, user: User = Depends(current_user),
                 db: Session = Depends(get_db)):
    decision = owned_decision(db, user, decision_id)
    sent = body.model_dump(exclude_unset=True)
    if sent.get("chosen_action") and sent["chosen_action"] not in {c["id"] for c in decision.candidates}:
        raise HTTPException(422, "unknown_action")
    feedback = decision.feedback or Feedback(decision_id=decision.id, user_id=user.id)
    for key, value in sent.items():
        setattr(feedback, key, value if value is not None or key not in ("reason", "outcome") else "")
    if "chosen_action" in sent:
        feedback.chose_recommended = (feedback.chosen_action == decision.recommended) if feedback.chosen_action else None
    feedback.updated_at = now()
    decision.feedback = feedback
    db.commit()
    return decision_view(decision)
