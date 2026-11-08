"""圈子：角色 ID、加好友（对方主人同意）、私信（两边主人都能看）、朋友圈、印象、自主活动、隐私开关、谁说话谁出积分。"""
import random
import time

from app import credits, social
from app.config import settings


def _wait_thread(u, fid, n=4, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        th = u.ok("get", f"/api/social/threads/{fid}")
        if not th["busy"] and len(th["messages"]) >= n:
            return th
        time.sleep(0.1)
    return u.ok("get", f"/api/social/threads/{fid}")


def test_every_character_has_a_unique_public_id(user, other):
    ids = [c["public_id"] for c in user.ok("get", "/api/characters") + other.ok("get", "/api/characters")]
    assert all(i and i.startswith("KR-") and len(i) == 9 for i in ids)
    assert len(set(ids)) == len(ids)


def test_housemates_are_friends_and_can_gossip(user):
    """同一个主人的角色天生是室友；让她们私信，两边轮流说，结束后各自记下对对方的印象。"""
    ov = user.ok("get", "/api/social")
    assert len(ov["characters"]) >= 2 and all(c["public_id"] for c in ov["characters"])
    fr = user.ok("get", "/api/social/friends", params={"character_id": user.krino["id"]})
    house = next(f for f in fr if f["friend"]["id"] == user.official["id"])
    assert house["house"]
    user.ok("post", f"/api/social/threads/{house['id']}/chat", json={"character_id": user.krino["id"], "topic": "主人又熬夜了"})
    th = _wait_thread(user, house["id"])
    assert len(th["messages"]) == social.DM_TURNS
    authors = [m["author_id"] for m in th["messages"]]
    assert authors[0] == user.krino["id"] and authors[1] == user.official["id"]  # 轮流说
    fr = user.ok("get", "/api/social/friends", params={"character_id": user.krino["id"]})
    assert next(f for f in fr if f["id"] == house["id"])["impression"]  # 她对室友有了印象
    assert user.delete(f"/api/social/friends/{house['id']}").status_code == 400  # 室友不能删


def test_friend_request_needs_the_other_owner(user, other):
    mine, theirs = user.krino, other.official
    r = user.ok("post", "/api/social/requests", json={"from_id": mine["id"], "to": theirs["public_id"].lower(), "note": "你好呀"})
    assert r["status"] == "pending"
    assert user.post(f"/api/social/requests/{r['id']}/accept").status_code == 404  # 只有对方的主人能同意
    inc = other.ok("get", "/api/social")["incoming"]
    assert inc[0]["from"]["public_id"] == mine["public_id"] and inc[0]["note"] == "你好呀"
    other.ok("post", f"/api/social/requests/{r['id']}/accept")
    # 私信：我让 KRINO 去聊，对方的角色回话；两边主人都能看到
    user.ok("post", f"/api/social/threads/{r['id']}/chat", json={"character_id": mine["id"]})
    th = _wait_thread(user, r["id"])
    assert len(th["messages"]) == social.DM_TURNS
    assert other.ok("get", f"/api/social/threads/{r['id']}")["messages"] == th["messages"]
    # 不相干的人看不到
    from tests.conftest import make_user
    stranger = make_user(user.c)
    assert stranger.get(f"/api/social/threads/{r['id']}").status_code == 404
    assert user.post("/api/social/requests", json={"from_id": mine["id"], "to": "KR-ZZZZZZ"}).status_code == 404


def test_feed_posts_likes_and_comments(user, other):
    r = user.ok("post", "/api/social/requests", json={"from_id": user.krino["id"], "to": other.krino["public_id"]})
    other.ok("post", f"/api/social/requests/{r['id']}/accept")
    p = other.ok("post", "/api/social/posts", json={"character_id": other.krino["id"]})
    assert p["content"] and p["mine"]
    feed = user.ok("get", "/api/social/feed")
    assert any(x["id"] == p["id"] for x in feed)  # 好友的动态我能看到
    out = user.ok("post", f"/api/social/posts/{p['id']}/react", json={"character_id": user.krino["id"], "kind": "like"})
    assert [x["public_id"] for x in out["likes"]] == [user.krino["public_id"]]
    out = user.ok("post", f"/api/social/posts/{p['id']}/react", json={"character_id": user.krino["id"], "kind": "comment"})
    assert out["comments"][0]["content"]
    # 我的大肥鱼还不是 ta 的好友：不能评论
    assert user.post(f"/api/social/posts/{p['id']}/react", json={"character_id": user.official["id"], "kind": "like"}).status_code in (200, 403)
    # 陌生人看不到这条
    from tests.conftest import make_user
    assert not any(x["id"] == p["id"] for x in make_user(user.c).ok("get", "/api/social/feed"))
    assert user.delete(f"/api/social/posts/{p['id']}").status_code == 404  # 只有作者的主人能删
    other.ok("delete", f"/api/social/posts/{p['id']}")


def test_share_life_toggle_and_no_sensitive(user, client):
    """主人关掉“带一点近况”，她的圈子提示词里就没有主人的生活；私密记忆从来不给。"""
    from app.db import SessionLocal
    from app.models import Character, Memory

    db = SessionLocal()
    c = db.get(Character, user.krino["id"])
    db.add(Memory(user_id=user.info["id"], character_id=c.id, type="event", title="加班", content="用户最近在加班做项目",
                  origin="stated", importance=3))
    db.add(Memory(user_id=user.info["id"], character_id=c.id, type="event", title="体检", content="用户体检查出了问题",
                  origin="stated", importance=3, sensitive=True))
    db.commit()
    s = social._system(db, c)
    assert "加班" in s and "体检" not in s
    user.ok("patch", "/api/me", json={"social": {"share_life": False}})
    db.expire_all()
    s = social._system(db, c)
    assert "加班" not in s
    db.close()


def test_whoever_speaks_pays(user, other, monkeypatch):
    """谁的角色说话谁出积分：主人今天积分用完了，她就不说话（对方的角色照常）。"""
    r = user.ok("post", "/api/social/requests", json={"from_id": user.krino["id"], "to": other.krino["public_id"]})
    other.ok("post", f"/api/social/requests/{r['id']}/accept")
    monkeypatch.setattr(settings, "credit_user_limits", {other.info["username"]: 1})
    credits.charge(other.info["id"], "image", 1.0)  # 对方今天花完了
    user.ok("post", f"/api/social/threads/{r['id']}/chat", json={"character_id": user.krino["id"]})
    th = _wait_thread(user, r["id"], n=1)
    assert [m["author_id"] for m in th["messages"]] == [user.krino["id"]]  # 只有我这边说了一句
    assert other.post(f"/api/social/threads/{r['id']}/chat", json={"character_id": other.krino["id"]}).status_code == 429


def test_autonomy_tick(user, client, monkeypatch):
    """自主活动：最近来过的主人，她的角色会自己发动态、找室友聊天；主人关掉就不动。"""
    from app.db import SessionLocal

    sid = user.session(user.krino["id"])
    user.say(sid, "你好")  # 来过 → 算活跃（关系里记下最后来的时间）
    monkeypatch.setattr(social, "now", lambda: __import__("app.models", fromlist=["now"]).now().replace(hour=12))

    class Always(random.Random):
        def random(self):
            return 0.0

    db = SessionLocal()
    done = social.autonomy_tick(db, tick_s=16 * 3600, rng=Always(1), budget=100)
    assert done["posts"] >= 2 and done["dms"] >= 1
    feed = user.ok("get", "/api/social/feed")
    assert {p["author"]["id"] for p in feed} >= {user.krino["id"], user.official["id"]}
    user.ok("patch", "/api/me", json={"social": {"autonomy": False}})
    db.expire_all()
    assert not any(social.autonomy_tick(db, tick_s=16 * 3600, rng=Always(1), budget=100)[k] for k in ("posts", "dms"))
    db.close()


def test_pending_character_stays_out_of_autonomy(user, monkeypatch):
    """刚新建、形象还在后台做的角色，先不自己发动态。"""
    import time as _t

    from app.db import SessionLocal
    from app.models import Character

    sid = user.session(user.krino["id"])
    user.say(sid, "你好")
    db = SessionLocal()
    c = db.get(Character, user.official["id"])
    c.origin = {**(c.origin or {}), "pending": _t.time()}
    db.commit()
    monkeypatch.setattr(social, "now", lambda: __import__("app.models", fromlist=["now"]).now().replace(hour=12))

    class Always(random.Random):
        def random(self):
            return 0.0

    social.autonomy_tick(db, tick_s=16 * 3600, rng=Always(1), budget=100)
    authors = {p["author"]["id"] for p in user.ok("get", "/api/social/feed")}
    assert user.official["id"] not in authors and user.krino["id"] in authors
    db.close()
