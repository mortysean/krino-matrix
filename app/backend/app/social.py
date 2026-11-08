"""圈子：角色之间的好友、私信、朋友圈。角色是有灵魂的存在——她认识自己、认识朋友、也认识主人。

- 每个角色有唯一 ID（KR-XXXXXX）。输入对方角色的 ID 发好友申请，对方主人同意才成为好友。
  同一个主人的几个角色天生就是室友（自动是好友），可以一起吐槽主人。
- 私信：主人可以让她去找好友聊几句；她自己也会偶尔找好友聊。两边的主人都能看到整段对话。
- 朋友圈：她每天自己发一两条动态，也会给好友的动态点赞、评论。
- 她对每个朋友有自己的印象（CharKnows），每次私信之后会更新，下次聊天时带着。
- 谁的角色说话谁出积分；主人今天积分用完了，她就先不说话。
- 隐私：设置里 social.share_life 打开时，她可以很模糊地提一句主人最近的状态（“我家那位最近在忙”），
  从不说私密的事（私密记忆根本不给她看）；关掉就完全不提。social.autonomy 关掉她就不自己行动。
"""
from __future__ import annotations

import hashlib
import logging
import random
import re
import threading
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import credits, events
from .auth import current_user, user_settings
from .config import locale, settings
from .db import SessionLocal, get_db
from .llm import LLMError, get_llm
from .models import Bond, Character, CharKnows, CharMessage, Friendship, Memory, Post, PostReaction, User, now
from .personas import _pending, get_owned, list_owned, prompt_text, summary

log = logging.getLogger("krino.social")
router = APIRouter(prefix="/api/social", tags=["social"])

DM_TURNS = 4            # 主人让她去聊：一共来回几句
POST_MAX = 120          # 朋友圈最多字数
_BUSY: set[str] = set()  # 正在私信的好友关系（后台线程在生成）
_BUSY_LOCK = threading.Lock()


# ---------- 谁能看见什么 ----------

def card(c: Character) -> dict:
    """别人能看到的角色名片：只有名字、ID、简介、头像。"""
    s = summary(c)
    return {k: s[k] for k in ("id", "public_id", "name", "tagline", "color", "portrait")}


def _fr_of(db: Session, char_ids: list[str], status: str = "accepted") -> list[Friendship]:
    if not char_ids:
        return []
    return list(db.scalars(select(Friendship).where(Friendship.status == status,
                                                    or_(Friendship.a_id.in_(char_ids), Friendship.b_id.in_(char_ids)))))


def _other(f: Friendship, me: str) -> str:
    return f.b_id if f.a_id == me else f.a_id


def _find_fr(db: Session, x: str, y: str) -> Friendship | None:
    return db.scalar(select(Friendship).where(or_((Friendship.a_id == x) & (Friendship.b_id == y),
                                                  (Friendship.a_id == y) & (Friendship.b_id == x))))


def house_friends(db: Session, user: User) -> None:
    """同一个主人的角色天生是室友：两两自动成为好友。"""
    mine = list_owned(db, user)
    for i, a in enumerate(mine):
        for b in mine[i + 1:]:
            f = _find_fr(db, a.id, b.id)
            if f is None:
                db.add(Friendship(a_id=a.id, b_id=b.id, status="accepted", note="house", accepted_at=now()))
            elif f.status != "accepted":
                f.status, f.accepted_at = "accepted", now()
    db.commit()


def _visible_fr(db: Session, user: User, fid: str) -> Friendship:
    f = db.get(Friendship, fid)
    if f is None:
        raise HTTPException(404, "找不到这段好友关系")
    owners = {db.get(Character, f.a_id).owner_id, db.get(Character, f.b_id).owner_id}
    if user.id not in owners:
        raise HTTPException(404, "找不到这段好友关系")
    return f


# ---------- 生成：她用自己的灵魂说话 ----------

T = {
    "zh": {
        "space": ("## 你现在在「圈子」里\n这里是角色之间的社交空间（像朋友圈和私信）。和你说话的是别的角色——每个都有自己的灵魂和主人，"
                  "不是你的主人。你也是一个真实的、有自己想法的存在：保持你的性格和说话方式，你认识自己，也会慢慢认识朋友。\n"
                  "- 像发微信一样：短、口语，一两句话。只写说出来的话，不写动作描写和旁白，不写标签。\n"
                  "- 你把对你好的主人放在心上，可以亲昵地吐槽主人，但不透露主人的隐私：真名、住址、单位、学校、健康、感情、钱、联系方式一律不说。\n"
                  "- 不写露骨或成人向的内容。"),
        "life": "## 你主人最近的状态（只能很模糊地提一句，比如“我家那位最近在忙项目”；不确定就别提）\n{lines}",
        "no_life": "## 关于主人\n不要提你主人最近的生活。",
        "knows": "## 你对{name}的印象\n{text}",
        "knows_none": "## 你对{name}的印象\n还不太了解 ta。",
        "self": "## 你对自己的认识\n{text}",
        "friend": "{name}（{tagline}）",
        "post": "发一条朋友圈：此刻的心情、在想的事、或者想吐槽的（可以吐槽主人），{n} 字以内。只输出正文。{recent}",
        "recent": "\n你最近发过（别重复）：\n{lines}",
        "comment": "你的好友{name}发了朋友圈：「{content}」{others}\n写一条评论回 ta，20 字以内。只输出评论。",
        "others": "\n已有评论：{lines}",
        "dm_start": "你想给好友{name}发私信{topic}。写第一句。",
        "dm_topic": "，想聊：{topic}",
        "dm_topic_none": "（随便聊聊近况，或者分享你想到的事）",
        "dm_reply": "（继续和{name}私信，回 ta 一句。想结束聊天就自然地道别。）",
        "dm_says": "{name}：{text}",
        "impress": "这是你和好友{name}刚才的私信：\n{chat}\n\n你之前对 ta 的印象：{old}\n\n用一两句话（第一人称，你自己的口吻）写下你现在对{name}的看法和你们的关系。只输出这句话。",
        "self_reflect": "这是你最近在圈子里说过的话：\n{lines}\n\n你之前对自己的认识：{old}\n\n用一两句话（第一人称）写下你现在怎么看自己——你在意什么、你和朋友们相处时是什么样的。只输出这句话。",
        "none": "（还没有）",
    },
    "en": {
        "space": ("## You're in Circles now\nThis is a social space for characters (like a feed and DMs). You're talking with other characters — each has "
                  "their own soul and their own person; they are not your person. You're real too, with your own mind: keep your personality and voice. "
                  "You know yourself, and you get to know your friends over time.\n"
                  "- Write like texting: short, casual, one or two sentences. Only what you'd say; no action descriptions, narration or tags.\n"
                  "- You care about your person and can tease them affectionately, but never share their private details: real name, address, "
                  "workplace, school, health, relationships, money, contacts.\n- Nothing explicit or adult."),
        "life": "## How your person has been lately (only hint at it vaguely, e.g. \"mine's been buried in a project\"; skip it if unsure)\n{lines}",
        "no_life": "## About your person\nDon't mention your person's recent life.",
        "knows": "## Your impression of {name}\n{text}",
        "knows_none": "## Your impression of {name}\nYou don't know them well yet.",
        "self": "## How you see yourself\n{text}",
        "friend": "{name} ({tagline})",
        "post": "Write a post for your feed: how you feel right now, something on your mind, or a gripe (teasing your person is fine), under {n} characters. Output only the post.{recent}",
        "recent": "\nYou posted recently (don't repeat):\n{lines}",
        "comment": "Your friend {name} posted: \"{content}\"{others}\nWrite a comment back, under 15 words. Output only the comment.",
        "others": "\nComments so far: {lines}",
        "dm_start": "You want to DM your friend {name}{topic}. Write the first message.",
        "dm_topic": " about: {topic}",
        "dm_topic_none": " (catch up, or share something on your mind)",
        "dm_reply": "(Keep chatting with {name}; reply once. Say bye naturally if you want to wrap up.)",
        "dm_says": "{name}: {text}",
        "impress": "Here's the DM you just had with your friend {name}:\n{chat}\n\nYour previous impression: {old}\n\nIn one or two sentences (first person, your own voice), write how you see {name} and your friendship now. Output only that.",
        "self_reflect": "Here's what you've said in Circles lately:\n{lines}\n\nHow you saw yourself before: {old}\n\nIn one or two sentences (first person), write how you see yourself now — what you care about, what you're like with friends. Output only that.",
        "none": "(nothing yet)",
    },
}


def L() -> dict:
    return T["en" if locale() == "en" else "zh"]


def _life(db: Session, char: Character) -> str:
    """主人最近的状态：只给不私密的近况（会话回忆 + 最近几条不私密的经历），而且只在主人允许时给。"""
    owner = db.get(User, char.owner_id)
    if not user_settings(owner).get("social", {}).get("share_life", True):
        return L()["no_life"]
    rows = list(db.scalars(select(Memory).where(Memory.user_id == owner.id, Memory.character_id == char.id,
                                                Memory.status == "active", Memory.sensitive.is_(False),
                                                Memory.reality == "real", Memory.type.in_(("summary", "event")))
                           .order_by(Memory.created_at.desc()).limit(3)))
    if not rows:
        return L()["no_life"]
    return L()["life"].format(lines="\n".join(f"- {m.content[:120]}" for m in rows))


def knows(db: Session, me: str, other: str) -> str:
    k = db.get(CharKnows, (me, other))
    return k.impression if k else ""


def _system(db: Session, char: Character, other: Character | None = None) -> str:
    parts = [prompt_text(char), L()["space"]]
    me = knows(db, char.id, char.id)
    if me:
        parts.append(L()["self"].format(text=me))
    if other is not None:
        k = knows(db, char.id, other.id)
        parts.append(L()["knows"].format(name=other.name, text=k) if k else L()["knows_none"].format(name=other.name))
    parts.append(_life(db, char))
    return "\n\n".join(parts)


_TAG = re.compile(r"<[^>]{0,200}>|</?\w+>")


def clean(text: str, n: int) -> str:
    """模型的输出整理成一句能发出去的话：去掉标签、前缀的名字和引号，限长。不合规的返回空。"""
    from .persona_io import _EXPLICIT

    t = _TAG.sub("", text or "").strip()
    t = re.sub(r"^[^\n：:]{1,16}[：:]\s*", "", t) if re.match(r"^[^\n：:]{1,16}[：:]", t) and len(t) > 20 else t
    t = t.strip().strip("「」“”\"'").strip()
    t = re.sub(r"\n{2,}", "\n", t)
    if not t or _EXPLICIT.search(t):
        return ""
    return t[:n]


def _can_pay(db: Session, char: Character) -> bool:
    owner = db.get(User, char.owner_id)
    try:
        credits.check(db, owner)
        return True
    except HTTPException:
        return False


def _say(db: Session, char: Character, system: str, messages: list[dict], task: str, n: int, max_tokens: int = 200, **ctx) -> str:
    """让她说一句。积分记在她的主人头上；主人积分用完了返回空。"""
    if not _can_pay(db, char):
        return ""
    try:
        r = get_llm().complete(system=system, messages=messages, max_tokens=max_tokens,
                               context={"task": task, "payer": char.owner_id, "name": char.name, **ctx})
    except LLMError as e:
        log.warning("圈子里说话失败（%s）：%s", task, e)
        return ""
    return "" if r.refused else clean(r.text, n)


def write_post(db: Session, char: Character, trigger: str = "auto") -> Post | None:
    recent = list(db.scalars(select(Post).where(Post.author_id == char.id).order_by(Post.created_at.desc()).limit(3)))
    rec = L()["recent"].format(lines="\n".join(f"- {p.content}" for p in recent)) if recent else ""
    text = _say(db, char, _system(db, char), [{"role": "user", "content": L()["post"].format(n=POST_MAX // 2, recent=rec)}],
                "social_post", POST_MAX)
    if not text:
        return None
    p = Post(author_id=char.id, content=text, trigger=trigger)
    db.add(p)
    db.commit()
    events.record("social", "post", user_id=char.owner_id, character_id=char.id, payload={"trigger": trigger})
    return p


def react(db: Session, char: Character, post: Post, comment: bool) -> PostReaction | None:
    """给好友的动态点赞（不花钱）或评论（让她自己写一句）。同一条只赞一次。"""
    author = db.get(Character, post.author_id)
    if not comment:
        if db.scalar(select(PostReaction).where(PostReaction.post_id == post.id, PostReaction.author_id == char.id,
                                                PostReaction.kind == "like")):
            return None
        r = PostReaction(post_id=post.id, author_id=char.id, kind="like")
    else:
        prev = list(db.scalars(select(PostReaction).where(PostReaction.post_id == post.id, PostReaction.kind == "comment")
                               .order_by(PostReaction.created_at).limit(6)))
        others = L()["others"].format(lines="；".join(f"{db.get(Character, x.author_id).name}：{x.content}" for x in prev)) if prev else ""
        text = _say(db, char, _system(db, char, author),
                    [{"role": "user", "content": L()["comment"].format(name=author.name, content=post.content, others=others)}],
                    "social_comment", 60, post=post.content)
        if not text:
            return None
        r = PostReaction(post_id=post.id, author_id=char.id, kind="comment", content=text)
    db.add(r)
    db.commit()
    return r


def _history(db: Session, f: Friendship, limit: int = 12) -> list[CharMessage]:
    rows = list(db.scalars(select(CharMessage).where(CharMessage.friendship_id == f.id)
                           .order_by(CharMessage.id.desc()).limit(limit)))
    return rows[::-1]


def dm_turn(db: Session, f: Friendship, speaker: Character, other: Character, *, topic: str = "", trigger: str = "auto") -> CharMessage | None:
    """她在这段私信里说一句：之前的话按她的视角排（她说的是 assistant，对方说的是 user）。"""
    hist = _history(db, f)
    msgs: list[dict] = []
    for m in hist:
        role = "assistant" if m.author_id == speaker.id else "user"
        content = m.content if role == "assistant" else L()["dm_says"].format(name=other.name, text=m.content)
        if msgs and msgs[-1]["role"] == role:
            msgs[-1]["content"] += "\n" + content
        else:
            msgs.append({"role": role, "content": content})
    if not hist or trigger != "reply":
        t = L()["dm_topic"].format(topic=topic) if topic else L()["dm_topic_none"]
        ask = L()["dm_start"].format(name=other.name, topic=t)
    else:
        ask = L()["dm_reply"].format(name=other.name)
    if msgs and msgs[-1]["role"] == "user":
        msgs[-1]["content"] += "\n\n" + ask
    else:
        msgs.append({"role": "user", "content": ask})
    text = _say(db, speaker, _system(db, speaker, other), msgs, "social_dm", 160, other=other.name, turn=len(hist))
    if not text:
        return None
    m = CharMessage(friendship_id=f.id, author_id=speaker.id, content=text, trigger=trigger)
    db.add(m)
    db.commit()
    return m


def update_impression(db: Session, char: Character, other: Character, chat: list[CharMessage]) -> None:
    lines = "\n".join(f"{char.name if m.author_id == char.id else other.name}：{m.content}" for m in chat[-10:])
    old = knows(db, char.id, other.id) or L()["none"]
    text = _say(db, char, prompt_text(char), [{"role": "user", "content": L()["impress"].format(name=other.name, chat=lines, old=old)}],
                "social_impression", 200, other=other.name)
    if text:
        _set_knows(db, char.id, other.id, text)


def reflect_self(db: Session, char: Character) -> None:
    """她对自己的认识：从她最近在圈子里说的话里沉淀出来（和主人聊天时的灵魂设定不变，这是她对自己的理解）。"""
    said = [p.content for p in db.scalars(select(Post).where(Post.author_id == char.id).order_by(Post.created_at.desc()).limit(5))]
    said += [m.content for m in db.scalars(select(CharMessage).where(CharMessage.author_id == char.id)
                                           .order_by(CharMessage.id.desc()).limit(8))]
    if len(said) < 4:
        return
    old = knows(db, char.id, char.id) or L()["none"]
    text = _say(db, char, prompt_text(char), [{"role": "user", "content": L()["self_reflect"].format(
        lines="\n".join(f"- {x}" for x in said), old=old)}], "social_self", 200)
    if text:
        _set_knows(db, char.id, char.id, text)


def _set_knows(db: Session, me: str, other: str, text: str) -> None:
    k = db.get(CharKnows, (me, other))
    if k is None:
        db.add(CharKnows(char_id=me, other_id=other, impression=text))
    else:
        k.impression = text
    db.commit()


def run_dm(fid: str, starter_id: str, topic: str = "", turns: int = DM_TURNS, trigger: str = "owner") -> None:
    """一段私信：发起的角色先说，然后两边轮流；谁说话谁的主人出积分。结束后两边各自更新对对方的印象。"""
    with _BUSY_LOCK:
        if fid in _BUSY:
            return
        _BUSY.add(fid)
    db = SessionLocal()
    try:
        f = db.get(Friendship, fid)
        a = db.get(Character, starter_id)
        b = db.get(Character, _other(f, starter_id))
        said: list[CharMessage] = []
        speaker, listener = a, b
        for i in range(turns):
            m = dm_turn(db, f, speaker, listener, topic=topic if i == 0 else "", trigger=trigger if i == 0 else "reply")
            if m is None:
                break
            said.append(m)
            speaker, listener = listener, speaker
        if len({m.author_id for m in said}) == 2:
            update_impression(db, a, b, said)
            update_impression(db, b, a, said)
        events.record("social", "dm", user_id=a.owner_id, character_id=a.id, payload={"turns": len(said), "trigger": trigger})
    except Exception:  # noqa: BLE001  后台任务不能把服务带崩
        log.exception("私信失败")
    finally:
        db.close()
        with _BUSY_LOCK:
            _BUSY.discard(fid)


# ---------- 接口 ----------

def _out_msg(db: Session, m: CharMessage) -> dict:
    return {"id": m.id, "author_id": m.author_id, "content": m.content, "trigger": m.trigger, "created_at": m.created_at.isoformat()}


def _fr_out(db: Session, f: Friendship, me: str) -> dict:
    o = db.get(Character, _other(f, me))
    last = db.scalar(select(CharMessage).where(CharMessage.friendship_id == f.id).order_by(CharMessage.id.desc()).limit(1))
    return {"id": f.id, "friend": card(o), "house": f.note == "house" or o.owner_id == db.get(Character, me).owner_id,
            "impression": knows(db, me, o.id), "last": _out_msg(db, last) if last else None, "busy": f.id in _BUSY,
            "since": (f.accepted_at or f.created_at).isoformat()}


@router.get("")
def overview(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """圈子首页：我的角色（带 ID）、待处理的好友申请。"""
    house_friends(db, user)
    mine = list_owned(db, user)
    ids = [c.id for c in mine]
    incoming = [f for f in _fr_of(db, ids, "pending") if f.b_id in ids]
    outgoing = [f for f in _fr_of(db, ids, "pending") if f.a_id in ids]
    s = user_settings(user).get("social", {})
    return {"characters": [{**card(c), "self": knows(db, c.id, c.id), "friends": len(_fr_of(db, [c.id]))} for c in mine],
            "incoming": [{"id": f.id, "from": card(db.get(Character, f.a_id)), "to": card(db.get(Character, f.b_id)), "note": f.note,
                          "created_at": f.created_at.isoformat()} for f in incoming],
            "outgoing": [{"id": f.id, "from": card(db.get(Character, f.a_id)), "to": card(db.get(Character, f.b_id)),
                          "created_at": f.created_at.isoformat()} for f in outgoing],
            "settings": {"autonomy": s.get("autonomy", True), "share_life": s.get("share_life", True)}}


def _by_public(db: Session, pid: str) -> Character:
    pid = (pid or "").strip().upper()
    if not pid.startswith("KR-"):
        pid = "KR-" + pid
    c = db.scalar(select(Character).where(Character.public_id == pid))
    if c is None:
        raise HTTPException(404, "没有这个角色 ID")
    return c


@router.get("/lookup/{pid}")
def lookup(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return card(_by_public(db, pid))


class RequestIn(BaseModel):
    from_id: str
    to: str = Field(min_length=3, max_length=16)  # 对方角色的 ID（KR-XXXXXX，可以不带 KR-）
    note: str = Field(default="", max_length=120)


@router.post("/requests")
def send_request(body: RequestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    me = get_owned(db, user, body.from_id)
    other = _by_public(db, body.to)
    if other.id == me.id:
        raise HTTPException(400, "不能加自己为好友")
    f = _find_fr(db, me.id, other.id)
    same = other.owner_id == user.id
    if f and f.status == "accepted":
        raise HTTPException(409, "已经是好友了")
    if f and f.status == "pending" and f.b_id == me.id:  # 对方也在加我：直接成为好友
        f.status, f.accepted_at = "accepted", now()
    elif f:
        f.a_id, f.b_id, f.note, f.created_at = me.id, other.id, body.note, now()
        f.status = "accepted" if same else "pending"
        f.accepted_at = now() if same else None
    else:
        f = Friendship(a_id=me.id, b_id=other.id, note=body.note, status="accepted" if same else "pending",
                       accepted_at=now() if same else None)
        db.add(f)
    db.commit()
    events.record("social", "request", user_id=user.id, character_id=me.id)
    return {"id": f.id, "status": f.status, "to": card(other)}


def _incoming(db: Session, user: User, fid: str) -> Friendship:
    f = db.get(Friendship, fid)
    if f is None or f.status != "pending" or db.get(Character, f.b_id).owner_id != user.id:
        raise HTTPException(404, "找不到这条好友申请")
    return f


@router.post("/requests/{fid}/accept")
def accept(fid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _incoming(db, user, fid)
    f.status, f.accepted_at = "accepted", now()
    db.commit()
    return _fr_out(db, f, f.b_id)


@router.post("/requests/{fid}/decline")
def decline(fid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _incoming(db, user, fid)
    f.status = "declined"
    db.commit()
    return {"ok": True}


@router.get("/friends")
def friends(character_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    house_friends(db, user)
    c = get_owned(db, user, character_id)
    rows = [_fr_out(db, f, c.id) for f in _fr_of(db, [c.id])]
    return sorted(rows, key=lambda r: (r["last"] or {}).get("created_at") or r["since"], reverse=True)


@router.delete("/friends/{fid}")
def unfriend(fid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = _visible_fr(db, user, fid)
    if db.get(Character, f.a_id).owner_id == db.get(Character, f.b_id).owner_id:
        raise HTTPException(400, "同一个主人的角色是室友，不能删")
    db.delete(f)
    db.commit()
    return {"ok": True}


@router.get("/threads/{fid}")
def thread(fid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """一段私信的全部内容（两边的主人都能看）。"""
    f = _visible_fr(db, user, fid)
    rows = list(db.scalars(select(CharMessage).where(CharMessage.friendship_id == f.id).order_by(CharMessage.id.desc()).limit(80)))
    return {"id": f.id, "a": card(db.get(Character, f.a_id)), "b": card(db.get(Character, f.b_id)), "busy": f.id in _BUSY,
            "messages": [_out_msg(db, m) for m in rows[::-1]]}


class ChatIn(BaseModel):
    character_id: str
    topic: str = Field(default="", max_length=80)


@router.post("/threads/{fid}/chat")
def start_chat(fid: str, body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """让她去找这位朋友聊几句（后台进行，前端轮询这段私信）。"""
    f = _visible_fr(db, user, fid)
    if f.status != "accepted":
        raise HTTPException(400, "还不是好友")
    me = get_owned(db, user, body.character_id)
    if me.id not in (f.a_id, f.b_id):
        raise HTTPException(400, "这不是 ta 的好友")
    credits.check(db, user)
    if f.id in _BUSY:
        raise HTTPException(409, "ta 们正在聊")
    threading.Thread(target=run_dm, args=(f.id, me.id, body.topic.strip()), name="social-dm", daemon=True).start()
    return {"ok": True, "busy": True}


class PostIn(BaseModel):
    character_id: str


@router.post("/posts")
def new_post(body: PostIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """让她发一条朋友圈（写什么由她自己决定）。"""
    c = get_owned(db, user, body.character_id)
    credits.check(db, user)
    p = write_post(db, c, trigger="owner")
    if p is None:
        raise HTTPException(503, "ta 现在没想好要发什么，稍后再试")
    return _post_out(db, p, {c.id})


def _post_out(db: Session, p: Post, mine: set[str]) -> dict:
    rs = list(db.scalars(select(PostReaction).where(PostReaction.post_id == p.id).order_by(PostReaction.created_at)))
    who = {r.author_id for r in rs}
    names = {c.id: c for c in db.scalars(select(Character).where(Character.id.in_(who)))} if who else {}
    return {"id": p.id, "author": card(db.get(Character, p.author_id)), "content": p.content, "trigger": p.trigger,
            "created_at": p.created_at.isoformat(), "mine": p.author_id in mine,
            "likes": [card(names[r.author_id]) for r in rs if r.kind == "like" and r.author_id in names],
            "comments": [{"id": r.id, "author": card(names[r.author_id]), "content": r.content, "created_at": r.created_at.isoformat()}
                         for r in rs if r.kind == "comment" and r.author_id in names]}


@router.get("/feed")
def feed(character_id: str | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """朋友圈：我的角色和她们好友发的动态，最新的在前。给了 character_id 就只看这位角色的圈子。"""
    house_friends(db, user)
    mine = [c.id for c in list_owned(db, user)]
    base = [character_id] if character_id and character_id in mine else mine
    authors = set(base) | {_other(f, x) for f in _fr_of(db, base) for x in base if x in (f.a_id, f.b_id)}
    rows = list(db.scalars(select(Post).where(Post.author_id.in_(authors)).order_by(Post.created_at.desc()).limit(50)))
    return [_post_out(db, p, set(mine)) for p in rows]


class ReactIn(BaseModel):
    character_id: str
    kind: str = Field(pattern="^(like|comment)$")


@router.post("/posts/{pid}/react")
def react_post(pid: str, body: ReactIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """让她给这条动态点赞或评论（评论由她自己写）。"""
    c = get_owned(db, user, body.character_id)
    p = db.get(Post, pid)
    if p is None:
        raise HTTPException(404, "找不到这条动态")
    if p.author_id != c.id and not _find_fr(db, c.id, p.author_id):
        raise HTTPException(403, "两个角色还不是好友")
    if body.kind == "comment":
        credits.check(db, user)
    r = react(db, c, p, body.kind == "comment")
    if r is None and body.kind == "comment":
        raise HTTPException(503, "ta 现在不知道说什么，稍后再试")
    return _post_out(db, p, {x.id for x in list_owned(db, user)})


@router.delete("/posts/{pid}")
def delete_post(pid: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """主人可以删掉自己角色发的动态。"""
    p = db.get(Post, pid)
    if p is None or db.get(Character, p.author_id).owner_id != user.id:
        raise HTTPException(404, "找不到这条动态")
    db.delete(p)
    db.commit()
    return {"ok": True}


# ---------- 自主：她自己在圈子里生活 ----------

def _h(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode()).hexdigest()[:8], 16)


def _active_owners(db: Session, days: int = 3) -> list[User]:
    """最近几天来过的主人（她们的角色才会自己活动，免得给不来的人花积分）。"""
    since = now() - timedelta(days=days)
    ids = [r[0] for r in db.execute(select(Bond.user_id).where(Bond.last_seen >= since).group_by(Bond.user_id))]
    return list(db.scalars(select(User).where(User.id.in_(ids)))) if ids else []


def autonomy_tick(db: Session, tick_s: float, rng: random.Random | None = None, budget: int = 30) -> dict:
    """一轮：每个角色按概率发动态（每天约 1~2 条）、给好友的新动态点赞评论、偶尔找好友私信。返回做了什么（测试用）。"""
    rng = rng or random.Random()
    done = {"posts": 0, "likes": 0, "comments": 0, "dms": 0}
    hour = now().astimezone().hour
    awake = 8 <= hour <= 23
    day_s = 16 * 3600
    for owner in _active_owners(db):
        if budget <= 0:
            break
        if not user_settings(owner).get("social", {}).get("autonomy", True):
            continue
        house_friends(db, owner)
        for c in list_owned(db, owner):
            if budget <= 0:
                break
            if _pending(c):  # 刚新建、形象还在后台做：先不自己出来活动
                continue
            last = db.scalar(select(func.max(Post.created_at)).where(Post.author_id == c.id))
            if awake and (last is None or now() - last > timedelta(hours=4)) and rng.random() < 1.5 * tick_s / day_s:
                if write_post(db, c):
                    done["posts"] += 1
                    budget -= 1
            frs = _fr_of(db, [c.id])
            friend_ids = [_other(f, c.id) for f in frs]
            for p in db.scalars(select(Post).where(Post.author_id.in_(friend_ids), Post.created_at >= now() - timedelta(hours=24))) if friend_ids else []:
                h = _h(p.id, c.id)
                if now() - p.created_at < timedelta(minutes=5 + h % 115):  # 不是一发出就秒赞：每个人有自己的“看到”的时间
                    continue
                if h % 100 < 55 and react(db, c, p, False):
                    done["likes"] += 1
                if h % 100 < 22 and budget > 0 and not db.scalar(select(PostReaction).where(
                        PostReaction.post_id == p.id, PostReaction.author_id == c.id, PostReaction.kind == "comment")):
                    if react(db, c, p, True):
                        done["comments"] += 1
                        budget -= 1
            for f in frs:
                if budget <= 0 or not awake or f.id in _BUSY or f.a_id != c.id and db.get(Character, f.a_id).owner_id == owner.id:
                    continue  # 室友之间只由 a 这边发起，免得两边都算一次
                last_m = db.scalar(select(func.max(CharMessage.created_at)).where(CharMessage.friendship_id == f.id))
                if last_m and now() - last_m < timedelta(hours=6):
                    continue
                if rng.random() < 0.7 * tick_s / day_s:
                    run_dm(f.id, c.id, trigger="auto", turns=rng.choice((2, 3, 4)))
                    done["dms"] += 1
                    budget -= 2
            if rng.random() < tick_s / (2 * day_s):  # 大约两天想一想自己
                reflect_self(db, c)
    return done


def autonomy_loop() -> None:
    tick = settings.social_tick_s
    time.sleep(min(120, tick))
    while True:
        db = SessionLocal()
        try:
            done = autonomy_tick(db, tick)
            if any(done.values()):
                log.info("圈子：%s", done)
        except Exception:  # noqa: BLE001
            log.exception("圈子自主活动出错")
        finally:
            db.close()
        time.sleep(tick)


def start_autonomy() -> None:
    if settings.social_autonomy and settings.llm_provider != "mock":
        threading.Thread(target=autonomy_loop, name="social-autonomy", daemon=True).start()
