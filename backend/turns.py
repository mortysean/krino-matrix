"""Runs one turn of the Decision Core for a conversation and records everything it produced."""
import json
import queue
import threading
from collections.abc import Callable, Iterator
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from decision_core import Answer, CoreInput, CoreResponse, DecisionEngine, ErrorResponse
from decision_core.engine import ERRORS
from decision_core.rules import lang_of
from model_adapter import CallLog, current_log
from .config import log, settings
from .db import SessionLocal
from .models import Conversation, Decision, Memory, Message, ModelCall, Turn, now

QUOTA_MESSAGE = {
    "zh": "今天的可用次数已用完，明天会自动恢复。已保存的历史和决策不受影响。",
    "en": "You have used today's runs. They reset tomorrow; saved history and decisions are unaffected.",
}


def turns_today(db: Session, user_id: str) -> int:
    start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.scalar(select(func.count()).select_from(Turn).where(Turn.user_id == user_id, Turn.created_at >= start))


def segment(messages: list[Message]) -> list[Message]:
    """The messages of the decision in progress: everything after the last decision."""
    last = max((i for i, m in enumerate(messages) if m.kind == "decision"), default=-1)
    return messages[last + 1:]


def pending_question(messages: list[Message]) -> dict | None:
    """The clarification question awaiting an answer, if the conversation ends on one."""
    if messages and messages[-1].kind == "clarification":
        return messages[-1].payload["response"]["question"]
    return None


def core_input(db: Session, conversation: Conversation, decide_now: bool) -> CoreInput | None:
    messages = list(conversation.messages)
    current = segment(messages)
    starts = [i for i, m in enumerate(current) if m.kind == "objective"]
    if not starts:
        return None
    current = current[starts[-1]:]
    answers = [Answer.model_validate(m.payload["answer"]) for m in current if m.kind == "answer"]

    history = []
    decision_ids = [m.payload["decision_id"] for m in messages if m.kind == "decision"]
    for d in db.scalars(select(Decision).where(Decision.id.in_(decision_ids)).order_by(Decision.created_at)):
        titles = {c["id"]: c["title"] for c in d.candidates}
        chosen = titles.get(d.feedback.chosen_action) if d.feedback and d.feedback.chosen_action else None
        history.append(f"Goal: {d.problem['objective']}; recommended: {titles.get(d.recommended, 'none')}; "
                       f"user chose: {chosen or 'not recorded'}")
    memories = list(db.scalars(select(Memory.text).where(Memory.user_id == conversation.user_id)
                               .order_by(Memory.created_at)))
    return CoreInput(objective=current[0].text, answers=answers, memories=memories, history=history[-5:],
                     max_questions=len(answers) if decide_now else settings.max_questions)


def save_result(
    db: Session,
    conversation: Conversation,
    data: CoreInput,
    response: CoreResponse
) -> dict:
    """Store the response as the assistant's message; a decision also as a full snapshot."""
    payload: dict = {"response": response.model_dump(mode="json")}
    text = ""
    if response.type == "decision":
        decision = Decision(
            user_id=conversation.user_id, conversation_id=conversation.id, objective_input=data.objective,
            answers=[a.model_dump() for a in data.answers], problem=response.problem.model_dump(mode="json"),
            candidates=[a.model_dump() for a in response.actions], recommended=response.best_action,
            scores=response.action_scores, confidence=response.confidence, evaluator_mode=response.evaluator.mode,
            model_version=response.model_version, response=payload["response"],
        )
        db.add(decision)
        db.flush()
        payload = {"decision_id": decision.id}
        text = response.headline
    elif response.type == "clarification":
        text = response.question.text
    message = Message(conversation_id=conversation.id, user_id=conversation.user_id, role="assistant",
                      kind=response.type, text=text, payload=payload)
    db.add(message)
    conversation.updated_at = now()
    db.flush()
    return {"message_id": message.id, **({"decision_id": payload["decision_id"]} if "decision_id" in payload else {})}


def run_turn(
    engine_factory: Callable[[], DecisionEngine],
    user_id: str,
    conversation_id: str,
    turn_id: str,
    data: CoreInput
) -> Iterator[str]:
    """Stream NDJSON events: stage events while the core works, then the final response.

    The core runs in its own thread and saves its result even if the client disconnects mid-way.
    """
    events: queue.Queue[dict | None] = queue.Queue()

    def work():
        calls = CallLog()
        current_log.set(calls)

        def on_stage(stage):
            calls.stage = stage
            events.put({"type": "stage", "stage": stage})

        try:
            engine = engine_factory()
        except Exception:
            log.exception("could not build the decision engine")
            response: CoreResponse = ErrorResponse(code="model_unavailable", suggestions=["retry", "later"],
                                                   message=ERRORS[lang_of(data.objective)]["model_unavailable"])
        else:
            response = engine.run(data, on_stage)
        try:
            with SessionLocal() as db:
                conversation = db.get(Conversation, conversation_id)
                ids = save_result(db, conversation, data, response)
                for c in calls.calls:
                    db.add(ModelCall(user_id=user_id, conversation_id=conversation_id, turn_id=turn_id, **c.model_dump()))
                turn = db.get(Turn, turn_id)
                turn.result = response.type if response.type != "error" else response.code
                db.commit()
            events.put({**response.model_dump(mode="json"), **ids})
        except Exception:
            log.exception("could not save turn %s", turn_id)
            events.put(ErrorResponse(code="call_failed",
                                     message=ERRORS[lang_of(data.objective)]["call_failed"]).model_dump(mode="json"))
        finally:
            events.put(None)

    threading.Thread(target=work, daemon=True).start()
    while (event := events.get()) is not None:
        yield json.dumps(event, ensure_ascii=False) + "\n"
