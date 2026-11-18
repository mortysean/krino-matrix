"""世界：她在哪、在做什么由服务器按世界时间推进，所有人看到同一个小镇；累了会回家，孤单了去酒馆，约好的碰面优先于日程。"""
from datetime import datetime, timedelta

from sqlalchemy import select

from app import world
from app.db import SessionLocal
from app.models import Character, CharState, LifeEvent, now
from tests.test_social import _wait_thread


def _at(hour: int, day: int = 19) -> datetime:
    return datetime(2026, 11, day, hour, 30, tzinfo=world.tz())


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


def test_meeting_holds_both_at_the_place_then_they_go_back(user, other):
    """约去观星台：两人都在观星台、在聊天、知道和谁在一起；聊完再待一会儿就回到日程。"""
    r = user.ok("post", "/api/social/requests", json={"from_id": user.krino["id"], "to": other.krino["public_id"]})
    other.ok("post", f"/api/social/requests/{r['id']}/accept")
    out = user.ok("post", "/api/social/town/meet", json={"character_id": user.krino["id"], "friend_id": other.krino["id"], "place": "stars"})
    _wait_thread(user, out["id"])
    cast = {c["id"]: c for c in other.ok("get", "/api/social/town")["cast"]}
    s = cast[user.krino["id"]]["state"]
    assert s["place"] == "stars" and s["activity"] == "talk" and s["with"] == other.krino["id"]
    assert datetime.fromisoformat(s["until"]) <= now() + timedelta(minutes=4)  # 聊完了：只再待一会儿
    db = SessionLocal()
    ids = [user.krino["id"], other.krino["id"]]
    world.advance(db, [db.get(Character, i) for i in ids], now() + timedelta(minutes=5))
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
