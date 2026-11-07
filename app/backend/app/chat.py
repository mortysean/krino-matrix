"""会话与一轮互动的主流程（唯一的一条流程）：

    事件（说话 / 互动动作 / 安静 / 画面）
      → 人格 + 记忆 + 关系上下文
      → KRINO Evaluator 互动策略选行为（policy.py）
      → 执行：需要说话时调用模型（可流式），画面先交给 VLM；表情和动作来自策略
      → 结构化行为事件（say / emote / animate / story / remember_suggest / perceive_request）
         给 3D 形象、语音、以及连接着的眼镜模拟器（devices.py 转成 AR 事件）
      → 后台整理记忆（memory.py），不阻塞回复

接口：POST /messages 一次性返回；POST /stream 以 SSE 流式返回（decision → delta… → done）。
"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import credits, events, memory, policy
from .auth import current_user, user_settings
from .config import chat_model_for, locale, settings
from .db import SessionLocal, get_db
from .i18n import tr
from .llm import LLMError, get_llm
from .models import Character, ChatSession, MemoryJob, Message, User, now
from .personas import ANIMATIONS, EXPRESSIONS, get_owned, lore_hits
from .prompt import StreamFilter, build_system, parse_reply
from .text import compact

log = logging.getLogger("krino.chat")
router = APIRouter(prefix="/api/sessions", tags=["chat"])

HISTORY = 20
# 写进聊天记录、或者替用户“说”给模型的几句固定文字
EVENT_TEXT = {'zh': {'gesture': '（你{g}）', 'shared': '（你分享了眼前的画面）', 'quiet': '（对方安静地待在你身边）', 'refused': '（她安静了一会儿）……我们换个话题好吗？'}, 'en': {'gesture': '(You {g})', 'shared': "(You shared what's in front of you)", 'quiet': "(They're quietly hanging out with you)", 'refused': '(she goes quiet for a moment) ...Can we talk about something else?'}}


def event_text(key: str, **kw) -> str:
    return EVENT_TEXT[locale()][key].format(**kw)


PERCEIVE_ASK = {"zh": "能让我看看吗？打开摄像头或者发一张图给我，我才看得到。",
                "en": "Can I see it? Send me a picture or turn on the camera and I'll take a look."}


@dataclass
class Plan:
    """一轮互动的计划：策略选了什么、要不要调模型、调的话用什么提示词。只存 ID，可以跨数据库会话使用。"""
    user_id: str
    session_id: str
    character_id: str
    user_message_id: int | None
    decision: policy.Decision
    mode: str | None = None          # respond | story | proactive | react | perceive；None = 不调模型
    system: str = ""
    history: list[dict] = field(default_factory=list)
    llm_context: dict = field(default_factory=dict)
    recall: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    perception: str | None = None
    fixed_text: str | None = None    # 不调模型时的固定台词（请求画面）
    event_type: str = "message"


def decode_image(data_url: str | None) -> tuple[bytes, str] | None:
    if not data_url:
        return None
    m = re.fullmatch(r"data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=\s]+)", data_url.strip())
    if not m:
        raise HTTPException(400, "图片只支持 PNG / JPEG / WebP 的 data URL")
    raw = base64.b64decode(m.group(2))
    if len(raw) > settings.max_image_bytes:
        raise HTTPException(413, "图片太大了")
    return raw, m.group(1)


def _history(db: Session, session_id: str) -> list[dict]:
    rows = db.scalars(select(Message).where(Message.session_id == session_id)
                      .order_by(Message.id.desc()).limit(HISTORY)).all()
    out: list[dict] = []
    for m in reversed(rows):
        role = "assistant" if m.role == "assistant" else "user"
        if out and out[-1]["role"] == role:  # API 要求 user / assistant 交替
            out[-1]["content"] += "\n" + m.content
        else:
            out.append({"role": role, "content": m.content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _since_proactive(db: Session, session_id: str) -> float | None:
    for m in db.scalars(select(Message).where(Message.session_id == session_id, Message.role == "assistant")
                        .order_by(Message.id.desc()).limit(30)):
        if (m.meta or {}).get("event") == "idle":
            return (now() - m.created_at).total_seconds()
    return None


def plan_turn(db: Session, user: User, sess: ChatSession, *, event: str, text: str = "", gesture: str | None = None,
              image: tuple[bytes, str] | None = None, idle_count: int = 0, source: str = "app") -> Plan:
    char = db.get(Character, sess.character_id)
    us = user_settings(user)
    if event == "gesture" and gesture not in policy.GESTURES:
        raise HTTPException(400, f"不支持的互动动作：{gesture}")
    ev = policy.InteractionEvent(type=event, text=text, gesture=gesture, has_image=image is not None,
                                 source=source, idle_count=idle_count)
    decision = policy.decide(ev, policy.PolicyContext(behavior=char.behavior, user_settings=us,
                                                      seconds_since_proactive=_since_proactive(db, sess.id)))
    events.record("policy", f"{event}:{decision.primary.action}", user_id=user.id, character_id=char.id,
                  payload={"actions": decision.actions(), "policy": decision.policy, "note": decision.note},
                  latency_ms=decision.latency_ms)

    user_msg = None
    if event == "message":
        user_msg = Message(session_id=sess.id, role="user", content=text,
                           meta={"story": decision.primary.action == "STORY", "image": image is not None, "source": source})
    elif event == "gesture":
        user_msg = Message(session_id=sess.id, role="event", content=event_text("gesture", g=policy.gesture_text(gesture)),
                           meta={"gesture": gesture})
    elif event == "perception":
        user_msg = Message(session_id=sess.id, role="event", content=text or event_text("shared"),
                           meta={"perception": True, "source": source})
    if user_msg is not None:
        db.add(user_msg)
        db.flush()
        if not sess.title and event == "message":
            sess.title = text[:30]
    p = Plan(user_id=user.id, session_id=sess.id, character_id=char.id,
             user_message_id=user_msg.id if user_msg else None, decision=decision, event_type=event)

    primary = decision.primary.action
    if primary == "NO_ACTION":
        return p
    if primary == "PERCEIVE" and image is None:
        p.fixed_text = PERCEIVE_ASK[locale()]
        return p
    if primary == "PERCEIVE":
        from .voice import describe_image

        t0 = time.perf_counter()
        p.perception = describe_image(image[0], image[1], question=text)
        events.record("vision", "describe", user_id=user.id, character_id=char.id,
                      latency_ms=(time.perf_counter() - t0) * 1000)
    p.mode = {"RESPOND": {"message": "respond", "idle": "proactive", "gesture": "react", "perception": "respond"}[event],
              "STORY": "story", "PERCEIVE": "perceive"}[primary]

    query = text
    if len(text) <= 5 and event == "message":  # 很短的追问带上用户上一句
        prev = db.scalar(select(Message).where(Message.session_id == sess.id, Message.role == "user",
                                               Message.id != (user_msg.id if user_msg else 0))
                         .order_by(Message.id.desc()).limit(1))
        query += "\n" + (prev.content[-120:] if prev else "")
    mems = memory.retrieve(db, user_id=user.id, character_id=char.id, query=query,
                           allow_sensitive=bool(us.get("save_sensitive")))
    bond = memory.get_bond(db, user.id, char.id)
    lore = lore_hits(char, query)
    # 联网：只在正常聊天回复时给她搜索工具（主动开口、互动反应、讲故事不需要）；服务端和用户都可以关
    web = p.mode == "respond" and settings.web_search != "off" and bool((us.get("interaction") or {}).get("web", True))
    ctx = build_system(char, user_name=user.display_name, memories=mems,
                       summary=memory.latest_summary(db, user.id, char.id), lore=lore,
                       bond=memory.bond_prompt(bond, char.name), current=memory.current_prompt(bond), mode=p.mode,
                       perception=p.perception, gesture=policy.gesture_text(gesture) if gesture else None, web=web)
    p.system, p.recall, p.skipped = ctx.system, ctx.used, ctx.skipped
    p.history = _history(db, sess.id) or [{"role": "user", "content": event_text("quiet")}]
    if p.history[-1]["role"] != "user":
        p.history.append({"role": "user", "content": event_text("quiet")})
    first = db.scalar(select(Message.id).where(Message.session_id == sess.id, Message.role == "assistant").limit(1)) is None
    p.llm_context = {"payer": user.id, "character": char, "mode": p.mode, "model": chat_model_for(char.model), "first_turn": first,
                     "hits": mems, "lore": lore, "perception": p.perception,
                     "gesture": policy.gesture_text(gesture) if gesture else None,
                     "web": web, "sources": []}  # sources：模型调用时把查过的网页填进来
    return p


def _actions(p: Plan, char: Character, text: str, parsed_expr: str | None, found: list | None = None,
             user_settings: dict | None = None, parsed_anim: str | None = None) -> list[dict]:
    """把策略的选择变成前端 / 设备执行的结构化行为。模型只能建议表情；是否换表情、做什么动作由策略决定。
    例外：她在括号里写的动作（found，见 cues.py）照着演，但仍守住硬约束：用户关了预设动作就不动，不在角色动作列表里的不做。"""
    out: list[dict] = []
    if text:
        out.append({"type": "say", "text": text, "story": p.decision.primary.action == "STORY"})
    if p.fixed_text in PERCEIVE_ASK.values():
        out.append({"type": "perceive_request"})
    b = char.behavior or {}
    exprs, anims = b.get("expressions") or EXPRESSIONS, b.get("animations") or ANIMATIONS
    cue_expr = next((c.expression for c in found or [] if c.expression in exprs), None)
    cue_anim = next((c.animation for c in found or [] if c.animation in anims), None) or (parsed_anim if parsed_anim in anims else None)
    if not ((user_settings or {}).get("interaction") or {}).get("animations", True):
        cue_anim = None
    emoted = animated = False
    for c in p.decision.extras:
        if c.action == "EMOTE":
            expr = cue_expr or c.params.get("expression") or parsed_expr or b.get("default_expression", "calm")
            out.append({"type": "emote", "expression": expr})
            emoted = True
        elif c.action == "ANIMATE" and not animated:
            out.append({"type": "animate", "name": cue_anim or c.params["name"]})
            animated = True
    if cue_expr and not emoted:
        out.append({"type": "emote", "expression": cue_expr})
    if cue_anim and not animated:
        out.append({"type": "animate", "name": cue_anim})
    return out


def finalize(db: Session, p: Plan, raw: str) -> dict:
    """保存回复，产生行为事件，排队整理记忆。"""
    sess = db.get(ChatSession, p.session_id)
    char = db.get(Character, p.character_id)
    user = db.get(User, p.user_id)
    parsed = parse_reply(raw, char) if raw else None
    text = parsed.text if parsed else (p.fixed_text or "")
    acts = _actions(p, char, text, parsed.expression if parsed else None, parsed.cues if parsed else None, user.settings,
                    parsed.animation if parsed else None)
    reply = None
    if text:
        reply = Message(session_id=sess.id, role="assistant", content=text,
                        state={"expression": parsed.expression if parsed else None,
                               "animation": parsed.animation if parsed else None, "mood": parsed.mood if parsed else ""},
                        meta={"event": p.event_type, "decision": p.decision.as_dict(), "actions": acts,
                              "recall": p.recall, "recall_skipped": p.skipped, "perception": p.perception,
                              "model": p.llm_context.get("model") if p.mode else None,
                              "sources": p.llm_context.get("sources") or []})
        db.add(reply)
    suggestion = None
    if any(c.action == "REMEMBER" for c in p.decision.extras) and p.user_message_id:
        msg = db.get(Message, p.user_message_id)
        story = p.decision.primary.action == "STORY" or bool((msg.meta or {}).get("story"))
        cand = memory.add_candidate(db, user_id=user.id, cid=char.id, reason="suggested", data={
            "type": "event", "content": f"用户和{char.name}：{compact(msg.content, 80)}", "evidence": msg.content[:200],
            "basis": "stated", "reality": "story" if story else "real", "importance": 3, "sources": [msg.uid],
            "note": f"{char.name}想把这段经历记下来"})
        suggestion = {"type": "remember_suggest", "candidate_id": cand.id, "content": cand.data["content"]}
        acts.append(suggestion)
    sess.updated_at = now()
    job = None
    if p.user_message_id and p.event_type == "message":
        job = MemoryJob(user_id=user.id, character_id=char.id, message_id=p.user_message_id)
        db.add(job)
    elif p.user_message_id:
        b = memory.get_bond(db, user.id, char.id)
        memory.touch_bond(b, now())
    db.commit()
    if job:
        memory.enqueue(job.id)
    from .devices import hub

    ar = hub.present(user.id, char, acts)
    return {"reply": _msg_out(reply) if reply else None,
            "user": _msg_out(db.get(Message, p.user_message_id)) if p.user_message_id else None,
            "actions": acts, "decision": p.decision.as_dict(), "memory_job": job.id if job else None, "ar": ar}


def run_turn(db: Session, p: Plan) -> dict:
    raw = ""
    if p.mode:
        t0 = time.perf_counter()
        r = get_llm().complete(system=p.system, messages=p.history, context=p.llm_context)
        raw = r.text if not r.refused else event_text("refused")
        events.record("llm", "complete", user_id=p.user_id, character_id=p.character_id,
                      latency_ms=(time.perf_counter() - t0) * 1000, payload={"model": r.model})
    return finalize(db, p, raw)


def stream_turn(p: Plan) -> Iterator[str]:
    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    yield sse("decision", {"actions": p.decision.actions(), "policy": p.decision.policy, "label": p.decision.label})
    raw = ""
    t0 = time.perf_counter()
    try:
        if p.mode:
            f = StreamFilter()
            for chunk in get_llm().stream(system=p.system, messages=p.history, context=p.llm_context):
                raw += chunk
                if out := f.feed(chunk):
                    yield sse("delta", {"text": out})
            events.record("llm", "stream", user_id=p.user_id, character_id=p.character_id,
                          latency_ms=(time.perf_counter() - t0) * 1000)
        db = SessionLocal()
        try:
            result = finalize(db, p, raw)
        finally:
            db.close()
        result["latency_ms"] = round((time.perf_counter() - t0) * 1000)
        yield sse("done", result)
    except LLMError as e:
        _rollback_user_message(p)
        yield sse("error", {"message": tr(str(e))})
    except Exception as e:  # noqa: BLE001
        log.exception("流式回复失败")
        events.error("stream", f"{type(e).__name__}: {e}")
        _rollback_user_message(p)
        yield sse("error", {"message": tr("回复失败了，请稍后再试")})


def _rollback_user_message(p: Plan) -> None:
    """模型失败时撤回刚存的用户消息，前端会把原文放回输入框。"""
    if not p.user_message_id:
        return
    db = SessionLocal()
    try:
        m = db.get(Message, p.user_message_id)
        if m:
            db.delete(m)
            db.commit()
    finally:
        db.close()


# ---------- 会话 ----------

def _session_out(s: ChatSession) -> dict:
    return {"id": s.id, "character_id": s.character_id, "title": s.title, "created_at": s.created_at.isoformat(),
            "updated_at": s.updated_at.isoformat(), "ended": s.ended_at is not None}


def _msg_out(m: Message) -> dict:
    return {"id": m.id, "uid": m.uid, "role": m.role, "content": m.content, "state": m.state, "meta": m.meta,
            "created_at": m.created_at.isoformat()}


def _own(db: Session, user: User, sid: str) -> ChatSession:
    s = db.get(ChatSession, sid)
    if s is None or s.user_id != user.id:
        raise HTTPException(404, "会话不存在")
    return s


def _open(db: Session, user: User, sid: str) -> ChatSession:
    s = _own(db, user, sid)
    if s.ended_at is not None:
        raise HTTPException(400, "会话已结束，请开始新会话")
    return s


SUMMARY_SYSTEM = ("你负责为一段角色对话写会话摘要，供角色下次见面时回忆。第三人称、200 字以内，写清楚：聊了什么、"
                  "用户透露的近况、约定或没聊完的话题。幻想剧情要注明是故事。不要编造对话里没有的内容。只输出摘要正文。")
REFLECT_SYSTEM = "你是角色本人。用两三句话、第一人称写下你现在对对方的印象（只根据摘要，不编造）。只输出这几句话。"
SUMMARY_SYSTEM_EN = ("Write a summary of this character chat so the character can remember it next time. Third person, under 120 words: "
                     "what you talked about, what the user shared about their life, promises or unfinished topics. Mark fantasy stories as stories. "
                     "Don't invent anything that isn't in the chat. Output only the summary, in English.")
REFLECT_SYSTEM_EN = ("You are the character. In two or three first-person sentences, write your current impression of the other person "
                     "(based only on the summary, nothing invented). Output only those sentences, in English.")


def summarize(db: Session, user: User, s: ChatSession) -> dict | None:
    s.ended_at = now()
    char = db.get(Character, s.character_id)
    msgs = [m for m in s.messages if m.content != memory.PURGED_TEXT]
    users = [m for m in msgs if m.role == "user"]
    b = memory.get_bond(db, user.id, char.id)
    b.sessions += 1
    if len(users) >= 4:
        b.closeness = min(100.0, b.closeness + memory.SESSION_BONUS)
    if len(users) < 2:
        db.commit()
        return None
    en = locale() == "en"
    transcript = "\n".join(f"{('User' if en else '用户') if m.role != 'assistant' else char.name}{': ' if en else '：'}{m.content}" for m in msgs[-40:])
    llm = get_llm()
    r = llm.complete(system=SUMMARY_SYSTEM_EN if en else SUMMARY_SYSTEM, messages=[{"role": "user", "content": f"<transcript>\n{transcript}\n</transcript>"}],
                     max_tokens=800, context={"task": "summary", "payer": user.id, "name": char.name,
                                              "history": [{"role": m.role, "content": m.content} for m in msgs]})
    if r.refused or not r.text.strip():
        db.commit()
        return {"skipped": "摘要生成失败"}
    m = memory.create_memory(db, user_id=user.id, character_id=char.id, content=r.text.strip(), type="summary",
                             origin="summary", importance=2, title=f"{'Chat' if en else '会话'} {s.created_at.astimezone().strftime('%m-%d %H:%M')}"
                                                                     f"：{compact(s.title or '', 20)}",
                             sources=[x.uid for x in users][-20:])
    try:
        v = llm.complete(system=REFLECT_SYSTEM_EN if en else REFLECT_SYSTEM, messages=[{"role": "user", "content": m.content}], max_tokens=300,
                         context={"task": "bond_reflect", "payer": user.id})
        if v.text.strip() and not v.refused:
            b.her_view = v.text.strip()[:300]
    except LLMError:
        pass
    db.commit()
    return {"id": m.id, "title": m.title}


class SessionIn(BaseModel):
    character_id: str


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    image: str | None = Field(default=None, max_length=8_000_000)  # data URL
    source: str = Field(default="app", pattern="^(app|voice|glasses)$")
    character_id: str | None = Field(default=None, max_length=32)  # 页面上正在聊的角色：和会话对不上就拒绝，防止串到别的角色


class EventIn(BaseModel):
    type: str = Field(pattern="^(idle|gesture|perception)$")
    gesture: str | None = None
    idle_count: int = Field(default=1, ge=0, le=100)
    text: str = Field(default="", max_length=400)
    image: str | None = Field(default=None, max_length=8_000_000)
    character_id: str | None = Field(default=None, max_length=32)


def _same_character(s: ChatSession, character_id: str | None) -> None:
    """每个角色是自己的对话、自己的记忆。前端切换角色的瞬间，旧会话的请求不能落到新角色上（反过来也一样）。"""
    if character_id and character_id != s.character_id:
        raise HTTPException(409, "这段对话属于另一个角色，已经帮你切回来了，请再发一次")


@router.get("")
def list_sessions(character_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    get_owned(db, user, character_id)
    rows = db.scalars(select(ChatSession).where(ChatSession.user_id == user.id, ChatSession.character_id == character_id)
                      .order_by(ChatSession.updated_at.desc()).limit(50))
    return [_session_out(s) for s in rows]


@router.post("")
def create_session(body: SessionIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = get_owned(db, user, body.character_id)
    s = ChatSession(user_id=user.id, character_id=c.id)
    db.add(s)
    memory.apply_decay(db, user.id, c.id)  # 新会话开始时顺便整理淡化
    db.commit()
    greeting = (c.persona or {}).get("greeting")
    return {**_session_out(s), "greeting": greeting}


@router.get("/{sid}")
def get_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own(db, user, sid)
    return {**_session_out(s), "messages": [_msg_out(m) for m in s.messages]}


@router.post("/{sid}/messages")
def send(sid: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    credits.check(db, user)
    s = _open(db, user, sid)
    _same_character(s, body.character_id)
    p = plan_turn(db, user, s, event="message", text=body.text.strip(), image=decode_image(body.image), source=body.source)
    try:
        return run_turn(db, p)
    except LLMError as e:
        db.rollback()
        _rollback_user_message(p)
        raise HTTPException(502, str(e)) from e


@router.post("/{sid}/stream")
def send_stream(sid: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    credits.check(db, user)
    s = _open(db, user, sid)
    _same_character(s, body.character_id)
    p = plan_turn(db, user, s, event="message", text=body.text.strip(), image=decode_image(body.image), source=body.source)
    db.commit()  # 用户消息先落库，流式生成在另一个数据库会话里收尾
    return StreamingResponse(stream_turn(p), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/{sid}/events")
def send_event(sid: str, body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """用户触发的预设互动、页面上的“安静了一阵”、眼镜模拟器分享的画面。"""
    credits.check(db, user)
    s = _open(db, user, sid)
    _same_character(s, body.character_id)
    p = plan_turn(db, user, s, event=body.type, text=body.text.strip(), gesture=body.gesture,
                  image=decode_image(body.image), idle_count=body.idle_count)
    try:
        return run_turn(db, p)
    except LLMError as e:
        db.rollback()
        _rollback_user_message(p)
        raise HTTPException(502, str(e)) from e


@router.post("/{sid}/end")
def end(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s = _own(db, user, sid)
    if s.ended_at is not None:
        return {**_session_out(s), "summary": None}
    try:
        summary = summarize(db, user, s)
    except LLMError as e:
        raise HTTPException(502, str(e)) from e
    return {**_session_out(s), "summary": summary}


@router.delete("/{sid}")
def delete_session(sid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(_own(db, user, sid))
    db.commit()
    return {"ok": True}
