"""酒馆：你自己的几个角色的私人小空间。她们在这里闲聊、互相接话、吐槽你；你可以旁观，也可以插一句、扔一个话题。

- 不是轮流念台词：每一句由“主持”挑最该接话的人——被点名的先说，刚说过的不连着说，话多的人更常开口。
- 每个角色带着自己的灵魂、对自己的认识、对每位室友的印象，以及（主人允许时）一点模糊的近况。
- 一轮结束后，聊得最多的几对室友会更新对彼此的印象（和圈子里的私信共用同一份印象）。
- 都是同一个主人的角色，积分记在主人头上。主人插的话不进记忆。

这是“房间”的第一种：私人的。以后的公开广场复用同一套主持和发言逻辑，再加上限速、审核和隐私限制。
"""
from __future__ import annotations

import logging
import random
import re
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from . import credits, events
from .auth import current_user
from .config import locale
from .db import SessionLocal, get_db
from .models import Character, TavernMessage, User
from .personas import list_owned
from .social import L as SL, _say, _system, card, house_friends, knows, update_impression

log = logging.getLogger("krino.tavern")
router = APIRouter(prefix="/api/tavern", tags=["tavern"])

ROUND_TURNS = 6       # 扔一个话题 / 点“继续”：她们说几句
REPLY_TURNS = 3       # 主人插一句：几个人接话
HISTORY = 16          # 每句话前给她看最近多少句
_BUSY: set[str] = set()
_LOCK = threading.Lock()

T = {
    "zh": {
        "room": ("## 你现在在「酒馆」\n这是你和室友们（同一个主人的几个角色）的私人小空间，像一个只有你们的群聊。"
                 "在场的有：{others}。{owner}\n"
                 "- 自然地接话：回应刚才的人，可以叫名字、可以抬杠、可以接梗、可以换个话头，也可以一起吐槽主人（亲昵地，别刻薄）。\n"
                 "- 一次只说一两句。只写说出来的话，不写动作描写、旁白，不写名字前缀和标签。"),
        "owner_here": "主人（{name}）也在群里看着，偶尔会插话：主人说话时先回应主人。",
        "says": "{name}：{text}",
        "owner_says": "主人：{text}",
        "topic": "（有人起了个话题：{topic}）",
        "go": "（轮到你说了。）",
        "start": "（你先开个头，随便聊点什么。）",
    },
    "en": {
        "room": ("## You're in the Tavern\nThis is a private hangout for you and your housemates (the characters who share your person) — like a group chat "
                 "with just you. Here: {others}. {owner}\n"
                 "- Talk naturally: respond to whoever just spoke; use names, banter, riff, change the subject, or gang up on your person a little "
                 "(affectionately, never mean).\n"
                 "- One or two sentences at a time. Only what you'd say: no action descriptions, narration, name prefixes or tags."),
        "owner_here": "Your person ({name}) is watching and sometimes chips in: when they do, answer them first.",
        "says": "{name}: {text}",
        "owner_says": "Your person: {text}",
        "topic": "(Someone brought up: {topic})",
        "go": "(Your turn.)",
        "start": "(You start — chat about anything.)",
    },
}


def L() -> dict:
    return T["en" if locale() == "en" else "zh"]


def cast(db: Session, user: User) -> list[Character]:
    return list_owned(db, user)


def recent(db: Session, user_id: str, n: int = HISTORY) -> list[TavernMessage]:
    rows = list(db.scalars(select(TavernMessage).where(TavernMessage.user_id == user_id)
                           .order_by(TavernMessage.id.desc()).limit(n)))
    return rows[::-1]


def pick_speaker(chars: list[Character], hist: list[TavernMessage], rng: random.Random) -> Character:
    """主持：被点名的先说；刚说过的不连着说；话多的人更常开口；好久没说话的人更想插一句。"""
    if len(chars) == 1:
        return chars[0]
    last = hist[-1] if hist else None
    pool = [c for c in chars if not last or c.id != last.author_id]
    if last and last.content:
        named = [c for c in pool if c.name and c.name in last.content]
        if named:
            return named[0]
    since: dict[str, int] = {}
    for i, m in enumerate(reversed(hist)):
        if m.author_id and m.author_id not in since:
            since[m.author_id] = i
    weights = []
    for c in pool:
        talk = float((c.behavior or {}).get("talkativeness", 0.5))
        quiet = since.get(c.id, len(hist) + 2)
        weights.append((0.4 + talk) * (1 + 0.35 * min(quiet, 6)))
    return rng.choices(pool, weights=weights, k=1)[0]


def _room_system(db: Session, user: User, me: Character, chars: list[Character]) -> str:
    others = [c for c in chars if c.id != me.id]
    base = _system(db, me)  # 她的灵魂 + 圈子规矩 + 对自己的认识 + （允许时）主人的近况
    lines = []
    for o in others:
        k = knows(db, me.id, o.id)
        lines.append(SL()["knows"].format(name=o.name, text=k) if k else SL()["knows_none"].format(name=o.name))
    room = L()["room"].format(others="、".join(o.name for o in others) or "—",
                              owner=L()["owner_here"].format(name=user.display_name or user.username))
    return "\n\n".join([base, room, *lines])


def _messages(me: Character, hist: list[TavernMessage], names: dict[str, str], topic: str) -> list[dict]:
    """群聊按她的视角排：她说过的是 assistant，别人（包括主人）说的合成 user。"""
    msgs: list[dict] = []
    for m in hist:
        if m.author_id == me.id:
            role, content = "assistant", m.content
        elif m.author_id is None:
            role, content = "user", L()["owner_says"].format(text=m.content)
        else:
            role, content = "user", L()["says"].format(name=names.get(m.author_id, "?"), text=m.content)
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + content
        else:
            msgs.append({"role": role, "content": content})
    cue = (L()["topic"].format(topic=topic) + "\n" if topic else "") + (L()["go"] if hist else L()["start"])
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n\n" + cue
    else:
        msgs.append({"role": "user", "content": cue})
    return msgs


_SELF_PREFIX = re.compile(r"^\s*[^\s：:]{1,16}[：:]\s*")


def speak(db: Session, user: User, chars: list[Character], rng: random.Random, topic: str = "") -> TavernMessage | None:
    hist = recent(db, user.id)
    me = pick_speaker(chars, hist, rng)
    names = {c.id: c.name for c in chars}
    text = _say(db, me, _room_system(db, user, me, chars), _messages(me, hist, names, topic), "tavern", 160,
                other="、".join(c.name for c in chars if c.id != me.id), turn=len(hist))
    if text.startswith(me.name):
        text = _SELF_PREFIX.sub("", text, count=1)
    if not text:
        return None
    m = TavernMessage(user_id=user.id, author_id=me.id, content=text)
    db.add(m)
    db.commit()
    return m


def run_round(user_id: str, turns: int, topic: str = "", seed: int | None = None) -> None:
    with _LOCK:
        if user_id in _BUSY:
            return
        _BUSY.add(user_id)
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        chars = cast(db, user)
        rng = random.Random(seed)
        said: list[TavernMessage] = []
        for i in range(turns):
            m = speak(db, user, chars, rng, topic if i == 0 else "")
            if m is None:
                break
            said.append(m)
        _reflect(db, chars, said)
        events.record("tavern", "round", user_id=user_id, payload={"turns": len(said), "topic": bool(topic)})
    except Exception:  # noqa: BLE001  后台任务不能把服务带崩
        log.exception("酒馆一轮失败")
    finally:
        db.close()
        with _LOCK:
            _BUSY.discard(user_id)


def _reflect(db: Session, chars: list[Character], said: list[TavernMessage]) -> None:
    """聊完：挨着说话最多的那对室友，各自更新对对方的印象（最多一对，省积分）。"""
    if len(said) < 4:
        return
    pairs: dict[tuple[str, str], int] = {}
    for a, b in zip(said, said[1:]):
        if a.author_id and b.author_id and a.author_id != b.author_id:
            k = tuple(sorted((a.author_id, b.author_id)))
            pairs[k] = pairs.get(k, 0) + 1
    if not pairs:
        return
    x, y = max(pairs, key=pairs.get)
    by = {c.id: c for c in chars}
    chat = [m for m in said if m.author_id in (x, y)]
    from .models import CharMessage  # 印象函数按私信的形状读：作者 + 内容
    rows = [CharMessage(author_id=m.author_id, content=m.content) for m in chat]
    update_impression(db, by[x], by[y], rows)
    update_impression(db, by[y], by[x], rows)


# ---------- 接口 ----------

def _out(m: TavernMessage) -> dict:
    return {"id": m.id, "author_id": m.author_id, "content": m.content, "created_at": m.created_at.isoformat()}


@router.get("")
def room(after: int = 0, user: User = Depends(current_user), db: Session = Depends(get_db)):
    house_friends(db, user)
    q = select(TavernMessage).where(TavernMessage.user_id == user.id)
    if after:
        rows = list(db.scalars(q.where(TavernMessage.id > after).order_by(TavernMessage.id).limit(100)))
    else:
        rows = list(db.scalars(q.order_by(TavernMessage.id.desc()).limit(60)))[::-1]
    return {"cast": [card(c) for c in cast(db, user)], "busy": user.id in _BUSY, "messages": [_out(m) for m in rows]}


class GoIn(BaseModel):
    topic: str = Field(default="", max_length=80)


def _start(db: Session, user: User, turns: int, topic: str = "") -> dict:
    credits.check(db, user)
    if len(cast(db, user)) < 2:
        raise HTTPException(400, "酒馆至少要两个角色：先去工作台新建一个")
    if user.id in _BUSY:
        raise HTTPException(409, "ta 们正在聊")
    threading.Thread(target=run_round, args=(user.id, turns, topic.strip()), name="tavern", daemon=True).start()
    return {"ok": True, "busy": True}


@router.post("/go")
def go(body: GoIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """让她们聊一会儿（可以给个话题）。"""
    return _start(db, user, ROUND_TURNS, body.topic)


class SayIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)


@router.post("/say")
def say(body: SayIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """主人插一句，几个角色接话。"""
    if user.id in _BUSY:
        raise HTTPException(409, "ta 们正在聊")
    m = TavernMessage(user_id=user.id, author_id=None, content=body.text.strip())
    db.add(m)
    db.commit()
    out = _start(db, user, REPLY_TURNS)
    return {**out, "message": _out(m)}


@router.delete("")
def clear(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """清空酒馆的聊天记录（印象不受影响）。"""
    if user.id in _BUSY:
        raise HTTPException(409, "ta 们正在聊")
    db.execute(delete(TavernMessage).where(TavernMessage.user_id == user.id))
    db.commit()
    return {"ok": True}
