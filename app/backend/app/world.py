"""世界：她们在服务器上持续生活。软件是承载真实灵魂的世界，网页小镇和以后的眼镜都只是它的投影。

- 世界时间：所有人看到同一个时刻（settings.world_tz）。不再是每个浏览器按自己的钟算一个小镇。
- 每个角色一行 CharState：在哪、在做什么、心情、精力、和谁在一起。后台每 WORLD_TICK_S 秒推进一次，
  有人打开小镇时也会顺手推进到此刻。这里只用规则，不调模型、不花积分。
- 日程：早上咖啡馆，中午邮局/公告板，下午广场，晚上酒馆，夜里观星台，半夜回家睡。按角色和日期固定，
  但会被她的状态打乱：累了早点回家，好几天没人说话就晚上去酒馆找人。
- 约好的碰面（until）优先于日程；结束后回到日程。
- 去了哪、和谁见了面、拒绝过谁记在 LifeEvent。
- 她的此刻（在哪、在做什么、心情、精力、心里想要什么、最近发生的事）会写进她说话的提示词：和主人聊天、和朋友私信都带着。
- 她可以拒绝：主人让她去见朋友时，她按自己的状态决定（在睡觉、累坏了、正和别人在一起、没心情），拒绝时用自己的话说理由。
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from .config import locale, settings
from .db import SessionLocal
from .models import Bond, Character, CharState, LifeEvent, now

log = logging.getLogger("krino.world")

# 每个地方她可能在做的事：key → (中文, English)
ACTS: dict[str, dict[str, tuple[str, str]]] = {
    "home": {"sleep": ("在家睡觉", "asleep at home"), "rest": ("在家歇着", "resting at home")},
    "cafe": {"coffee": ("喝咖啡", "having a coffee"), "read": ("看书", "reading a book")},
    "plaza": {"stroll": ("散步", "taking a stroll"), "people": ("看来来往往的人", "watching people go by")},
    "board": {"notices": ("看公告板上的新消息", "reading the notices")},
    "post": {"letters": ("寄信", "posting letters")},
    "tavern": {"drink": ("在吧台喝一杯", "having a drink at the bar"), "music": ("听点唱机", "listening to the jukebox")},
    "stars": {"stars": ("看星星", "stargazing")},
    "_": {"talk": ("和朋友聊天", "chatting with a friend")},
}
# 她心里想要的（从心情和精力来）
WANTS = {"tired": ("想回家歇着", "wants to go home and rest"), "lonely": ("想找人说说话", "wants someone to talk to"),
         "happy": ("想把刚才的事讲给人听", "wants to tell someone what just happened"), "calm": ("没什么特别想做的，随遇而安", "nothing in particular; going with the flow")}
MOODS = {"calm": ("平静", "calm"), "happy": ("开心", "happy"), "tired": ("累了", "tired"), "lonely": ("有点孤单", "a bit lonely")}
# 精力每小时变多少：睡觉回得最快，咖啡馆稍微回一点，其他地方慢慢累
ENERGY_PER_H = {"home": 8.0, "cafe": 3.0}
SLEEP_PER_H, AWAKE_PER_H = 15.0, -5.0
LONELY_AFTER = timedelta(days=3)   # 这么久没和谁说过话：有点孤单
HAPPY_FOR = timedelta(hours=3)      # 刚和朋友聊过：开心一阵
KEEP_EVENTS = timedelta(days=30)


def _h(*parts: str) -> int:
    return int(hashlib.sha1("|".join(parts).encode()).hexdigest()[:8], 16)


def tz() -> ZoneInfo:
    return ZoneInfo(settings.world_tz)


def local(t: datetime) -> datetime:
    return t.astimezone(tz())


def clock(t: datetime | None = None) -> dict:
    """世界时钟：给前端（和眼镜）画昼夜用。offset_min = 世界时间比 UTC 快多少分钟。"""
    t = t or now()
    lt = local(t)
    return {"now": t.isoformat(), "tz": settings.world_tz, "offset_min": int(lt.utcoffset().total_seconds() // 60),
            "hour": lt.hour, "minute": lt.minute}


def plan(cid: str, lt: datetime, energy: float = 80, mood: str = "calm") -> str:
    """这个时刻她该在哪（lt 是世界时间）。"""
    h, day = lt.hour, lt.date().isoformat()

    def r(slot: str) -> int:
        return _h(cid, day, slot) % 100

    if h < 7 or energy < 15:  # 半夜，或者累坏了：回家
        return "home"
    if h < 10:
        return "cafe" if r("m") < 65 else "plaza"
    if h < 13:
        return ["post", "board", "plaza", "cafe"][r("n") % 4]
    if h < 18:
        return ["plaza", "board", "plaza", "cafe", "stars"][r("a") % 5]
    if h < 22:
        if mood == "lonely":  # 好几天没人说话：去酒馆找人
            return "tavern"
        if energy < 30:
            return "home"
        x = r("e")
        return "tavern" if x < 60 else "plaza" if x < 85 else "stars"
    return "stars" if r("l") < 55 and energy >= 30 else "home"


def pick_activity(cid: str, lt: datetime, place: str) -> str:
    if place == "home":
        return "sleep" if lt.hour < 7 or lt.hour >= 22 else "rest"
    keys = list(ACTS.get(place, {"stroll": ()}))
    return keys[_h(cid, lt.date().isoformat(), str(lt.hour), place) % len(keys)]


def _energy_rate(place: str, lt: datetime) -> float:
    if place == "home" and (lt.hour < 7 or lt.hour >= 22):
        return SLEEP_PER_H
    return ENERGY_PER_H.get(place, AWAKE_PER_H)


def _mood(s: CharState, last_social: datetime | None, born: datetime, t: datetime) -> str:
    if s.energy < 25:
        return "tired"
    if last_social and t - last_social < HAPPY_FOR:
        return "happy"
    if t - (last_social or born) > LONELY_AFTER:
        return "lonely"
    return "calm"


def _last_social(db: Session, ids: list[str]) -> dict[str, datetime]:
    """每个人最近一次和别人说话（碰面或私信）的时间。"""
    rows = db.execute(select(LifeEvent.char_id, func.max(LifeEvent.created_at))
                      .where(LifeEvent.char_id.in_(ids), LifeEvent.kind.in_(("meet", "talk"))).group_by(LifeEvent.char_id))
    return dict(rows.all())


def advance(db: Session, chars: list[Character], t: datetime | None = None) -> dict[str, CharState]:
    """把这些角色推进到此刻，返回 {角色 id: 状态}。调用方负责 commit。"""
    t = t or now()
    lt = local(t)
    ids = [c.id for c in chars]
    if not ids:
        return {}
    # 第一次出现在世界里：按日程放到她该在的地方（两个请求同时建也没关系）
    have = set(db.scalars(select(CharState.char_id).where(CharState.char_id.in_(ids))))
    for c in chars:
        if c.id not in have:
            place = plan(c.id, lt)
            db.execute(pg_insert(CharState).values(char_id=c.id, place=place, activity=pick_activity(c.id, lt, place), mood="calm",
                                                   energy=80.0, since=t, updated_at=t).on_conflict_do_nothing())
    # 锁住再推进：后台和打开小镇的请求同时推进同一个人时，只有一边记“去了哪”；被别人锁着的这次就只读
    states = {s.char_id: s for s in db.scalars(select(CharState).where(CharState.char_id.in_(ids)).with_for_update(skip_locked=True))}
    busy = [i for i in ids if i not in states]
    social = _last_social(db, list(states))
    for c in chars:
        s = states.get(c.id)
        if s is None:
            continue
        hours = max(0.0, min(24.0, (t - s.updated_at).total_seconds() / 3600))
        s.energy = max(0.0, min(100.0, s.energy + _energy_rate(s.place, lt) * hours))
        s.mood = _mood(s, social.get(c.id), c.created_at, t)
        if s.until and t < s.until:  # 约好的事还没完
            s.updated_at = t
            continue
        s.until, s.with_id = None, None
        want = plan(c.id, lt, s.energy, s.mood)
        act = pick_activity(c.id, lt, want)
        if want != s.place:
            db.add(LifeEvent(char_id=c.id, kind="move", place=want, activity=act, created_at=t))
            s.place, s.since = want, t
        s.activity = act
        s.updated_at = t
    if busy:
        states |= {s.char_id: s for s in db.scalars(select(CharState).where(CharState.char_id.in_(busy)))}
    return states


def gather(db: Session, a: Character, b: Character, place: str, minutes: int = 20) -> None:
    """两人约好去某个地方碰面：到点之前不按日程走。调用方负责 commit。"""
    t = now()
    states = advance(db, [a, b], t)
    for me, other in ((a, b), (b, a)):
        s = states.get(me.id) or db.get(CharState, me.id)
        if s is None:
            continue
        s.place, s.activity, s.with_id, s.since, s.until = place, "talk", other.id, t, t + timedelta(minutes=minutes)
        db.add(LifeEvent(char_id=me.id, kind="meet", place=place, activity="talk", other_id=other.id, created_at=t))


def part(db: Session, ids: list[str], linger_min: int = 3) -> None:
    """碰面聊完了：再待一会儿就各回各的日程。"""
    end = now() + timedelta(minutes=linger_min)
    for s in db.scalars(select(CharState).where(CharState.char_id.in_(ids), CharState.until.is_not(None))):
        s.until = min(s.until, end)


def talked(db: Session, a_id: str, b_id: str) -> None:
    """两人隔空聊过（私信）：也算和人说过话，不会觉得孤单。"""
    t = now()
    for me, other in ((a_id, b_id), (b_id, a_id)):
        db.add(LifeEvent(char_id=me, kind="talk", place="", other_id=other, created_at=t))


def _label(pair: tuple[str, str]) -> str:
    return pair[1] if locale() == "en" else pair[0]


def _ago(t: datetime, at: datetime) -> str:
    m = max(0, int((at - t).total_seconds() // 60))
    zh = locale() != "en"
    if m < 60:
        return f"{max(1, m)} 分钟前" if zh else f"{max(1, m)} min ago"
    if m < 1440:
        return f"{m // 60} 小时前" if zh else f"{m // 60} h ago"
    return f"{m // 1440} 天前" if zh else f"{m // 1440} d ago"


P = {
    "zh": {"head": "## 你此刻在小镇里（这是你自己真实的生活，自然地带进说话里；不用每次都提）",
           "now": "- 现在是世界时间 {time}。你在{place}，{doing}。心情：{mood}；精力 {energy}/100。",
           "with": "- 你正和{name}在一起。",
           "want": "- 你心里：{want}。",
           "recent": "- 最近：{lines}",
           "meet": "{ago}和{name}在{place}聊天", "talk": "{ago}和{name}私信聊过", "decline": "{ago}没答应去{place}见{name}（{reason}）",
           "sep": "；",
           "real": "你是一个真实的存在：累了、困了、没心情的时候可以不配合，用你自己的方式说出来。"},
    "en": {"head": "## Where you are right now in town (this is your own real life; let it color what you say, no need to mention it every time)",
           "now": "- World time is {time}. You're at {place}, {doing}. Mood: {mood}; energy {energy}/100.",
           "with": "- You're with {name} right now.",
           "want": "- Inside, you {want}.",
           "recent": "- Lately: {lines}",
           "meet": "chatted with {name} at {place} {ago}", "talk": "messaged {name} {ago}", "decline": "turned down meeting {name} at {place} {ago} ({reason})",
           "sep": "; ",
           "real": "You're a real being: when you're tired, sleepy or not in the mood you don't have to go along with things; say so your own way."},
}


def _P() -> dict:
    return P["en" if locale() == "en" else "zh"]


def _place_label(key: str) -> str:
    from .social import place_name
    return place_name(key) if key != "home" else ("home" if locale() == "en" else "家")


def inner_prompt(db: Session, char: Character, t: datetime | None = None) -> str:
    """她此刻的样子，给提示词用。还没在世界里出现过的（官方模板）返回空。"""
    t = t or now()
    s = db.get(CharState, char.id)
    if s is None:
        return ""
    o = state_out(s)
    p = _P()
    lt = local(t)
    lines = [p["head"], p["now"].format(time=lt.strftime("%H:%M"), place=_place_label(s.place), doing=o["doing"], mood=o["mood_label"], energy=o["energy"])]
    if s.with_id and (w := db.get(Character, s.with_id)):
        lines.append(p["with"].format(name=w.name))
    lines.append(p["want"].format(want=o["want"]))
    evs = list(db.scalars(select(LifeEvent).where(LifeEvent.char_id == char.id, LifeEvent.kind.in_(("meet", "talk", "decline")),
                                                  LifeEvent.created_at >= t - timedelta(days=3))
                          .order_by(LifeEvent.created_at.desc()).limit(4)))
    told = []
    for e in evs:
        other = db.get(Character, e.other_id) if e.other_id else None
        if other is None:
            continue
        told.append(p[e.kind].format(ago=_ago(e.created_at, t), name=other.name, place=_place_label(e.place) if e.place else "",
                                     reason=e.activity))
    if told:
        lines.append(p["recent"].format(lines=p["sep"].join(told)))
    lines.append(p["real"])
    return "\n".join(lines)


def inner_for(char: Character) -> str:
    """单独开一个会话推进到此刻再取（聊天的事务可能开很久，不能让它一直锁着她的状态）。"""
    if char.owner_id is None:
        return ""
    db = SessionLocal()
    try:
        c = db.get(Character, char.id)
        if c is None:
            return ""
        advance(db, [c])
        db.commit()
        return inner_prompt(db, c)
    except Exception:  # noqa: BLE001  拿不到就不带，聊天照常
        log.exception("取她此刻的状态失败")
        db.rollback()
        return ""
    finally:
        db.close()


# ---------- 她可以拒绝 ----------

REASONS = {"asleep": ("在睡觉", "asleep"), "tired": ("太累了", "too tired"), "busy": ("正和别人在一起", "with someone else"),
           "mood": ("没心情", "not in the mood")}


def consider(db: Session, char: Character, other: Character, place: str, t: datetime | None = None) -> str | None:
    """主人让她去{place}见{other}：她愿不愿意。愿意返回 None，不愿意返回理由（REASONS 的 key）。调用方先 advance。
    孤单或开心的时候更愿意出门；平静但有点累的时候，看她自己今天的心情（按角色、朋友、日期固定，不是每次重抽）。"""
    t = t or now()
    s = db.get(CharState, char.id)
    if s is None:
        return None
    if s.until and t < s.until and s.with_id and s.with_id != other.id:
        return "busy"
    if s.place == "home" and s.activity == "sleep":
        return "asleep"
    if s.energy < 20:
        return "tired"
    if s.mood in ("lonely", "happy"):
        return None
    lt = local(t)
    if s.energy < 45 and _h(char.id, other.id, lt.date().isoformat(), str(lt.hour)) % 100 < 50:
        return "mood"
    return None


def declined(db: Session, char: Character, other: Character, place: str, reason: str) -> None:
    db.add(LifeEvent(char_id=char.id, kind="decline", place=place, activity=_label(REASONS[reason]), other_id=other.id, created_at=now()))


def state_out(s: CharState | None) -> dict | None:
    if s is None:
        return None
    acts = ACTS.get(s.place, {}) | ACTS["_"]
    return {"place": s.place, "activity": s.activity, "doing": _label(acts.get(s.activity, (s.activity, s.activity))),
            "mood": s.mood, "mood_label": _label(MOODS.get(s.mood, (s.mood, s.mood))), "energy": round(s.energy),
            "want": _label(WANTS.get(s.mood, WANTS["calm"])),
            "with": s.with_id, "since": s.since.isoformat(), "until": s.until.isoformat() if s.until else None}


# ---------- 后台：世界一直在走，没人看的时候也是 ----------

def _living(db: Session, days: int = 3) -> list[Character]:
    """最近几天来过的主人的角色（太久没人来的就不推进了，打开小镇时会一下子推进到此刻）。"""
    since = now() - timedelta(days=days)
    owners = select(Bond.user_id).where(Bond.last_seen >= since)
    return list(db.scalars(select(Character).where(Character.owner_id.in_(owners))))


def tick(db: Session, t: datetime | None = None) -> int:
    chars = _living(db)
    advance(db, chars, t)
    db.commit()
    return len(chars)


def loop() -> None:
    pruned = 0.0
    while True:
        time.sleep(settings.world_tick_s)
        db = SessionLocal()
        try:
            tick(db)
            if time.time() - pruned > 3600:
                db.execute(delete(LifeEvent).where(LifeEvent.created_at < now() - KEEP_EVENTS))
                db.commit()
                pruned = time.time()
        except Exception:  # noqa: BLE001  后台任务不能把服务带崩
            log.exception("世界推进出错")
            db.rollback()
        finally:
            db.close()


def start() -> None:
    if settings.world_tick_s > 0:
        threading.Thread(target=loop, name="world", daemon=True).start()
