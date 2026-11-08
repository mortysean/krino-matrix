"""酒馆：自己的几个角色在一个房间里聊天；主持挑谁接话；主人插话会被回应；只有主人自己能看到。"""
import random
import time

from app import credits, tavern
from app.config import settings
from app.models import Character, TavernMessage


def _wait(u, n, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = u.ok("get", "/api/tavern")
        if not r["busy"] and len(r["messages"]) >= n:
            return r
        time.sleep(0.1)
    return u.ok("get", "/api/tavern")


def test_round_takes_turns_and_owner_gets_answered(user):
    r = user.ok("get", "/api/tavern")
    assert len(r["cast"]) >= 2 and r["messages"] == []
    user.ok("post", "/api/tavern/go", json={"topic": "主人的作息"})
    r = _wait(user, tavern.ROUND_TURNS)
    msgs = r["messages"]
    assert len(msgs) == tavern.ROUND_TURNS
    assert all(a["author_id"] != b["author_id"] for a, b in zip(msgs, msgs[1:]))  # 没人连着说
    assert len({m["author_id"] for m in msgs}) >= 2
    # 主人插一句：记下来，接着有人接话
    out = user.ok("post", "/api/tavern/say", json={"text": "你们在背后说我什么呢"})
    assert out["message"]["author_id"] is None
    r = _wait(user, tavern.ROUND_TURNS + 1 + tavern.REPLY_TURNS)
    after = r["messages"][tavern.ROUND_TURNS:]
    assert after[0]["author_id"] is None and all(m["author_id"] for m in after[1:])
    # 只看新的
    newer = user.ok("get", "/api/tavern", params={"after": msgs[-1]["id"]})["messages"]
    assert newer[0]["content"] == "你们在背后说我什么呢"
    # 聊过之后，室友之间有了印象
    fr = user.ok("get", "/api/social/friends", params={"character_id": user.krino["id"]})
    assert any(f["impression"] for f in fr if f["house"])
    user.ok("delete", "/api/tavern")
    assert user.ok("get", "/api/tavern")["messages"] == []


def test_tavern_is_private(user, other):
    user.ok("post", "/api/tavern/go", json={})
    _wait(user, tavern.ROUND_TURNS)
    assert other.ok("get", "/api/tavern")["messages"] == []


def test_out_of_credits_stops_the_room(user, monkeypatch):
    monkeypatch.setattr(settings, "credit_user_limits", {user.info["username"]: 1})
    credits.charge(user.info["id"], "image", 1.0)
    assert user.post("/api/tavern/go", json={}).status_code == 429


def test_pick_speaker_rules():
    """被点名的先说；刚说过的不连着说。"""
    a, b, c = (Character(id=i, behavior={"talkativeness": 0.5}, persona={"name": n}, slug=i)
               for i, n in (("a", "KRINO"), ("b", "大肥鱼"), ("c", "乔巴")))
    hist = [TavernMessage(author_id="a", content="大肥鱼你说呢？")]
    assert tavern.pick_speaker([a, b, c], hist, random.Random(0)).id == "b"
    hist = [TavernMessage(author_id="b", content="嗯")]
    picks = {tavern.pick_speaker([a, b, c], hist, random.Random(s)).id for s in range(30)}
    assert picks == {"a", "c"}
