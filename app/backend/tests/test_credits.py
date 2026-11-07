"""积分：对话、图片、语音的花费折成积分（1 元 = 10 积分），按账号每天限额。"""
import json

import httpx

from app import credits, llm
from app.config import settings


def test_points_and_llm_cost(monkeypatch):
    monkeypatch.setattr(settings, "usd_cny", 7.0)
    assert credits.points(100) == 1000                                    # 100 元 = 1000 积分
    assert credits.llm_cost_cny({"cost": 0.01}) == 0.07                   # OpenRouter 给了实际花费（美元）
    monkeypatch.setattr(settings, "llm_price_in", 2)
    monkeypatch.setattr(settings, "llm_price_out", 8)
    assert credits.llm_cost_cny({"prompt_tokens": 1_000_000, "completion_tokens": 500_000}) == 6  # 没给就按单价估


def test_daily_limit_blocks_chat_image_and_voice(user, other, monkeypatch):
    monkeypatch.setattr(settings, "credit_user_limits", {user.info["username"]: 1000})  # 测试账号每天 100 元
    info = user.ok("get", "/api/credits")
    assert info["limit"] == 1000 and info["spent"] == 0
    sid = user.session(user.official["id"])
    user.say(sid, "你好", wait=False)                    # 没超：照常聊
    credits.charge(user.info["id"], "image", 100.0)      # 花掉 100 元
    assert user.ok("get", "/api/credits")["spent"] == 1000
    r = user.post(f"/api/sessions/{sid}/messages", json={"text": "还在吗"})
    assert r.status_code == 429 and "积分" in r.json()["detail"]
    assert user.post("/api/workbench/design", json={"prompt": "蓝发", "n": 1}).status_code == 429
    assert user.post("/api/voice/tts", json={"text": "你好"}).status_code == 429
    # 没单独设的账号不受影响（默认不限）
    osid = other.session(other.official["id"])
    other.say(osid, "你好", wait=False)


def test_openrouter_usage_is_charged(user, monkeypatch):
    """普通调用和流式调用都按 OpenRouter 返回的实际花费记账，记在 context 里的 payer 头上。"""
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "usd_cny", 7.0)

    def handler(req):
        body = json.loads(req.content)
        assert body["usage"] == {"include": True}
        usage = {"prompt_tokens": 100, "completion_tokens": 20, "cost": 0.01}
        if body.get("stream"):
            chunks = [{"choices": [{"delta": {"content": "嗨"}}]}, {"choices": [{"delta": {}}], "usage": usage}]
            return httpx.Response(200, text="".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n")
        return httpx.Response(200, json={"model": "m", "choices": [{"message": {"content": "嗨"}}], "usage": usage})

    real = httpx.Client
    monkeypatch.setattr(llm.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    o = llm.OpenRouterLLM()
    o.complete(system="s", messages=[{"role": "user", "content": "hi"}], context={"payer": user.info["id"]})
    assert "".join(o.stream(system="s", messages=[{"role": "user", "content": "hi"}], context={"payer": user.info["id"]})) == "嗨"
    assert user.ok("get", "/api/credits")["spent"] == 1.4  # 两次各 0.07 元 = 0.7 积分
