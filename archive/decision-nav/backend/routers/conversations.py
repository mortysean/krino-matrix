import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from krino.contract import Answer, ErrorResponse
from krino.evaluator.rules import lang_of
from ..config import settings
from ..db import get_db
from ..models import Conversation, Decision, Message, Turn, User, now
from ..security import current_user
from ..turns import QUOTA_MESSAGE, core_input, pending_question, run_turn, segment, turns_today
from .decisions import decision_view

router = APIRouter(prefix="/api", tags=["conversations"])

NDJSON = "application/x-ndjson"


class AnswerIn(BaseModel):
    question_id: str
    values: list[str] = []
    text: str = ""
    skipped: bool = False


class TurnIn(BaseModel):
    conversation_id: str | None = None
    text: str | None = None         # a new goal, or a free-text answer to the pending question
    answer: AnswerIn | None = None
    retry: bool = False             # run the decision in progress again, adding nothing
    decide_now: bool = False        # skip the remaining questions and decide


class TitleIn(BaseModel):
    title: str


def owned_conversation(db: Session, user: User, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(404, "not_found")
    return conversation


def conversation_view(c: Conversation, preview: str = "") -> dict:
    return {"id": c.id, "title": c.title, "created_at": c.created_at, "updated_at": c.updated_at, "preview": preview}


def single(event: dict) -> StreamingResponse:
    return StreamingResponse(iter([json.dumps(event, ensure_ascii=False) + "\n"]), media_type=NDJSON)


@router.post("/turns")
def turn(body: TurnIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """One turn, streamed as NDJSON: {"type": "conversation"}, then "stage" events, then exactly one
    clarification / decision / error."""
    text = (body.text or "").strip()
    lang = lang_of(text) if text else "zh"
    if turns_today(db, user.id) >= settings.daily_quota:
        return single(ErrorResponse(code="quota_exceeded", message=QUOTA_MESSAGE[lang], retryable=False,
                                    suggestions=["later"]).model_dump(mode="json"))

    if body.conversation_id:
        conversation = owned_conversation(db, user, body.conversation_id)
    else:
        if not text:
            raise HTTPException(422, "empty_input")
        conversation = Conversation(user_id=user.id, title=text[:60])
        db.add(conversation)
        db.flush()

    question = pending_question(segment(list(conversation.messages)))
    answer = None
    if body.answer:
        if question is None or body.answer.question_id != question["id"]:
            raise HTTPException(409, "no_such_question")
        answer = Answer(question=question["text"], **body.answer.model_dump())
    elif text and question is not None and not body.decide_now:
        answer = Answer(question_id=question["id"], question=question["text"], text=text)
    elif body.decide_now and question is not None:
        answer = Answer(question_id=question["id"], question=question["text"], skipped=True)

    if answer:
        db.add(Message(conversation_id=conversation.id, user_id=user.id, role="user", kind="answer",
                       text=answer.as_text(), payload={"answer": answer.model_dump()}))
    elif text:
        db.add(Message(conversation_id=conversation.id, user_id=user.id, role="user", kind="objective", text=text))
    elif not body.retry and not body.decide_now:
        raise HTTPException(422, "empty_input")
    db.flush()
    db.refresh(conversation)

    data = core_input(db, conversation, body.decide_now)
    if data is None:
        raise HTTPException(409, "no_objective")
    t = Turn(user_id=user.id)
    db.add(t)
    conversation.updated_at = now()
    db.commit()

    factory = request.app.state.engine_factory
    head = json.dumps({"type": "conversation", "id": conversation.id, "title": conversation.title},
                      ensure_ascii=False) + "\n"

    def stream():
        yield head
        yield from run_turn(factory, user.id, conversation.id, t.id, data)
    return StreamingResponse(stream(), media_type=NDJSON)


@router.get("/conversations")
def list_conversations(q: str = "", limit: int = 50, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    query = select(Conversation).where(Conversation.user_id == user.id)
    if q.strip():
        like = f"%{q.strip()}%"
        matching = select(Message.conversation_id).where(Message.user_id == user.id, Message.text.ilike(like))
        query = query.where(or_(Conversation.title.ilike(like), Conversation.id.in_(matching)))
    conversations = db.scalars(query.order_by(Conversation.updated_at.desc()).limit(min(limit, 200))).all()
    previews = {}
    for c in conversations:
        last = next((m for m in reversed(c.messages) if m.text), None)
        previews[c.id] = last.text[:120] if last else ""
    return [conversation_view(c, previews[c.id]) for c in conversations]


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    conversation = owned_conversation(db, user, conversation_id)
    ids = [m.payload["decision_id"] for m in conversation.messages if m.kind == "decision"]
    decisions = {d.id: decision_view(d) for d in db.scalars(
        select(Decision).where(Decision.id.in_(ids), Decision.user_id == user.id))}
    messages = []
    for m in conversation.messages:
        item = {"id": m.id, "role": m.role, "kind": m.kind, "text": m.text, "created_at": m.created_at}
        if m.kind == "decision":
            item["decision"] = decisions.get(m.payload["decision_id"])
        elif m.kind in ("clarification", "error"):
            item["response"] = m.payload.get("response")
        elif m.kind == "answer":
            item["answer"] = m.payload.get("answer")
        messages.append(item)
    return {**conversation_view(conversation), "messages": messages,
            "pending_question": pending_question(segment(list(conversation.messages)))}


@router.patch("/conversations/{conversation_id}")
def rename_conversation(conversation_id: str, body: TitleIn, user: User = Depends(current_user),
                        db: Session = Depends(get_db)):
    conversation = owned_conversation(db, user, conversation_id)
    conversation.title = body.title.strip()[:200] or conversation.title
    db.commit()
    return conversation_view(conversation)


@router.delete("/conversations/{conversation_id}")
def delete_conversation(conversation_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(owned_conversation(db, user, conversation_id))
    db.commit()
    return {"ok": True}
