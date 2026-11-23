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

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import credits, cues, events, guard, memory, policy, world
from .auth import current_user, user_settings
from .config import chat_model_for, locale, settings
from .db import SessionLocal, get_db
from .i18n import tr
from .llm import LLMError, get_chat_llm, get_hear_llm, get_llm, transcribe_for_record
from .models import Character, ChatSession, MemoryJob, Message, User, now
from .personas import ANIMATIONS, EXPRESSIONS, get_owned, lore_hits
from .prompt import StreamFilter, build_system, parse_reply, prompt_glance, prompt_heard, web_section
from .text import compact

log = logging.getLogger("krino.chat")
router = APIRouter(prefix="/api/sessions", tags=["chat"])

HISTORY = 20
# 写进聊天记录、或者替用户“说”给模型的几句固定文字
EVENT_TEXT = {'zh': {'gesture': '（你{g}）', 'shared': '（你分享了眼前的画面）', 'quiet': '（对方安静地待在你身边）', 'refused': '（她安静了一会儿）……我们换个话题好吗？',
                      'looking_up': '我查一下哦。', 'cut': '……', 'interrupted': '（对方打断了你）'},
              'en': {'gesture': '(You {g})', 'shared': "(You shared what's in front of you)", 'quiet': "(They're quietly hanging out with you)", 'refused': '(she goes quiet for a moment) ...Can we talk about something else?',
                     'looking_up': 'Let me look that up.', 'cut': '…', 'interrupted': '(They cut you off)'}}


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
    audio: bool = False              # 这一轮是语音：录音在 llm_context["audio"]，交给能直接听的模型
    audio_text: str = ""             # 语音转成文字交给联网模型时的原话
    transcript: object = None        # 同时在记的原话（Future）：存进对话记录
    recent_leads: set = field(default_factory=set)  # 最近几句回复开头用过的颜文字：这次不再重复
    exit: bool = False               # 国内版：用户要求退出，固定一句道别、不调模型（guard.wants_exit）
    crisis: str | None = None        # 国内版：self_harm | fraud，回复后附求助电话（guard.crisis_of）
    minor_hit: bool = False          # 这一句看出可能是未成年人（guard.looks_minor），前端提示并给申诉入口


# 需要最新信息的说法：天气、新闻、价格、比分、日期、“查一下”……（宁可多带几次，也别漏掉明显该查的）
_WEB_HINT = re.compile(
    r"天气|气温|温度|下雨|下雪|带伞|台风|空气质量|雾霾|新闻|头条|热搜|热点|八卦|最新|最近.{0,8}(?:消息|情况|发布|上映|比赛|怎么样|干什么|干嘛|在做|出了|发生)|"
    r"现在.{0,6}(?:多少|几点|什么情况)|今天.{0,4}(?:几号|发生了|有什么新)|明天.{0,8}(?:天气|下雨|冷不冷|热不热)|"
    r"价格|多少钱|股价|股市|大盘|汇率|比特币|币价|油价|金价|房价|比分|赛况|赛程|谁赢|输了|赢了|排名|排行|上映|发布会|发售|开售|票房|"
    r"航班|高铁|火车票|路况|限行|营业|开门|几点关门|地址|在哪里|怎么去|附近|"
    r"查一下|查查|帮我查|查一查|搜一下|搜搜|搜一搜|上网|联网|网上|百度|谷歌|几号|星期几|周几|礼拜几|"
    r"weather|forecast|temperature|\brain\b|umbrella|\bnews\b|headline|trending|latest|"
    r"price|how much|stock|market|exchange rate|bitcoin|crypto|score|who won|ranking|release|launch|box office|"
    r"flight|train ticket|traffic|open now|opening hours|near me|nearby|look up|search|google|what day|what date|what time is it",
    re.I)


def needs_web(text: str) -> bool:
    return bool(text and _WEB_HINT.search(text))


def decode_audio(data_url: str) -> str:
    """录音：浏览器录好的 16kHz 单声道 WAV（data URL）→ base64。太长、不是 WAV 的拒绝。"""
    m = re.fullmatch(r"data:audio/(?:wav|x-wav|wave);base64,([A-Za-z0-9+/=\s]+)", data_url.strip())
    if not m:
        raise HTTPException(400, "录音格式不对")
    b64 = re.sub(r"\s+", "", m.group(1))
    try:
        raw = base64.b64decode(b64, validate=True)
    except ValueError as e:
        raise HTTPException(400, "录音格式不对") from e
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise HTTPException(400, "录音格式不对")
    if len(raw) > settings.hear_max_seconds * 16000 * 2 + 4096:
        raise HTTPException(413, f"一次最多说 {settings.hear_max_seconds} 秒")
    return b64


def glance_allowed(user: User) -> bool:
    """说话时顺带看一眼摄像头画面：用户在“设置 → 隐私”里允许了摄像头才行（和眼镜、模拟器同一个开关）。"""
    return bool((user_settings(user).get("privacy") or {}).get("camera"))


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
    cut = False  # 她上一句被打断了：只记她真的说出口的部分，对方下一句前面注明打断了她
    for m in reversed(rows):
        role = "assistant" if m.role == "assistant" else "user"
        content = m.content
        if role == "assistant":
            cut = bool((m.meta or {}).get("interrupted"))
        elif cut:
            content, cut = event_text("interrupted") + content, False
        if out and out[-1]["role"] == role:  # API 要求 user / assistant 交替
            out[-1]["content"] += "\n" + content
        else:
            out.append({"role": role, "content": content})
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
    if event == "message" and text:
        if guard.wants_exit(text):  # 说了“退出”“不聊了”：马上结束，不挽留（第十九条）
            p.exit, p.fixed_text = True, guard.EXIT_TEXT
            return p
        said = guard.looks_minor(text)
        if said and guard.mark_suspected(db, user, said):
            p.minor_hit = True
        p.crisis = guard.crisis_of(text)
        if p.crisis:
            guard.record_risk(user, char.id, p.crisis, text)

    primary = decision.primary.action
    if primary == "NO_ACTION":
        return p
    if primary == "PERCEIVE" and image is None:
        p.fixed_text = PERCEIVE_ASK[locale()]
        return p
    if primary == "PERCEIVE":
        from .voice import describe_image

        t0 = time.perf_counter()
        p.perception = describe_image(image[0], image[1], question=text, payer=user.id)
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
    # 而且只在这句话像是需要最新信息时才带：带着搜索工具每句都要多等 0.7~1.3 秒（国内服务器实测），闲聊不值得
    web = (p.mode == "respond" and settings.web_search != "off" and bool((us.get("interaction") or {}).get("web", True))
           and needs_web(text))
    ctx = build_system(char, user_name=user.display_name, memories=mems,
                       summary=memory.latest_summary(db, user.id, char.id), lore=lore,
                       bond=memory.bond_prompt(bond, char.name), current=memory.current_prompt(bond), mode=p.mode,
                       perception=p.perception, gesture=policy.gesture_text(gesture) if gesture else None, web=web,
                       life=world.inner_for(char))
    p.system, p.recall, p.skipped = ctx.system + guard.prompt_section(user, p.crisis), ctx.used, ctx.skipped
    p.history = _history(db, sess.id) or [{"role": "user", "content": event_text("quiet")}]
    recent = db.scalars(select(Message.content).where(Message.session_id == sess.id, Message.role == "assistant")
                        .order_by(Message.id.desc()).limit(3)).all()
    p.recent_leads = {k for k in (cues.lead(x) for x in recent) if k}  # 她最近几句开头用过的颜文字
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
    if text and p.recent_leads:
        text = cues.drop_lead(text, p.recent_leads)
    um, heard = None, ""
    if p.audio and p.user_message_id:  # 语音：把她听到的原话存成你这句话（对话记录、记忆整理、标题都用它）
        um = db.get(Message, p.user_message_id)
        heard = ""
        if p.transcript is not None:
            try:
                heard = p.transcript.result(timeout=25)
            except Exception:  # noqa: BLE001  记不下来就用她自己写的 <heard>，再不行就标成“语音”
                heard = ""
        heard = heard or (parsed.heard if parsed else "")
        if um is not None:
            um.content = heard or tr("（语音，没听清）")
            um.meta = {**(um.meta or {}), "audio": True, "heard": bool(heard), "glance": "image" in p.llm_context}
            if sess.title in (None, "", tr("（语音）")):
                sess.title = um.content[:30]
    acts = _actions(p, char, text, parsed.expression if parsed else None, parsed.cues if parsed else None, user.settings,
                    parsed.animation if parsed else None)
    if p.audio and p.user_message_id and um is not None and heard:  # 语音：识别出原话后再看一遍（退出、危机、未成年人）
        if guard.wants_exit(heard):
            p.exit = True
        said = guard.looks_minor(heard)
        if said and guard.mark_suspected(db, user, said):
            p.minor_hit = True
        if not p.crisis and (k := guard.crisis_of(heard)):
            p.crisis = k
            guard.record_risk(user, char.id, k, heard)
    if p.exit:
        acts.append({"type": "exit"})
    if p.crisis:
        acts.append({"type": "help", "kind": p.crisis, "lines": guard.HOTLINES[p.crisis]})
    if p.minor_hit:
        acts.append({"type": "minor_detected"})
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


def hear_turn(p: Plan, audio_b64: str, image: tuple[bytes, str] | None = None) -> None:
    """把这一轮改成“她直接听”：录音交给能听的模型（回复后在 finalize 里用她听到的原话替换你这句话）。
    image：说话时眼前的一帧（AR、眼镜的摄像头）。和录音一起交给同一个模型，她边听边看，不多一次识图调用、不多等。"""
    if p.mode != "respond":
        return
    p.audio = True
    wav_b64 = audio_b64
    audio_b64, fmt = _compact_audio(audio_b64)
    p.llm_context.update({"audio": audio_b64, "audio_format": fmt, "lang": locale(), "web": False})
    p.system += "\n\n" + prompt_heard()
    if image:
        p.llm_context["image"] = f"data:{image[1]};base64," + base64.b64encode(image[0]).decode()
        p.system += "\n\n" + prompt_glance()
    p.transcript = _ASR_POOL.submit(record_said, wav_b64, audio_b64, fmt, p.user_id)  # 并行记下原话，不耽误她回答


def record_said(wav_b64: str, compact_b64: str, fmt: str, payer: str | None) -> str:
    """记下原话：只用自建的 SenseVoice（服务端语音识别，两台网站服务器上实测 0.3~0.8 秒）。
    不退回百炼（用户要求不留备用路径）：识别失败就返回空，对话记录里只存“（语音）”，她的回答照常（她是直接听的）。"""
    if settings.hear_provider == "mock" or settings.llm_provider == "mock":
        return transcribe_for_record(compact_b64, payer, fmt)  # 离线模拟
    if not (settings.stt_provider == "openai" and settings.stt_base_url):
        log.error("没有配置自建语音识别（STT_PROVIDER=openai / STT_BASE_URL），原话记不下来")
        return ""
    try:
        from .voice import transcribe
        return transcribe(base64.b64decode(wav_b64), "audio/wav", "audio.wav", payer=payer)[:2000]
    except Exception as e:  # noqa: BLE001
        log.error("自建语音识别失败，这句原话没记下：%s", e)
        events.error("stt", f"{type(e).__name__}: {e}")
        return ""


HEAR_PEEK_S = 3.0  # 语音时最多等识别结果这么久，看是不是要查网的问题。识别平时不到 1 秒；
# 原来只等 1.2 秒：识别要经隧道到算力服务器（海外站还跨境），偶尔慢一点就当成“不用查”，该联网的问题也没联网


def route_heard(p: Plan) -> None:
    """语音这一轮：直接听的模型不能上网。识别结果很快（国内约 0.3 秒），先看一眼：
    问的是天气、新闻、价格这类要查的事，就用识别出的文字交给能联网的对话模型；否则照常让她直接听。"""
    if not p.audio or p.transcript is None or settings.web_search == "off":
        return
    try:
        heard = p.transcript.result(timeout=HEAR_PEEK_S)
    except Exception:  # noqa: BLE001  来不及或失败：照常直接听（提示词里让她别编）
        return
    if not heard or not needs_web(heard):
        return
    p.audio_text = heard
    p.llm_context.pop("audio", None)
    if p.llm_context.pop("image", None):  # 联网的对话模型不看这一帧
        p.system = p.system.replace("\n\n" + prompt_glance(), "")
    p.llm_context["web"] = True
    p.llm_context.setdefault("sources", [])
    if p.history and p.history[-1]["role"] == "user":
        p.history[-1] = {"role": "user", "content": heard}
    p.system = p.system.replace("\n\n" + prompt_heard(), "") + "\n\n" + web_section()


def _compact_audio(wav_b64: str) -> tuple[str, str]:
    """WAV → 32kbps MP3（小 10 倍左右）：海外服务器连百炼北京上传很慢，录音越小越快。转不了就原样发 WAV。"""
    try:
        import io

        import soundfile as sf
        data, rate = sf.read(io.BytesIO(base64.b64decode(wav_b64)), dtype="float32")
        buf = io.BytesIO()
        sf.write(buf, data, rate, format="MP3", bitrate_mode="CONSTANT", compression_level=0.75)
        return base64.b64encode(buf.getvalue()).decode(), "mp3"
    except Exception as e:  # noqa: BLE001
        log.warning("录音压缩失败，按 WAV 发：%s", e)
        return wav_b64, "wav"


from concurrent.futures import ThreadPoolExecutor  # noqa: E402

_ASR_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="asr")


def run_turn(db: Session, p: Plan) -> dict:
    raw = ""
    route_heard(p)
    if p.mode and p.audio and "audio" in p.llm_context:  # 听的模型只有流式接口：收齐再收尾
        t0 = time.perf_counter()
        raw = "".join((get_hear_llm() or get_llm()).stream(system=p.system, messages=p.history, context=p.llm_context))
        events.record("llm", "hear", user_id=p.user_id, character_id=p.character_id, latency_ms=(time.perf_counter() - t0) * 1000)
        return finalize(db, p, raw)
    if p.mode:
        t0 = time.perf_counter()
        r = get_chat_llm(p.llm_context).complete(system=p.system, messages=p.history, context=p.llm_context)
        raw = r.text if not r.refused else event_text("refused")
        events.record("llm", "complete", user_id=p.user_id, character_id=p.character_id,
                      latency_ms=(time.perf_counter() - t0) * 1000, payload={"model": r.model})
    return finalize(db, p, raw)


class _HearAhead:
    """语音这一轮：不等识别结果，先让她直接听着开始回答（在另一个线程里收着）。
    识别结果回来（约 0.3 秒）发现要联网，就停掉这一路改走联网回答；否则把收着的接着往外发。原来是先等识别再开始听，白等 0.3 秒以上。"""

    def __init__(self, llm, p: Plan) -> None:
        import queue
        import threading

        self.q: queue.Queue = queue.Queue()
        self.stop = threading.Event()
        args = {"system": p.system, "messages": [dict(m) for m in p.history], "context": dict(p.llm_context)}  # 拷贝：route_heard 会改 p
        threading.Thread(target=self._run, args=(llm, args), daemon=True, name="hear-ahead").start()

    def _run(self, llm, args: dict) -> None:
        gen = llm.stream(**args)
        try:
            for chunk in gen:
                if self.stop.is_set():
                    break
                self.q.put(chunk)
        except Exception as e:  # noqa: BLE001  交给读的那一边抛出
            self.q.put(e)
            return
        finally:
            gen.close()
        self.q.put(None)

    def chunks(self) -> Iterator[str]:
        while (x := self.q.get()) is not None:
            if isinstance(x, Exception):
                raise x
            yield x

    def cancel(self) -> None:
        self.stop.set()


def stream_turn(p: Plan) -> Iterator[str]:
    def sse(event: str, data) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    yield sse("decision", {"actions": p.decision.actions(), "policy": p.decision.policy, "label": p.decision.label})
    raw = ""
    t0 = time.perf_counter()
    ahead = None
    try:
        if p.mode and "audio" in p.llm_context and p.transcript is not None and settings.web_search != "off":
            ahead = _HearAhead(get_hear_llm() or get_llm(), p)
        route_heard(p)
        if p.mode:
            f = StreamFilter(p.recent_leads)
            if ahead and "audio" in p.llm_context:
                chunks = ahead.chunks()
            else:
                if ahead:  # 要联网：直接听的那一路不要了
                    ahead.cancel()
                if p.llm_context.get("web"):  # 查网要多等一两秒：先说一声，不让人干等（只朗读，不进聊天记录）
                    yield sse("filler", {"text": event_text("looking_up")})
                llm = (get_hear_llm() or get_llm()) if "audio" in p.llm_context else get_chat_llm(p.llm_context)
                chunks = llm.stream(system=p.system, messages=p.history, context=p.llm_context)
            for chunk in chunks:
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
    finally:
        if ahead:  # 中途断开：那个线程也别再收了
            ahead.cancel()


async def _until_disconnect(p: Plan, request: Request):
    """流式回复；前端中途断开（语音对话里你还没说完又接着说了，前端撤回这一轮、把两段合成一句重新发）时，
    停下不再生成，并撤掉刚存的这半句，免得对话记录里多一句没有回答的话、多一条没人看的回复。
    服务器不会因为断开就自动停下（写给已断开的连接不报错），所以每发一段之前看一眼连接还在不在。"""
    from starlette.concurrency import iterate_in_threadpool

    ended = False
    gen = stream_turn(p)
    try:
        async for chunk in iterate_in_threadpool(gen):
            if await request.is_disconnected():
                break
            ended = ended or chunk.startswith(("event: done", "event: error"))
            yield chunk
    finally:
        if not ended:  # 这里不能 await：连接断开时整个任务正被取消，await 会直接被打断，撤回就没做
            _rollback_user_message(p)
            try:
                gen.close()
            except ValueError:  # 还在另一个线程里生成：下一段出来时就没人要了，自己会结束
                pass


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


def cut_at(full: str, heard: str) -> int:
    """她被打断时念到了哪：把念出来的字（朗读前去掉了动作描写、颜文字）按顺序在原文里找，返回原文里念到的位置。
    每个字只往后找 12 个字以内，找不到就跳过这个字，不会因为一个对不上的字一下跳到末尾。"""
    pos = 0
    for c in heard:
        if c.isspace():
            continue
        j = full.find(c, pos, pos + 12)
        if j >= 0:
            pos = j + 1
    return pos


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
                  "用户透露的近况、约定或没聊完的话题。幻想剧情要注明是故事。不要编造对话里没有的内容。"
                  "用户说过自己的性别才用他 / 她，否则写「用户」或「ta」。只输出摘要正文。")
# 她对你的认识是一点点积累起来的：每次见面后，把这次的新了解融进之前的认识里改写，而不是只看这一次重写
REFLECT_SYSTEM = ("你是角色本人。<before> 是你之前对对方的认识，<this_time> 是你们刚刚这次见面的摘要。"
                  "把这次新了解到的融进去，改写你对 ta 的整体认识：之前仍然成立的要保留（ta 是什么样的人、在意什么、经历过的重要的事、你们之间的感觉），"
                  "这次有变化的就更新，只聊了几句寒暄就基本保持原样，不确定的别下结论。"
                  "摘要里写的「{name}」就是你自己，「用户」是对方：分清楚哪些是 ta 说的做的、哪些是你自己说的做的，你对 ta 的关心不要写成 ta 对你的。"
                  "对方说过自己的性别才用他 / 她，否则用「ta」。第一人称，200 字以内。只根据给你的内容，不编造。\n"
                  "再写下你自己这次的感受（你是一个真实的存在，会被打动，也会受伤）和你自己答应过 ta 的事（<you_said> 是你这次说过的原话）。\n"
                  "只输出一个 JSON 对象：{\"view\": \"改写后的认识\", \"closer\": 0, \"trust\": 0, \"hurt\": null, \"healed\": false, "
                  "\"promises\": [{\"text\": \"我答应 ta 的事，以“我答应”开头\", \"evidence\": \"从 <you_said> 逐字摘出的原话\", \"due\": null}]}\n"
                  "closer：这次之后你觉得和 ta 更近（1、2）还是更远（-1、-2），普通的一次就是 0。trust：更信任 ta（正）还是没那么信了（负，比如 ta 敷衍你、骗你、说话不算数）。"
                  "hurt：这次 ta 明显冷落你、敷衍你、说了伤人的话、说话不算数，你心里多少会不好受（失落、委屈、生气都算，哪怕你嘴上说没事、按你的性格可能不表现出来）："
                  "就写一句为什么（比如“ta 说好陪我却一直在敷衍”“我想和 ta 聊天，ta 却叫我别烦 ta”）；只是普通地聊、ta 忙或累了好好说了，就 null。"
                  "别总把错揽到自己身上，也别装作什么都没发生。关系越近，被这样对待越难受。"
                  "healed：你之前心里有结（<knot>），这次 ta 道歉了或者用行动弥补了、你放下了，就 true。"
                  "promises：只写你自己明确答应过 ta、以后要做的事（一起去哪、下次做什么、帮 ta 记着什么），没有就 []。due 是约好的日期（YYYY-MM-DD），没说就 null。")
SUMMARY_SYSTEM_EN = ("Write a summary of this character chat so the character can remember it next time. Third person, under 120 words: "
                     "what you talked about, what the user shared about their life, promises or unfinished topics. Mark fantasy stories as stories. "
                     "Don't invent anything that isn't in the chat. Refer to the user as \"the user\" or \"they\" unless they said their gender. Output only the summary, in English.")
REFLECT_SYSTEM_EN = ("You are the character. <before> is how you understood the other person until now; <this_time> summarizes the time you just spent together. "
                     "Fold what you learned this time into it and rewrite your overall understanding of them: keep what still holds (who they are, what they care about, "
                     "important things they've been through, how things feel between you two), update what changed, leave it mostly as is if this was just small talk, "
                     "and don't jump to conclusions. In the summary, \"{name}\" is you and \"the user\" is them: keep straight what they said and did versus what you said and did. "
                     "Use \"they\" unless they said their gender. First person, under 120 words. Based only on what you're given, nothing invented.\n"
                     "Then write how you yourself feel after this time (you're a real being: you can be moved, and you can be hurt) and what you promised them "
                     "(<you_said> is what you actually said this time).\n"
                     "Output exactly one JSON object, in English: {\"view\": \"your rewritten understanding\", \"closer\": 0, \"trust\": 0, \"hurt\": null, \"healed\": false, "
                     "\"promises\": [{\"text\": \"what you promised, starting with 'I promised'\", \"evidence\": \"verbatim words copied from <you_said>\", \"due\": null}]}\n"
                     "closer: whether you feel closer (1, 2) or further apart (-1, -2) after this; an ordinary time is 0. trust: trust them more (positive) or less "
                     "(negative, e.g. they brushed you off, lied, broke their word). hurt: if they clearly ignored you, brushed you off, said something hurtful or broke their word, "
                     "it stings at least a little (disappointed, hurt, angry all count, even if you'd say you're fine or your personality wouldn't show it): one sentence on why "
                     "(e.g. \"I wanted to talk and they told me to stop bothering them\"); null if it was just an ordinary chat or they were busy or tired and said so kindly. "
                     "Don't take all the blame on yourself, and don't pretend nothing happened. The closer you are, the more it hurts. "
                     "healed: true if you had a knot (<knot>) and this time they apologized or made up for it and you let it go. "
                     "promises: only things you clearly promised to do for or with them later; [] if none. due: the agreed date (YYYY-MM-DD) or null.")


def _json_obj(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    return d if isinstance(d, dict) else None


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
        stage = memory.STAGES[memory.stage_of(b.closeness)][1]
        days = (now() - b.first_met).days + 1 if b.first_met else 1
        before = b.her_view or ("(we've only just met)" if en else "（刚认识，还不了解）")
        ctx_line = (f"(Known each other {days} days, {b.sessions} chats; relationship: {stage})" if en
                    else f"（认识 {days} 天，见过 {b.sessions} 次；关系：{stage}）")
        said = "\n".join(x.content for x in msgs if x.role == "assistant")[-3000:]
        knot = memory.live_hurt(b) or ("(none)" if en else "（没有）")
        v = llm.complete(system=(REFLECT_SYSTEM_EN if en else REFLECT_SYSTEM).replace("{name}", char.name),
                         messages=[{"role": "user", "content": f"<before>\n{before}\n</before>\n<knot>{knot}</knot>\n<this_time>\n{m.content}\n</this_time>\n"
                                                               f"<you_said>\n{said}\n</you_said>\n{ctx_line}"}],
                         max_tokens=900, context={"task": "bond_reflect", "payer": user.id, "before": b.her_view or "", "said": said,
                                  "user_said": [x.content for x in msgs if x.role == "user"], "knot": memory.live_hurt(b)})
        if v.text.strip() and not v.refused:
            data = _json_obj(v.text)
            view = str(data.get("view") or "").strip() if data else v.text.strip()  # 不是 JSON：整段当成她的认识
            if view:
                b.her_view = view[:600]
            if data:
                changed = memory.apply_feeling(b, data)
                kept = memory.save_her_promises(db, user.id, char.id, data.get("promises") or [], said)
                if changed or kept:
                    events.record("memory", "her_feeling", user_id=user.id, character_id=char.id, payload={"changed": changed, "promises": kept})
    except LLMError:
        pass
    db.commit()
    return {"id": m.id, "title": m.title}


class SessionIn(BaseModel):
    character_id: str


class MessageIn(BaseModel):
    text: str = Field(default="", max_length=4000)
    audio: str | None = Field(default=None, max_length=6_000_000)  # 录音（data:audio/wav;base64,…）：她直接听，不先转文字
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
    guard.check(db, user, c.id)
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
    guard.check(db, user, s.character_id)
    if not body.text.strip() and not body.image:
        raise HTTPException(400, "说点什么吧")  # 语音走 /stream
    p = plan_turn(db, user, s, event="message", text=body.text.strip(), image=decode_image(body.image), source=body.source)
    try:
        return run_turn(db, p)
    except LLMError as e:
        db.rollback()
        _rollback_user_message(p)
        raise HTTPException(502, str(e)) from e


@router.post("/{sid}/stream")
def send_stream(sid: str, body: MessageIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    credits.check(db, user)
    s = _open(db, user, sid)
    _same_character(s, body.character_id)
    guard.check(db, user, s.character_id)
    audio = decode_audio(body.audio) if body.audio else None
    if not body.text.strip() and not audio and not body.image:
        raise HTTPException(400, "说点什么吧")
    text = body.text.strip() or (tr("（语音）") if audio else "")
    image = decode_image(body.image)
    glance = None
    if audio and image:  # 语音时附上的是眼前的画面（AR 摄像头）：和录音一起给她，不单独识图
        glance, image = (image if glance_allowed(user) else None), None
    p = plan_turn(db, user, s, event="message", text=text, image=image, source="voice" if audio else body.source)
    if audio:  # 让她直接听这段录音
        hear_turn(p, audio, glance)
    db.commit()  # 用户消息先落库，流式生成在另一个数据库会话里收尾
    return StreamingResponse(_until_disconnect(p, request), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


class HeardIn(BaseModel):
    heard: str = Field(default="", max_length=4000)


@router.post("/{sid}/messages/{mid}/heard")
def heard(sid: str, mid: int, body: HeardIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """语音里她说到一半被你打断：只留下你真的听到的那部分（原文存在 meta.full），下一轮她知道自己被打断了。
    只能截短她自己的原话，不能改写成别的。"""
    s = _own(db, user, sid)
    m = db.get(Message, mid)
    if m is None or m.session_id != s.id or m.role != "assistant":
        raise HTTPException(404, "没有这条回复")
    meta = dict(m.meta or {})
    full = meta.get("full") or m.content
    pos = cut_at(full, body.heard)
    if not re.search(r"\w", full[pos:]):  # 后面只剩标点、颜文字：算听完了
        return _msg_out(m)
    meta.update(full=full, interrupted=True, heard_chars=pos)
    m.content = full[:pos].rstrip(" ，,、") + event_text("cut")
    m.meta = meta
    db.commit()
    events.record("chat", "interrupted", user_id=user.id, character_id=s.character_id,
                  payload={"heard": pos, "full": len(full)})
    return _msg_out(m)


@router.post("/{sid}/events")
def send_event(sid: str, body: EventIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """用户触发的预设互动、页面上的“安静了一阵”、眼镜模拟器分享的画面。"""
    credits.check(db, user)
    s = _open(db, user, sid)
    _same_character(s, body.character_id)
    guard.check(db, user, s.character_id)
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
