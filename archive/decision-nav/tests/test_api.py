import json


def register(client, email="a@example.com", password="password123"):
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def turn(client, **body):
    r = client.post("/api/turns", json=body)
    assert r.status_code == 200, r.text
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def test_auth_required(client):
    assert client.get("/api/conversations").status_code == 401


def test_register_login_and_rate_limit(client):
    register(client)
    client.post("/api/auth/logout")
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "password123"}).status_code == 429


def test_full_decision_flow(client):
    register(client)
    events = turn(client, text="我想转行做数据分析")
    assert events[0]["type"] == "conversation"
    assert [e["stage"] for e in events if e["type"] == "stage"] == ["understand", "clarify"]
    question = events[-1]
    assert question["type"] == "clarification"
    cid = events[0]["id"]

    events = turn(client, conversation_id=cid, answer={"question_id": "sql_level", "values": ["入门"]})
    decision = events[-1]
    assert decision["type"] == "decision" and decision["best_action"] == "build_portfolio"
    did = decision["decision_id"]

    # the user picks a non-recommended action, then reports the outcome later
    r = client.put(f"/api/decisions/{did}/feedback",
                   json={"chosen_action": "apply_internal", "status": "chosen", "reason": "主管支持"})
    assert r.json()["feedback"]["chose_recommended"] is False
    r = client.put(f"/api/decisions/{did}/feedback", json={"executed": "yes", "helpful": "partly"})
    fb = r.json()["feedback"]
    assert fb["chosen_action"] == "apply_internal" and fb["executed"] == "yes" and fb["reason"] == "主管支持"

    conversation = client.get(f"/api/conversations/{cid}").json()
    assert [m["kind"] for m in conversation["messages"]] == ["objective", "clarification", "answer", "decision"]
    snapshot = conversation["messages"][-1]["decision"]
    assert snapshot["answers"][0]["values"] == ["入门"] and snapshot["model_version"].startswith("fake-llm")
    assert len(snapshot["response"]["actions"]) == 3

    assert client.get("/api/conversations", params={"q": "数据分析"}).json()[0]["id"] == cid
    assert client.get("/api/account/status").json()["usage"]["turns_today"] == 2


def test_skip_question_and_decide_now(client):
    register(client)
    cid = turn(client, text="我想转行做数据分析")[0]["id"]
    events = turn(client, conversation_id=cid, decide_now=True)
    assert events[-1]["type"] == "decision"
    answers = client.get(f"/api/conversations/{cid}").json()["messages"][2]["answer"]
    assert answers["skipped"] is True


def test_users_are_isolated(client):
    register(client, "a@example.com")
    cid = turn(client, text="目标 A")[0]["id"]
    mid = client.post("/api/memories", json={"text": "我在上海"}).json()["id"]
    client.post("/api/auth/logout")
    register(client, "b@example.com")
    assert client.get(f"/api/conversations/{cid}").status_code == 404
    assert client.delete(f"/api/conversations/{cid}").status_code == 404
    assert client.patch(f"/api/memories/{mid}", json={"text": "x"}).status_code == 404
    assert client.get("/api/conversations").json() == []
    assert client.post("/api/turns", json={"conversation_id": cid, "text": "hi"}).status_code == 404


def test_memories_and_delete(client):
    register(client)
    mid = client.post("/api/memories", json={"text": "我在上海"}).json()["id"]
    assert client.patch(f"/api/memories/{mid}", json={"text": "我在杭州"}).json()["text"] == "我在杭州"
    cid = turn(client, text="找房子")[0]["id"]
    assert client.delete(f"/api/memories/{mid}").json()["ok"]
    assert client.get("/api/memories").json() == []
    assert client.delete(f"/api/conversations/{cid}").json()["ok"]
    assert client.get("/api/conversations").json() == []


def test_quota(client, monkeypatch):
    from backend.config import settings
    monkeypatch.setattr(settings, "daily_quota", 1)
    register(client)
    turn(client, text="目标")
    events = turn(client, text="另一个目标")
    assert events == [events[0]] and events[0]["type"] == "error" and events[0]["code"] == "quota_exceeded"


def test_engine_unavailable(client):
    from backend.main import app

    def broken():
        raise KeyError("LLM_DEFAULT")
    app.state.engine_factory = broken
    register(client)
    events = turn(client, text="目标")
    assert events[-1]["type"] == "error" and events[-1]["code"] == "model_unavailable"
    cid = events[0]["id"]
    assert client.get(f"/api/conversations/{cid}").json()["messages"][-1]["kind"] == "error"


def test_password_reset(client, caplog):
    register(client)
    client.post("/api/auth/logout")
    with caplog.at_level("WARNING", logger="krino"):
        assert client.post("/api/auth/reset/request", json={"email": "a@example.com"}).json()["ok"]
    token = caplog.text.split("token=")[1].split()[0]
    assert client.post("/api/auth/reset/confirm", json={"token": token, "password": "newpassword1"}).status_code == 200
    assert client.post("/api/auth/reset/confirm", json={"token": token, "password": "newpassword2"}).status_code == 400
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"email": "a@example.com", "password": "newpassword1"}).status_code == 200


def test_style_settings(client):
    register(client)
    assert client.get("/api/account/style").json() == {"tone": "pilot", "persona": "calm", "pace": "balanced"}
    r = client.put("/api/account/style", json={"tone": "chat", "persona": "tsundere", "pace": "direct"})
    assert r.status_code == 200
    assert client.get("/api/account/style").json() == {"tone": "chat", "persona": "tsundere", "pace": "direct"}
    assert client.put("/api/account/style", json={"tone": "shout"}).status_code == 422
