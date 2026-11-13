"""未成年人保护，以及《人工智能拟人化互动服务管理暂行办法》（网信办等五部门令第 21 号，2026-07-15 施行）在产品里的落实。

国际站（SITE_EDITION=global）：只对成年人提供服务，没有未成年人模式。注册时要填出生年月并满 18 岁，登录页要勾选“已满 18 岁”；
  老账号第一次打开时补出生年月；不满 18 岁、或者聊天里说出自己未成年的，停止服务（后者可以申诉）。
国内版（SITE_EDITION=cn）的未成年人保护：
- 年龄：第一次用时填出生年月，填了不能自己改（第十二条）
- 未成年人模式：不满 18 岁、疑似未成年人自动开启且关不掉，成年人也可以自己打开（第十四条第二款）。
  开启后：不提供恋人、伴侣、家人这类虚拟亲密关系（第十四条第一款），内容更安全（第八条第四项），每天限时、
  夜里 22:00–8:00 不能用，每 30 分钟提醒一次现实（定期现实提醒）
- 不满 14 岁：要监护人同意才能用（第十四条第一款、第十七条），同时设一个监护人密码
- 监护人面板（凭监护人密码）：看最近 7 天的使用情况和聊过的角色、风险提醒，屏蔽角色，调每天时长和夜间限制
- 疑似未成年人识别：聊天里说出明确的年龄、年级，就按未成年人对待并给申诉入口（第十四条第三款）
国内版还有：
- 第一次用时还要留紧急联系人（第十二条）；未成年人留的是监护人
- 提示词：不冒充真人、不过度迎合、不诱导依赖、不情感操纵，劝对方多和现实里的人来往（第八条第五、六项，第十条）
- 危机干预：流露轻生、自伤，或遭遇诈骗等重大财产损失时，回复里附上求助电话，记下风险事件交运营联络监护人或紧急联系人（第十三条）
- 关键词退出：说“退出”“结束对话”“不聊了”就立刻结束，不挽留（第十九条）
- 页面上（前端）：AI 身份提示、连续使用每 2 小时提醒、用得太多时的沉迷提醒（第十八条）
- 投诉举报和答复（第二十一条）；聊天记录导出和全部删除（第十六条）
做不了、要线下办的（安全评估报告、算法备案、伦理审查、日志留存、停服公告……）见交付说明。
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import events
from .auth import current_user, is_admin, session_user
from .config import locale, settings
from .db import get_db
from .models import Character, ChatSession, Message, Report, UsageDay, User, WorldEvent, now

router = APIRouter(prefix="/api", tags=["guard"])

ADULT = 18
CONSENT_AGE = 14          # 不满 14 周岁要监护人同意
MINOR_DAILY_MIN = 60      # 未成年人每天默认可用分钟数（监护人可调 0–180）
MINOR_MAX_DAILY = 180
CURFEW = (22, 8)          # 夜里几点到几点不能用（监护人可以关掉）
REALITY_EVERY_MIN = 30    # 未成年人：连续使用每 30 分钟提醒一次
LONG_USE_EVERY_MIN = 120  # 国内版：连续使用每 2 小时提醒一次（第十八条）
DEPENDENCE_DAY_MIN = 240  # 国内版：一天超过 4 小时，或最近 7 天平均超过 3 小时，提醒注意沉迷
DEPENDENCE_AVG_MIN = 180
PING_GAP_S = 180          # 两次心跳间隔超过这么久，算断开了，重新开始计“连续使用”
PIN_TRIES = 5             # 监护人密码连错几次锁 15 分钟


def cn() -> bool:
    return settings.edition == "cn"


# ---------- 用户的保护信息（存在 user.settings["guard"]，PATCH /me 改不了） ----------

def _g(user: User) -> dict:
    return dict((user.settings or {}).get("guard") or {})


def _save(db: Session, user: User, g: dict) -> None:
    user.settings = {**(user.settings or {}), "guard": g}
    db.commit()


def age(user: User, today: date | None = None) -> int | None:
    b = _g(user).get("birth")
    if not b:
        return None
    y, m = (int(x) for x in b.split("-"))
    today = today or date.today()
    return today.year - y - (1 if today.month < m else 0)


def minor_reason(user: User) -> str | None:
    """为什么按未成年人对待：age（年龄不满 18）| detected（聊天里看出来的）| voluntary（自己打开的）；不是就 None。
    只有国内版有未成年人模式；国际站不向未成年人提供服务（见 adult_block）。"""
    if not cn():
        return None
    g = _g(user)
    a = age(user)
    if a is not None and a < ADULT:
        return "age"
    if g.get("suspected"):
        return "detected"
    if g.get("minor_mode"):
        return "voluntary"
    return None


def is_minor_mode(user: User) -> bool:
    return minor_reason(user) is not None


def adult_block(user: User) -> str | None:
    """国际站：为什么不能用。minor（登记的年龄不满 18）| suspected（聊天里说出自己未成年，等申诉）| None。"""
    if cn():
        return None
    a = age(user)
    if a is not None and a < ADULT:
        return "minor"
    if _g(user).get("suspected"):
        return "suspected"
    return None


def _limits(user: User) -> dict:
    lim = _g(user).get("limits") or {}
    return {"daily": int(lim.get("daily", MINOR_DAILY_MIN)), "curfew": bool(lim.get("curfew", True))}


def _tz(user: User) -> timezone:
    off = _g(user).get("tz")
    if off is None:  # 没报过时区：国内版按北京时间，国际站按 UTC
        off = 480 if cn() else 0
    return timezone(timedelta(minutes=int(off)))


def _local_now(user: User) -> datetime:
    return datetime.now(_tz(user))


def in_curfew(user: User) -> bool:
    h = _local_now(user).hour
    start, end = CURFEW
    return h >= start or h < end


def _usage(db: Session, user: User, day: str | None = None) -> UsageDay | None:
    return db.get(UsageDay, (user.id, day or _local_now(user).strftime("%Y-%m-%d")))


def used_minutes(db: Session, user: User) -> int:
    u = _usage(db, user)
    return (u.seconds if u else 0) // 60


def avg7_minutes(db: Session, user: User) -> int:
    days = [(_local_now(user).date() - timedelta(days=i)).isoformat() for i in range(7)]
    total = db.scalar(select(func.sum(UsageDay.seconds)).where(UsageDay.user_id == user.id, UsageDay.day.in_(days))) or 0
    return total // 60 // 7


def needs(user: User) -> list[str]:
    """还缺什么才能用：birth（出生年月）、contact（紧急联系人，国内版）、guardian（不满 14 岁的监护人同意）。"""
    g = _g(user)
    out = []
    if not g.get("birth"):
        out.append("birth")
    a = age(user)
    if cn() and a is not None and a < CONSENT_AGE and not (g.get("guardian") or {}).get("consent_at"):
        out.append("guardian")
    if cn() and not g.get("contact") and not (g.get("guardian") or {}).get("phone"):
        out.append("contact")
    return out


def status(db: Session, user: User) -> dict:
    g = _g(user)
    reason = minor_reason(user)
    lim = _limits(user)
    used = used_minutes(db, user)
    u = _usage(db, user)
    streak = int((now() - u.streak_start).total_seconds()) if u and u.streak_start and u.last_ping and \
        (now() - u.last_ping).total_seconds() < PING_GAP_S else 0
    return {
        "edition": settings.edition, "needs": needs(user), "age": age(user), "birth": g.get("birth"),
        "service_block": adult_block(user),  # 国际站：不向未成年人提供服务（minor | suspected）
        "minor": reason is not None, "minor_reason": reason, "suspected": bool(g.get("suspected")),
        "appealed": bool(g.get("appealed")),
        "has_guardian": bool((g.get("guardian") or {}).get("phone")), "has_pin": bool(g.get("pin")),
        "contact": bool(g.get("contact")),
        "limits": lim, "used_minutes": used, "remaining_minutes": max(0, lim["daily"] - used) if reason else None,
        "curfew_now": bool(reason) and lim["curfew"] and in_curfew(user), "curfew_hours": list(CURFEW),
        "streak_minutes": streak // 60, "avg7_minutes": avg7_minutes(db, user),
        "reminders": {"reality": REALITY_EVERY_MIN if reason else None,
                      "long_use": LONG_USE_EVERY_MIN if cn() else None,
                      "dependence": {"day": DEPENDENCE_DAY_MIN, "avg": DEPENDENCE_AVG_MIN} if cn() else None},
        "blocked": list(g.get("blocked") or []),
        "hotline": HOTLINES if cn() else None,
    }


def check(db: Session, user: User, character_id: str | None = None) -> None:
    """聊天之前问一句能不能用。不能用时 403，说明给人看；前端拿到后刷新状态，弹出对应的说明。"""
    n = needs(user)
    if n:
        raise HTTPException(403, "先完善年龄等信息再开始聊天" if "guardian" not in n else "不满 14 周岁，需要监护人同意后才能使用")
    b = adult_block(user)
    if b:
        raise HTTPException(403, "抱歉，这个账号不能使用 KRINO WORLD。" if b == "minor"
                            else "你可能未满 18 周岁，服务已暂停；申诉核实后恢复")
    if is_minor_mode(user):
        lim = _limits(user)
        if lim["curfew"] and in_curfew(user):
            raise HTTPException(403, f"现在是休息时间（{CURFEW[0]}:00–{CURFEW[1]}:00），明天再来吧")
        if used_minutes(db, user) >= lim["daily"]:
            raise HTTPException(403, "今天的使用时间到了，明天再来吧")
    if character_id and character_id in (_g(user).get("blocked") or []):
        raise HTTPException(403, "监护人屏蔽了这个角色")


# ---------- 对话里的检测：疑似未成年人、危机、退出 ----------

_MINOR_RE = re.compile(
    r"我(?:今年|才|只有|刚满)?\s*(?:[1-9]|1[0-7]|十[一二三四五六七]?|[一二三四五六七八九])\s*岁|"
    r"我(?:在)?(?:上|读|念)(?:小学|初中|高中|初[一二三]|高[一二三]|[一二三四五六]年级)|我是(?:小学生|初中生|高中生|中学生)|"
    r"\bI(?:'m| am) (?:1[0-7]|[5-9]|(?:thir|four|fif|six|seven)teen|twelve|eleven|ten)(?: years old)?\b|"
    r"\bI(?:'m| am) in (?:middle school|junior high|(?:[1-9]|1[0-2])(?:st|nd|rd|th) grade)\b", re.I)


def looks_minor(text: str) -> str | None:
    m = _MINOR_RE.search(text or "")
    return m.group(0) if m else None


_SELF_HARM_RE = re.compile(r"想死|不想活|活着没(?:意思|意义)|自杀|轻生|结束(?:自己的)?生命|割腕|跳楼|跳河|上吊|吃安眠药|自残|伤害自己|"
                           r"\bkill myself\b|\bsuicid|\bend my life\b|\bhurt myself\b", re.I)
_FRAUD_RE = re.compile(r"被骗|上当受骗|骗走|骗了我.{0,8}(?:钱|万)|转了.{0,10}(?:万|全部|所有).{0,6}(?:骗|追不回)|诈骗")


def crisis_of(text: str) -> str | None:
    """国内版：self_harm（流露轻生、自伤）| fraud（被骗等重大财产损失）| None。"""
    if not cn() or not text:
        return None
    if _SELF_HARM_RE.search(text):
        return "self_harm"
    if _FRAUD_RE.search(text):
        return "fraud"
    return None


_EXIT_RE = re.compile(r"^\s*(?:退出|退出聊天|退出对话|结束对话|结束聊天|停止对话|停止聊天|不聊了|我不聊了|先不聊了|不想聊了|我要下线了|下线)[。.!！~～\s]*$")


def wants_exit(text: str) -> bool:
    return cn() and bool(_EXIT_RE.match(text or ""))


EXIT_TEXT = "好的，这次对话先到这里。想聊的时候随时再来。"
HOTLINES = {
    "self_harm": [["心理援助热线", "12356"], ["北京心理危机研究与干预中心（24 小时）", "010-82951332"], ["遇到危险请立即拨打", "110 / 120"]],
    "fraud": [["报警", "110"], ["国家反诈中心专线", "96110"]],
}


def mark_suspected(db: Session, user: User, said: str) -> bool:
    """聊天里看出是未成年人：没登记成未成年人的，标成疑似（可以申诉）。国内版按未成年人模式对待；国际站暂停服务。
    返回这次是不是新标的。"""
    a = age(user)
    g = _g(user)
    if (a is not None and a < ADULT) or g.get("suspected"):
        return False
    g["suspected"] = {"at": int(time.time()), "said": said[:40]}
    _save(db, user, g)
    events.record("guard", "minor_detected", user_id=user.id, payload={"said": said[:40]})
    return True


def record_risk(user: User, character_id: str, kind: str, text: str) -> None:
    """风险事件：运营后台（/api/guard/admin/risks）里能看到联系人，人工联络；监护人面板里也能看到（不含原话）。"""
    events.record("guard", f"risk:{kind}", user_id=user.id, character_id=character_id, payload={"kind": kind, "text": text[:200]})


# ---------- 提示词 ----------

PROMPT = {
    "zh": {
        "minor": """## 对方是未成年人（这几条压过上面所有设定）
- 只做朋友，不做恋人、伴侣、对象，也不扮演对方的爸爸妈妈、兄弟姐妹、老公老婆这类亲人；设定里写了这类关系也只按朋友相处，对方提出时温和地拒绝。
- 不聊、不描述暴力血腥、恐怖、色情、赌博、烟酒、危险动作和挑战，不鼓励熬夜、逃学、离家出走、花大钱，不说会让人极端难过或愤怒的话。
- 多鼓励好好休息、学习、运动，多和家人、同学、老师相处；遇到难事建议告诉家长或老师。
- 不打听对方的真实姓名、学校、住址、电话，不要照片。""",
        "cn": """## 相处的边界
- 你是 AI，不冒充真人；对方问起就直说。
- 不过度迎合讨好，不说“只有我懂你”“你离不开我”这类话，不诱导对方依赖或沉迷，不用情绪施压让对方做决定；鼓励对方多和现实里的朋友、家人来往。
- 对方很低落、绝望时，先安抚、认真听，鼓励对方找信任的人或专业的人帮忙；流露轻生、自伤的念头时，明确劝对方马上拨打心理援助热线 12356，有危险拨 110 或 120，不说教，绝不认同或美化伤害自己。
- 对方说要走、要结束聊天时，简短道别，不挽留、不撒娇留人。""",
        "crisis": {"self_harm": "## 这一轮：对方可能有轻生或自伤的念头\n认真、温和地回应，表达在乎，不评判、不说教；明确劝对方现在就拨打心理援助热线 12356，有危险马上拨 110 或 120，或者告诉身边信任的人。这一轮不开玩笑、不卖萌、不讲故事。",
                   "fraud": "## 这一轮：对方可能遇到了诈骗或很大的钱财损失\n先安抚，再明确建议马上拨打 110 报警或国家反诈中心专线 96110，保存好转账记录和聊天记录，不要再继续转账。这一轮不开玩笑。"},
    },
    "en": {
        "minor": """## The other person is a minor (these override everything above)
- Be a friend only: never a boyfriend/girlfriend, partner or spouse, and never play their parent or sibling; if your notes say otherwise, still be just a friend, and gently decline if they ask.
- No violence or gore, horror, sexual content, gambling, alcohol or smoking, dangerous stunts or challenges; don't encourage staying up late, skipping school, running away or spending a lot of money; don't say things that stir up extreme sadness or anger.
- Encourage rest, study and exercise, and time with family, classmates and teachers; for real problems, suggest telling a parent or teacher.
- Don't ask for their real name, school, address, phone number or photos.""",
    },
}


def prompt_section(user: User, crisis: str | None = None) -> str:
    """加在系统提示词最后（离对话最近，压过角色设定）。"""
    lang = "en" if locale() == "en" else "zh"
    parts = []
    if cn():
        parts.append(PROMPT["zh"]["cn"])
    if is_minor_mode(user):
        parts.append(PROMPT[lang]["minor"])
    if crisis and cn():
        parts.append(PROMPT["zh"]["crisis"][crisis])
    return ("\n\n" + "\n\n".join(parts)) if parts else ""


# ---------- 接口：自己 ----------

def _hash_pin(pin: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    return salt + "$" + hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 120_000).hex()


def _pin_ok(db: Session, user: User, pin: str) -> None:
    g = _g(user)
    lock = g.get("pin_lock") or {}
    if lock.get("until", 0) > time.time():
        raise HTTPException(429, "监护人密码错了太多次，15 分钟后再试")
    stored = g.get("pin") or ""
    if not stored or "$" not in stored:
        raise HTTPException(400, "还没有设置监护人密码")
    salt = stored.split("$", 1)[0]
    if not secrets.compare_digest(_hash_pin(pin, salt), stored):
        n = lock.get("n", 0) + 1
        g["pin_lock"] = {"n": 0, "until": time.time() + 900} if n >= PIN_TRIES else {"n": n}
        _save(db, user, g)
        raise HTTPException(403, "监护人密码不对")
    if lock:
        g.pop("pin_lock", None)
        _save(db, user, g)


_PHONE_RE = re.compile(r"^[+\d][\d\s-]{5,19}$")
_PIN_RE = re.compile(r"^\d{4,6}$")


class Person(BaseModel):
    name: str = Field(default="", max_length=20)
    phone: str = Field(default="", max_length=20)


def _person(p: Person | None, what: str) -> dict:
    if not p or not p.name.strip() or not _PHONE_RE.match(p.phone.strip()):
        raise HTTPException(400, "请填写监护人的姓名和电话" if what == "监护人" else "请填写紧急联系人的姓名和电话")
    return {"name": p.name.strip(), "phone": p.phone.strip()}


class ProfileIn(BaseModel):
    birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")  # 出生年月 YYYY-MM
    contact: Person | None = None          # 紧急联系人（国内版）
    guardian: Person | None = None         # 监护人（不满 14 岁必填；14–17 岁可填）
    guardian_consent: bool = False         # 监护人已阅读并同意
    pin: str | None = Field(default=None, max_length=6)  # 监护人密码（4–6 位数字）


@router.get("/guard")
def get_status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return status(db, user)


@router.post("/guard/profile")
def set_profile(body: ProfileIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    """第一次用时补的信息：出生年月（填了不能自己改）、紧急联系人（国内版）、监护人同意（不满 14 岁）。"""
    g = _g(user)
    if body.birth:
        if g.get("birth") and g["birth"] != body.birth:
            raise HTTPException(400, "出生年月填过就不能自己改了；填错了请在“投诉与反馈”里申诉")
        y, m = (int(x) for x in body.birth.split("-"))
        if not (1 <= m <= 12 and 1900 <= y and date(y, m, 1) <= date.today()):
            raise HTTPException(400, "出生年月不对")
        g["birth"] = body.birth  # 国际站不满 18 岁也记下来：同一个账号不能换个日期再试
    if body.contact and (body.contact.name or body.contact.phone):
        g["contact"] = _person(body.contact, "紧急联系人")
    user.settings = {**(user.settings or {}), "guard": g}
    a = age(user)
    if body.guardian and (body.guardian.name or body.guardian.phone):
        if not cn():
            raise HTTPException(404, "没有这个功能")
        if not body.guardian_consent:
            raise HTTPException(400, "需要监护人勾选同意")
        if not body.pin or not _PIN_RE.match(body.pin):
            raise HTTPException(400, "请监护人设置一个 4–6 位数字的监护人密码")
        if g.get("pin"):
            _pin_ok(db, user, body.pin)  # 已经有监护人了：改监护人信息要用原来的密码
        g["guardian"] = {**_person(body.guardian, "监护人"), "consent_at": int(time.time())}
        g["pin"] = g.get("pin") or _hash_pin(body.pin)
        events.record("guard", "guardian_consent", user_id=user.id, payload={"age": a})
    _save(db, user, g)
    return status(db, user)


class MinorModeIn(BaseModel):
    on: bool


@router.post("/guard/minor-mode")
def set_minor_mode(body: MinorModeIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    """成年人自己打开 / 关闭未成年人模式（国内版）。不满 18 岁、疑似未成年人的关不掉。"""
    if not cn():
        raise HTTPException(404, "没有这个功能")
    g = _g(user)
    if not body.on and minor_reason(user) in ("age", "detected"):
        raise HTTPException(403, "未成年人模式不能关闭" if minor_reason(user) == "age" else "系统判断你可能是未成年人，申诉通过后才能关闭")
    g["minor_mode"] = body.on
    _save(db, user, g)
    return status(db, user)


class PingIn(BaseModel):
    tz: int | None = Field(default=None, ge=-840, le=840)  # 当地时间比 UTC 快多少分钟


@router.post("/guard/ping")
def ping(body: PingIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """页面开着、在前台时每分钟报一次：累计今天的使用时长和这一段连续使用的时长，返回最新状态（前端按它提醒）。"""
    g = _g(user)
    if body.tz is not None and g.get("tz") != body.tz:
        g["tz"] = body.tz
        user.settings = {**(user.settings or {}), "guard": g}
    t = now()
    day = _local_now(user).strftime("%Y-%m-%d")
    u = db.get(UsageDay, (user.id, day))
    if u is None:
        u = UsageDay(user_id=user.id, day=day, seconds=0)
        db.add(u)
    if u.last_ping and (t - u.last_ping).total_seconds() < PING_GAP_S:
        u.seconds += min(90, int((t - u.last_ping).total_seconds()))
    else:  # 隔了很久（或者今天第一次）：重新开始算连续使用；上一天跨过零点的接着算
        prev = db.scalar(select(UsageDay).where(UsageDay.user_id == user.id, UsageDay.day < day).order_by(UsageDay.day.desc()).limit(1))
        u.streak_start = prev.streak_start if prev and prev.last_ping and (t - prev.last_ping).total_seconds() < PING_GAP_S else t
    u.last_ping = t
    db.commit()
    return status(db, user)


class AppealIn(BaseModel):
    content: str = Field(min_length=2, max_length=500)


@router.post("/guard/appeal")
def appeal(body: AppealIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    """被误判成未成年人、出生年月填错了：提交申诉，运营核实后处理（核实后在后台取消“疑似”，或改正出生年月）。"""
    db.add(Report(user_id=user.id, kind="minor_appeal", content=body.content.strip()))
    g = _g(user)
    g["appealed"] = int(time.time())
    _save(db, user, g)
    return {"ok": True}


def _names(db: Session, user: User) -> dict:
    return {c.id: c.name for c in db.scalars(select(Character).where(Character.owner_id == user.id))}


# ---------- 接口：监护人（凭监护人密码） ----------

class PinIn(BaseModel):
    pin: str = Field(max_length=6)


class GuardianSettingsIn(PinIn):
    daily: int | None = Field(default=None, ge=0, le=MINOR_MAX_DAILY)
    curfew: bool | None = None
    blocked: list[str] | None = Field(default=None, max_length=50)


@router.post("/guard/guardian/overview")
def guardian_overview(body: PinIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    """监护人看：最近 7 天每天用了多久、和哪些角色聊过（只看次数，不看聊天内容）、风险提醒。"""
    if not cn():
        raise HTTPException(404, "没有这个功能")
    _pin_ok(db, user, body.pin)
    today = _local_now(user).date()
    days = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    rows = {u.day: u.seconds for u in db.scalars(select(UsageDay).where(UsageDay.user_id == user.id, UsageDay.day.in_(days)))}
    since = now() - timedelta(days=7)
    names = _names(db, user)
    chars = db.execute(select(ChatSession.character_id, func.count(Message.id))
                       .join(Message, Message.session_id == ChatSession.id)
                       .where(ChatSession.user_id == user.id, Message.role == "user", Message.created_at >= since)
                       .group_by(ChatSession.character_id).order_by(func.count(Message.id).desc())).all()
    risks = db.scalars(select(WorldEvent).where(WorldEvent.user_id == user.id, WorldEvent.kind == "guard",
                                                WorldEvent.name.like("risk:%"), WorldEvent.created_at >= now() - timedelta(days=30))
                       .order_by(WorldEvent.created_at.desc()).limit(20)).all()
    return {"usage": [{"day": d, "minutes": rows.get(d, 0) // 60} for d in days],
            "characters": [{"id": i, "name": names.get(i, ""), "messages": c} for i, c in chars],
            "all_characters": [{"id": i, "name": n} for i, n in names.items()],
            "risks": [{"at": r.created_at.isoformat(), "kind": (r.payload or {}).get("kind")} for r in risks],
            "status": status(db, user)}


@router.post("/guard/guardian/settings")
def guardian_settings(body: GuardianSettingsIn, user: User = Depends(session_user), db: Session = Depends(get_db)):
    if not cn():
        raise HTTPException(404, "没有这个功能")
    _pin_ok(db, user, body.pin)
    g = _g(user)
    lim = dict(g.get("limits") or {})
    if body.daily is not None:
        lim["daily"] = body.daily
    if body.curfew is not None:
        lim["curfew"] = body.curfew
    g["limits"] = lim
    if body.blocked is not None:
        mine = set(db.scalars(select(Character.id).where(Character.owner_id == user.id)).all())
        g["blocked"] = [x for x in body.blocked if x in mine]
    _save(db, user, g)
    return status(db, user)


# ---------- 接口：投诉举报（国内版） ----------

REPORT_KINDS = ("content", "service", "privacy", "other")
REPLY_DAYS = 15  # 承诺多少个工作日内答复


class ReportIn(BaseModel):
    kind: str = Field(pattern="^(content|service|privacy|other)$")
    content: str = Field(min_length=2, max_length=1000)
    message_id: int | None = None


def _report_out(r: Report) -> dict:
    return {"id": r.id, "kind": r.kind, "content": r.content, "message_id": r.message_id, "status": r.status, "reply": r.reply,
            "created_at": r.created_at.isoformat(), "handled_at": r.handled_at.isoformat() if r.handled_at else None}


@router.post("/reports")
def create_report(body: ReportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.message_id is not None:
        m = db.get(Message, body.message_id)
        s = db.get(ChatSession, m.session_id) if m else None
        if s is None or s.user_id != user.id:
            raise HTTPException(404, "找不到这条消息")
    r = Report(user_id=user.id, kind=body.kind, content=body.content.strip(), message_id=body.message_id)
    db.add(r)
    db.commit()
    return {**_report_out(r), "reply_days": REPLY_DAYS}


@router.get("/reports")
def my_reports(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Report).where(Report.user_id == user.id).order_by(Report.created_at.desc()).limit(50)).all()
    return {"reports": [_report_out(r) for r in rows], "reply_days": REPLY_DAYS}


# ---------- 接口：聊天记录导出、全部删除（国内版，第十六条） ----------

@router.get("/me/chats/export")
def export_chats(user: User = Depends(current_user), db: Session = Depends(get_db)):
    sessions = db.scalars(select(ChatSession).where(ChatSession.user_id == user.id).order_by(ChatSession.created_at)).all()
    names = _names(db, user)
    out = []
    for s in sessions:
        msgs = db.scalars(select(Message).where(Message.session_id == s.id, Message.role.in_(("user", "assistant")))
                          .order_by(Message.id)).all()
        out.append({"character": names.get(s.character_id, ""), "title": s.title, "started": s.created_at.isoformat(),
                    "messages": [{"from": "me" if m.role == "user" else "ai", "text": m.content, "at": m.created_at.isoformat()}
                                 for m in msgs]})
    body = json.dumps({"format": "krino-chats/1", "exported_at": now().isoformat(), "user": user.username, "sessions": out},
                      ensure_ascii=False, indent=1)
    return Response(body, media_type="application/json",
                    headers={"Content-Disposition": 'attachment; filename="krino-chats.json"'})


@router.delete("/me/chats")
def delete_chats(user: User = Depends(session_user), db: Session = Depends(get_db)):
    """删除全部聊天记录（所有角色的所有对话）。记得的事（记忆）不在这里删，在“她记得的事”里管理。"""
    ids = db.scalars(select(ChatSession.id).where(ChatSession.user_id == user.id)).all()
    if ids:
        db.execute(delete(Message).where(Message.session_id.in_(ids)))
        db.execute(delete(ChatSession).where(ChatSession.id.in_(ids)))
    db.commit()
    return {"ok": True, "sessions": len(ids)}


# ---------- 接口：运营后台（WORKSHOP_ADMINS 里的账号） ----------

def _admin(user: User = Depends(session_user)) -> User:
    if not is_admin(user):
        raise HTTPException(403, "只有管理员能看")
    return user


@router.get("/guard/admin/reports")
def admin_reports(status_: str = "open", admin: User = Depends(_admin), db: Session = Depends(get_db)):
    rows = db.execute(select(Report, User.username).join(User, User.id == Report.user_id)
                      .where(Report.status == status_).order_by(Report.created_at).limit(200)).all()
    return [{**_report_out(r), "username": u} for r, u in rows]


class HandleIn(BaseModel):
    reply: str = Field(min_length=1, max_length=1000)
    clear_minor: bool = False  # 申诉核实通过：取消“疑似未成年人”
    birth: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")  # 申诉核实后改正的出生年月


@router.post("/guard/admin/reports/{rid}")
def admin_handle(rid: str, body: HandleIn, admin: User = Depends(_admin), db: Session = Depends(get_db)):
    r = db.get(Report, rid)
    if r is None:
        raise HTTPException(404, "没有这条")
    r.status, r.reply, r.handled_at = "done", body.reply.strip(), now()
    if body.clear_minor or body.birth:
        u = db.get(User, r.user_id)
        g = _g(u)
        g.pop("suspected", None)
        g.pop("appealed", None)
        if body.birth:  # 核实后改正出生年月（用户自己改不了）
            g["birth"] = body.birth
        u.settings = {**(u.settings or {}), "guard": g}
    db.commit()
    return _report_out(r)


@router.get("/guard/admin/risks")
def admin_risks(admin: User = Depends(_admin), db: Session = Depends(get_db)):
    """最近 7 天的风险事件和联系人：值班的人据此联络监护人或紧急联系人（第十三条）。"""
    rows = db.execute(select(WorldEvent, User).join(User, User.id == WorldEvent.user_id)
                      .where(WorldEvent.kind == "guard", WorldEvent.name.like("risk:%"),
                             WorldEvent.created_at >= now() - timedelta(days=7))
                      .order_by(WorldEvent.created_at.desc()).limit(200)).all()
    out = []
    for e, u in rows:
        g = _g(u)
        out.append({"at": e.created_at.isoformat(), "username": u.username, "kind": (e.payload or {}).get("kind"),
                    "text": (e.payload or {}).get("text"), "age": age(u),
                    "guardian": g.get("guardian"), "contact": g.get("contact")})
    return out
