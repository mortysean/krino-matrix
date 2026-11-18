"""世界：她在哪、在做什么由服务器按世界时间推进，所有人看到同一个小镇；累了会回家，孤单了去酒馆，约好的碰面优先于日程。"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import world
from app.db import SessionLocal
from app.models import Character, CharState, LifeEvent, now
from tests.test_social import _wait_thread


def _at(hour: int, day: int = 19) -> datetime:
    return datetime(2026, 11, day, hour, 30, tzinfo=world.tz())


@pytest.fixture
def daytime(monkeypatch):
    """世界里是今天下午三点半（晚上她们会在家睡觉，约不出来）。"""
    t = world.local(world.now()).replace(hour=15, minute=30)
    monkeypatch.setattr(world, "now", lambda: t)
    return t


def _friends(user, other):
    r = user.ok("post", "/api/social/requests", json={"from_id": user.krino["id"], "to": other.krino["public_id"]})
    other.ok("post", f"/api/social/requests/{r['id']}/accept")


def _meet(user, other, place="stars"):
    return user.ok("post", "/api/social/town/meet", json={"character_id": user.krino["id"], "friend_id": other.krino["id"], "place": place})


def test_schedule_follows_world_time_and_her_state():
    assert world.plan("x", _at(3)) == "home"
    assert world.plan("x", _at(15), energy=10) == "home"  # 累坏了
    assert world.plan("x", _at(20), mood="lonely") == "tavern"  # 好几天没人说话：去酒馆找人
    assert world.plan("x", _at(20), energy=25) == "home"
    assert world.plan("x", _at(9)) in ("cafe", "plaza")
    assert world.plan("x", _at(9)) == world.plan("x", _at(9))  # 同一时刻同一个人：结果固定


def test_two_owners_see_the_same_town_state(user, other):
    """我和朋友的主人看到的是同一个她：同一个地方、同一件事；还有世界时钟。"""
    r = user.ok("post", "/api/social/requests", json={"from_id": user.krino["id"], "to": other.krino["public_id"]})
    other.ok("post", f"/api/social/requests/{r['id']}/accept")
    a = {c["id"]: c for c in user.ok("get", "/api/social/town")["cast"]}
    tw = other.ok("get", "/api/social/town")
    b = {c["id"]: c for c in tw["cast"]}
    me = user.krino["id"]
    assert a[me]["state"]["place"] == b[me]["state"]["place"] and a[me]["state"]["activity"] == b[me]["state"]["activity"]
    assert a[me]["state"]["doing"] and a[me]["state"]["mood"] in world.MOODS
    assert tw["clock"]["tz"] == world.settings.world_tz and 0 <= tw["clock"]["hour"] < 24


def test_world_moves_her_and_keeps_a_life_log(user):
    """推进到半夜她回家睡觉，精力慢慢回来；去了哪记在生活记录里。"""
    db = SessionLocal()
    c = db.get(Character, user.krino["id"])
    world.advance(db, [c], _at(15).astimezone())
    s = db.get(CharState, c.id)
    s.energy = 40.0
    db.commit()
    world.advance(db, [c], _at(23).astimezone())  # 晚上 11 点：太累了，不去观星台，回家
    world.advance(db, [c], _at(5, day=20).astimezone())
    db.commit()
    db.refresh(s)
    assert s.place == "home" and s.activity == "sleep" and s.energy > 40
    moves = db.scalars(select(LifeEvent).where(LifeEvent.char_id == c.id, LifeEvent.kind == "move")).all()
    assert moves and moves[-1].place == "home"
    db.close()


def test_meeting_holds_both_at_the_place_then_they_go_back(user, other, daytime):
    """约去观星台：两人都在观星台、在聊天、知道和谁在一起；聊完再待一会儿就回到日程。"""
    _friends(user, other)
    out = _meet(user, other)
    assert out["ok"]
    _wait_thread(user, out["id"])
    cast = {c["id"]: c for c in other.ok("get", "/api/social/town")["cast"]}
    s = cast[user.krino["id"]]["state"]
    assert s["place"] == "stars" and s["activity"] == "talk" and s["with"] == other.krino["id"]
    assert datetime.fromisoformat(s["until"]) <= daytime + timedelta(minutes=4)  # 聊完了：只再待一会儿
    db = SessionLocal()
    ids = [user.krino["id"], other.krino["id"]]
    world.advance(db, [db.get(Character, i) for i in ids], daytime + timedelta(minutes=5))
    db.commit()
    for i in ids:
        st = db.get(CharState, i)
        assert st.until is None and st.with_id is None and st.mood == "happy"  # 刚和朋友聊过：开心
        assert db.scalar(select(LifeEvent).where(LifeEvent.char_id == i, LifeEvent.kind == "meet")).place == "stars"
    db.close()


def test_lonely_after_days_without_anyone(user):
    db = SessionLocal()
    c = db.get(Character, user.official["id"])
    world.advance(db, [c], now() + timedelta(days=4))
    db.commit()
    assert db.get(CharState, c.id).mood in ("lonely", "tired")
    db.close()


def _set(cid, **kw):
    db = SessionLocal()
    c = db.get(Character, cid)
    world.advance(db, [c])
    s = db.get(CharState, cid)
    for k, v in kw.items():
        setattr(s, k, v)
    db.commit()
    db.close()


def test_she_can_say_no_when_asleep_and_remembers_it(user, other, daytime):
    """她在家睡觉：主人约她出去，她不去，用自己的话说为什么；这件事她记得，之后说话时带着。"""
    _friends(user, other)
    _set(user.krino["id"], place="home", activity="sleep", until=daytime + timedelta(hours=1))
    out = _meet(user, other)
    assert not out["ok"] and out["by"] == user.krino["id"] and out["why"] == "asleep" and "在睡觉" in out["line"]
    th = user.ok("get", f"/api/social/threads/{out['id']}")
    assert not th["messages"]  # 没去，就没有这段对话
    db = SessionLocal()
    me = db.get(Character, user.krino["id"])
    assert db.scalar(select(LifeEvent).where(LifeEvent.char_id == me.id, LifeEvent.kind == "decline")).other_id == other.krino["id"]
    inner = world.inner_prompt(db, me, daytime)
    assert "没答应" in inner and "KRINO" in inner and "可以不配合" in inner
    db.close()


def test_the_friend_can_say_no_too(user, other, daytime):
    """朋友累坏了：来不了，我的角色告诉我。"""
    _friends(user, other)
    _set(other.krino["id"], energy=5.0)
    out = _meet(user, other, "tavern")
    assert not out["ok"] and out["by"] == other.krino["id"] and out["why"] == "tired" and out["line"]


def test_lonely_or_happy_she_goes_out_even_a_bit_tired(user, other, daytime):
    _friends(user, other)
    _set(user.krino["id"], energy=30.0)
    _set(other.krino["id"], energy=30.0)
    db = SessionLocal()
    a, b = db.get(Character, user.krino["id"]), db.get(Character, other.krino["id"])
    db.get(CharState, a.id).mood = "lonely"
    assert world.consider(db, a, b, "tavern", daytime) is None
    db.close()


def test_her_life_goes_into_what_she_says(user, other, daytime, monkeypatch):
    """她此刻的生活写进说话的提示词：和主人聊天（单独的会话取）、和朋友私信都带着；没有主人的模板没有。"""
    from app import social

    _friends(user, other)
    db = SessionLocal()
    me = db.get(Character, user.krino["id"])
    life = world.inner_for(me)
    assert "你此刻在小镇里" in life and "精力" in life and "你心里" in life
    assert "你此刻在小镇里" in social._system(db, me, db.get(Character, other.krino["id"]))
    assert world.inner_for(Character(id="x", owner_id=None)) == ""
    db.close()
    seen = []
    from app import chat as chat_mod
    real = chat_mod.build_system
    monkeypatch.setattr(chat_mod, "build_system", lambda *a, **k: (seen.append(k.get("life")), real(*a, **k))[1])
    sid = user.session(user.krino["id"])
    user.say(sid, "你在干嘛呀", wait=False)
    assert seen and seen[0] and "你此刻在小镇里" in seen[0]
