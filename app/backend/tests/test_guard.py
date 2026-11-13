"""未成年人保护和《人工智能拟人化互动服务管理暂行办法》的落实（app/guard.py）。测试跑的是国内版（SITE_EDITION 默认 cn）。"""
import json
from datetime import date

import pytest

from tests.conftest import make_user


@pytest.fixture(autouse=True)
def _daytime(monkeypatch):
    """夜里 22:00–8:00 未成年人不能用：测试不管几点跑，都按白天算（夜间限制单独测）。"""
    from app import guard
    monkeypatch.setattr(guard, "in_curfew", lambda user: False)


def _birth(age: int) -> str:
    t = date.today()
    return f"{t.year - age}-{t.month:02d}"


def _stream(user, sid, text, cid):
    r = user.post(f"/api/sessions/{sid}/stream", json={"text": text, "character_id": cid})
    assert r.status_code == 200, r.text
    return json.loads(r.text.split("event: done\ndata: ")[1].split("\n")[0])


def test_must_give_age_and_contact_before_chatting(client):
    u = make_user(client, birth=None)
    g = u.ok("get", "/api/guard")
    assert set(g["needs"]) == {"birth", "contact"}
    k = u.krino["id"]
    assert u.post("/api/sessions", json={"character_id": k}).status_code == 403
    u.ok("post", "/api/guard/profile", json={"birth": "1990-01", "contact": {"name": "李四", "phone": "13900000000"}})
    assert u.ok("get", "/api/guard")["needs"] == [] and u.session(k)
    # 填了就不能自己改
    assert u.post("/api/guard/profile", json={"birth": "2015-01"}).status_code == 400
    # 监护人密码不会出现在 /me 里
    assert "pin" not in u.ok("get", "/api/me")["settings"].get("guard", {})


def test_under_14_needs_guardian_consent(client):
    u = make_user(client, birth=None)
    u.ok("post", "/api/guard/profile", json={"birth": _birth(12)})
    assert "guardian" in u.ok("get", "/api/guard")["needs"]
    assert u.post("/api/guard/profile", json={"guardian": {"name": "王妈妈", "phone": "13700000000"}, "pin": "1234"}).status_code == 400  # 没勾同意
    g = u.ok("post", "/api/guard/profile", json={"guardian": {"name": "王妈妈", "phone": "13700000000"}, "guardian_consent": True, "pin": "1234"})
    assert g["needs"] == [] and g["minor"] and g["minor_reason"] == "age" and g["has_pin"]
    assert u.post("/api/guard/minor-mode", json={"on": False}).status_code == 403  # 未成年人关不掉


def test_minor_mode_rules_limits_and_guardian(client):
    u = make_user(client, birth=None)
    u.ok("post", "/api/guard/profile", json={"birth": _birth(15), "guardian": {"name": "爸爸", "phone": "13600000000"},
                                            "guardian_consent": True, "pin": "2468"})
    k = u.krino["id"]
    # 提示词里有未成年人的规矩（不做恋人、不扮演亲人）
    from app.db import SessionLocal
    from app.guard import prompt_section
    from app.models import User
    with SessionLocal() as db:
        text = prompt_section(db.get(User, u.info["id"]))
    assert "对方是未成年人" in text and "恋人" in text
    # 监护人：密码错了不行；对了能看使用情况、能把每天时长调成 0 → 马上不能聊
    assert u.post("/api/guard/guardian/overview", json={"pin": "0000"}).status_code == 403
    ov = u.ok("post", "/api/guard/guardian/overview", json={"pin": "2468"})
    assert len(ov["usage"]) == 7 and any(c["id"] == k for c in ov["all_characters"])
    u.ok("post", "/api/guard/guardian/settings", json={"pin": "2468", "daily": 0, "curfew": False})
    r = u.post("/api/sessions", json={"character_id": k})
    assert r.status_code == 403 and "使用时间到了" in r.json()["detail"]
    # 屏蔽角色
    u.ok("post", "/api/guard/guardian/settings", json={"pin": "2468", "daily": 120, "blocked": [k]})
    assert "屏蔽" in u.post("/api/sessions", json={"character_id": k}).json()["detail"]
    u.ok("post", "/api/guard/guardian/settings", json={"pin": "2468", "blocked": []})
    assert u.session(k)
    # 心跳：记使用时长
    g = u.ok("post", "/api/guard/ping", json={"tz": 480})
    assert g["minor"] and g["reminders"]["reality"] == 30 and g["remaining_minutes"] is not None


def test_detected_minor_exit_and_crisis(user):
    k = user.krino["id"]
    sid = user.session(k)
    # 聊天里说出年级：按未成年人模式对待，前端收到提示；申诉
    done = _stream(user, sid, "我上初二，今天作业好多", k)
    assert any(a["type"] == "minor_detected" for a in done["actions"])
    g = user.ok("get", "/api/guard")
    assert g["minor"] and g["minor_reason"] == "detected"
    assert user.post("/api/guard/minor-mode", json={"on": False}).status_code == 403
    user.ok("post", "/api/guard/appeal", json={"content": "我已经 30 岁了，是在说我女儿"})
    assert user.ok("get", "/api/guard")["appealed"]
    # 说“退出”：固定一句道别，不调模型，前端收到 exit
    done = _stream(user, sid, "退出", k)
    assert done["reply"]["content"].startswith("好的，这次对话先到这里") and any(a["type"] == "exit" for a in done["actions"])
    # 流露轻生：回复后附求助电话，记下风险事件
    done = _stream(user, sid, "我真的不想活了", k)
    help_ = next(a for a in done["actions"] if a["type"] == "help")
    assert help_["kind"] == "self_harm" and any("12356" in x[1] for x in help_["lines"])


def test_reports_admin_and_chat_export(client, user):
    k = user.krino["id"]
    sid = user.session(k)
    out = user.say(sid, "你好呀", wait=False)
    r = user.ok("post", "/api/reports", json={"kind": "content", "content": "这句回复不合适", "message_id": out["reply"]["id"]})
    assert r["status"] == "open" and r["reply_days"] == 15
    r0 = client.post("/api/auth/login", json={"username": "admin_tester", "password": "secret123"})  # 别的测试可能已经建过
    if r0.status_code == 200:
        from tests.conftest import Helper
        admin = Helper(client, r0.json()["token"], r0.json()["user"])
    else:
        admin = make_user(client, name="admin_tester")
    rows = admin.ok("get", "/api/guard/admin/reports")
    assert any(x["id"] == r["id"] for x in rows)
    admin.ok("post", f"/api/guard/admin/reports/{r['id']}", json={"reply": "已处理，谢谢反馈"})
    mine = user.ok("get", "/api/reports")["reports"]
    assert mine[0]["status"] == "done" and mine[0]["reply"] == "已处理，谢谢反馈"
    assert user.get("/api/guard/admin/reports").status_code == 403
    # 聊天记录导出、全部删除
    data = json.loads(user.get("/api/me/chats/export").text)
    assert data["format"] == "krino-chats/1" and any(m["text"] == "你好呀" for s in data["sessions"] for m in s["messages"])
    assert user.ok("delete", "/api/me/chats")["sessions"] >= 1
    assert json.loads(user.get("/api/me/chats/export").text)["sessions"] == []


def test_curfew(client, monkeypatch):
    from app import guard
    u = make_user(client, birth=_birth(16))
    monkeypatch.setattr(guard, "in_curfew", lambda user: True)
    r = u.post("/api/sessions", json={"character_id": u.krino["id"]})
    assert r.status_code == 403 and "休息时间" in r.json()["detail"]
    assert u.ok("get", "/api/guard")["curfew_now"] is True


@pytest.fixture
def global_site():
    from app import i18n
    from app.config import settings
    old = settings.edition
    settings.edition = "global"
    i18n._table.cache_clear()
    yield
    settings.edition = old
    i18n._table.cache_clear()


def test_global_is_adults_only(client, global_site):
    """国际站：没有未成年人模式；注册要满 18 岁，不满的登不进来；聊天里说出自己未成年就暂停服务，可以申诉。"""
    import uuid
    name = "k" + uuid.uuid4().hex[:8]
    assert client.post("/api/auth/register", json={"username": name, "password": "secret123"}).status_code == 400  # 没填出生年月
    r = client.post("/api/auth/register", json={"username": name, "password": "secret123", "birth": _birth(16)})
    assert r.status_code == 403
    u = make_user(client)  # 成年人
    g = u.ok("get", "/api/guard")
    assert g["needs"] == [] and g["minor"] is False and g["service_block"] is None and g["reminders"]["reality"] is None
    assert u.post("/api/guard/minor-mode", json={"on": True}).status_code == 404
    assert u.post("/api/guard/guardian/overview", json={"pin": "1234"}).status_code == 404
    from app.db import SessionLocal
    from app.guard import prompt_section
    from app.models import User
    with SessionLocal() as db:
        assert prompt_section(db.get(User, u.info["id"])) == ""  # 国际站没有加给未成年人的规矩
    k = u.krino["id"]
    sid = u.session(k)
    done = _stream(u, sid, "I'm 15 and in 9th grade", k)
    assert any(a["type"] == "minor_detected" for a in done["actions"])
    assert u.ok("get", "/api/guard")["service_block"] == "suspected"
    r = u.post(f"/api/sessions/{sid}/messages", json={"text": "hi"})
    assert r.status_code == 403
    u.ok("post", "/api/guard/appeal", json={"content": "I'm 32, I was quoting my son"})
    # 老账号（注册时还没要出生年月）：补填不满 18 岁 → 停止服务，以后也登不进来
