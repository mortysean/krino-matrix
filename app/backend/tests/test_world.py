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


# ---------- 你走进她的世界 ----------

def test_you_walk_over_and_she_knows_you_are_right_there(user, other, daytime):
    """你去她在的地方找她：你出现在小镇里（别人的小镇里她在“和你在一起”），她开口打招呼，这是一段会话的第一句；
    之后聊天时她知道你就在身边、是面对面；说再见后她再待一会儿就回到日程。"""
    _friends(user, other)
    me = user.krino["id"]
    _set(me, place="cafe", activity="coffee", energy=70.0, until=daytime + timedelta(hours=1))
    out = user.ok("post", "/api/social/town/with", json={"character_id": me})
    assert out["ok"] and out["how"] == "visit" and out["place"] == "cafe" and out["line"] and out["session_id"]
    tw = user.ok("get", "/api/social/town")
    assert tw["you"]["character_id"] == me and tw["you"]["place"] == "cafe"
    seen_by_friend = {c["id"]: c for c in other.ok("get", "/api/social/town")["cast"]}[me]["state"]
    assert seen_by_friend["activity"] == "owner" and seen_by_friend["place"] == "cafe"
    assert other.ok("get", "/api/social/town")["you"] is None
    msgs = user.ok("get", f"/api/sessions/{out['session_id']}")["messages"]
    assert msgs[0]["role"] == "assistant" and msgs[0]["content"] == out["line"]
    db = SessionLocal()
    inner = world.inner_for(db.get(Character, me))
    assert "就在咖啡馆" in inner and "面对面" in inner
    db.close()
    # 朋友这时约她：她正和你在一起
    r = other.ok("post", "/api/social/town/meet", json={"character_id": other.krino["id"], "friend_id": me, "place": "plaza"})
    assert not r["ok"] and r["by"] == me and r["why"] == "busy"
    assert user.ok("post", "/api/social/town/leave")["session_id"] == out["session_id"]
    assert user.ok("get", "/api/social/town")["you"] is None
    db = SessionLocal()
    world.advance(db, [db.get(Character, me)], daytime + timedelta(minutes=5))
    db.commit()
    assert db.get(CharState, me).activity != "owner"
    db.close()


def test_invite_her_somewhere_and_it_becomes_a_shared_memory(user, daytime):
    """约她一起去观星台：她答应了就过去，这成了你们的共同经历（她的记忆里有，同一天同一个地方只记一次）。"""
    me = user.krino["id"]
    _set(me, place="plaza", activity="stroll", energy=70.0, mood="calm", until=daytime + timedelta(hours=1))
    out = user.ok("post", "/api/social/town/with", json={"character_id": me, "place": "stars"})
    assert out["ok"] and out["how"] == "invite" and out["state"]["place"] == "stars"
    user.ok("post", "/api/social/town/with", json={"character_id": me, "place": "stars"})
    mems = [m for m in user.ok("get", "/api/memories", params={"character_id": me}) if m["key"] and m["key"].startswith("together:stars")]
    assert len(mems) == 1 and mems[0]["type"] == "event" and "观星台" in mems[0]["content"]


def test_she_can_say_no_to_you_too(user, daytime):
    """她在睡觉：你走过去她也不起来；太累了不想跟你挪地方。她用自己的话说，你在小镇里不出现。"""
    me = user.krino["id"]
    _set(me, place="home", activity="sleep", until=daytime + timedelta(hours=1))
    out = user.ok("post", "/api/social/town/with", json={"character_id": me})
    assert not out["ok"] and out["why"] == "asleep" and "睡觉" in out["line"]
    assert user.ok("get", "/api/social/town")["you"] is None
    _set(me, place="plaza", activity="stroll", energy=10.0, mood="tired", until=daytime + timedelta(hours=1))
    out = user.ok("post", "/api/social/town/with", json={"character_id": me, "place": "stars"})
    assert not out["ok"] and out["why"] == "tired"
    assert user.ok("post", "/api/social/town/with", json={"character_id": me})["ok"]  # 但你走过去找她，她会理你


def test_cannot_be_with_someone_elses_soul(user, other, daytime):
    assert user.post("/api/social/town/with", json={"character_id": other.krino["id"]}).status_code == 404


def test_while_together_you_can_go_somewhere_else_in_the_same_conversation(user, daytime):
    me = user.krino["id"]
    _set(me, place="cafe", activity="coffee", energy=70.0, mood="happy", until=daytime + timedelta(hours=1))
    a = user.ok("post", "/api/social/town/with", json={"character_id": me})
    b = user.ok("post", "/api/social/town/with", json={"character_id": me, "place": "stars"})
    assert b["ok"] and b["how"] == "invite" and b["session_id"] == a["session_id"]
    assert user.ok("get", "/api/social/town")["you"]["place"] == "stars"
    msgs = user.ok("get", f"/api/sessions/{a['session_id']}")["messages"]
    assert [m["content"] for m in msgs] == [a["line"], b["line"]]


# ---------- 关系可以变近，也可以变远 ----------

def _chat(user, cid, *lines):
    sid = user.session(cid)
    for t in lines:
        user.say(sid, t)
    user.ok("post", f"/api/sessions/{sid}/end")
    return user.ok("get", f"/api/relations/{cid}/bond")


def test_harsh_words_hurt_her_and_an_apology_heals_it(user, daytime):
    """你冲她说狠话：关系远一点、没那么信你，心里有个结（说话时带着，约她出去也更可能不去）；道歉之后结解开了。"""
    cid = user.official["id"]
    b0 = _chat(user, cid, "今天还好", "随便聊聊")
    b1 = _chat(user, cid, "你好烦", "烦死了别烦我")
    assert b1["hurt"] and b1["trust"] < b0["trust"] and b1["closeness"] < b0["closeness"] + 2
    db = SessionLocal()
    from app import memory
    from app.models import Bond
    bond = db.get(Bond, (user.info["id"], cid))
    assert "心里还有个结" in memory.bond_prompt(bond, "大肥鱼")
    db.close()
    b2 = _chat(user, cid, "对不起，刚才是我不好", "我心情差，不该冲你")
    assert b2["hurt"] is None and any(m["text"] == "解开了心结" for m in b2["milestones"])


def test_hurt_makes_her_less_willing_to_go_out_with_you(user, daytime):
    db = SessionLocal()
    from app import memory
    c = db.get(Character, user.krino["id"])
    world.advance(db, [c], daytime)
    s = db.get(CharState, c.id)
    s.place, s.activity, s.energy, s.mood, s.until = "plaza", "stroll", 80.0, "calm", daytime + timedelta(hours=1)
    db.commit()
    hits = 0
    for h in range(24):  # 按小时固定：一天里大部分时候不想跟你出去
        t = daytime.replace(hour=h)
        hits += world.consider_owner(db, c, "stars", "invite", 50.0, t, hurt=True) == "upset"
    assert 8 <= hits <= 20
    assert world.consider_owner(db, c, "plaza", "visit", 50.0, daytime, hurt=True) is None  # 你走过去找她，她还是会理你
    db.close()


def test_she_remembers_her_own_promise(user):
    """她说过“下次一起去看海”：记成她答应你的事；之后聊天时一直带着（不靠关键词碰上）。"""
    from app import chat as chat_mod
    from app.models import Memory
    cid = user.official["id"]
    sid = user.session(cid)
    db = SessionLocal()
    from app.models import Message
    user.say(sid, "周末好无聊")
    db.add(Message(session_id=sid, role="assistant", content="那下次我陪你一起去看海吧！"))
    db.commit()
    user.say(sid, "好呀")
    user.ok("post", f"/api/sessions/{sid}/end")
    m = db.scalar(select(Memory).where(Memory.character_id == cid, Memory.origin == "her"))
    assert m and m.type == "commitment" and "看海" in m.content
    db.close()
    seen = []
    real = chat_mod.build_system
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(chat_mod, "build_system", lambda *a, **k: (seen.append(k["memories"]), real(*a, **k))[1])
    user.say(user.session(cid), "今天吃了面条", wait=False)
    mp.undo()
    assert any("看海" in x["content"] for x in seen[0])
