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


def test_event_write_never_hangs_on_a_locked_user(user):
    """有人锁着这个用户（比如正在删账号）时，记积分最多等 3 秒就放弃，不能把调用方一起卡死。"""
    import threading
    import time

    from sqlalchemy import text

    from app import events
    from app.db import SessionLocal
    holder = SessionLocal()
    holder.execute(text("SELECT id FROM users WHERE id = :u FOR UPDATE"), {"u": user.info["id"]})  # 像删账号一样锁住这一行
    done = threading.Event()
    t0 = time.time()
    threading.Thread(target=lambda: (credits.charge(user.info["id"], "llm", 0.01), done.set()), daemon=True).start()
    try:
        assert done.wait(10), "记积分卡住了"
        assert time.time() - t0 < 8
    finally:
        holder.rollback()
        holder.close()


def test_gpu_meter_splits_time_between_concurrent_requests(monkeypatch):
    """自建显卡按算力收：同一张卡上同时跑两个请求，这段时间两人平摊。"""
    clock = [100.0]
    monkeypatch.setattr(credits.time, "monotonic", lambda: clock[0])
    m = credits.GpuMeter("t")
    a = m.start()
    clock[0] += 2          # 只有 a：2 秒全算 a
    b = m.start()
    clock[0] += 4          # a、b 一起：各 2 秒
    assert m.stop(a) == 4
    clock[0] += 1          # 只剩 b
    assert m.stop(b) == 3
    monkeypatch.setattr(settings, "gpu_price_cny_hour", 6)
    assert credits.gpu_cny(3600) == 6


def test_self_hosted_asr_and_vision_are_charged_by_gpu_time(user, monkeypatch):
    from app import voice

    monkeypatch.setattr(settings, "gpu_price_cny_hour", 3600)  # 1 元 / 秒，好算
    monkeypatch.setattr(settings, "stt_provider", "openai")
    monkeypatch.setattr(settings, "stt_base_url", "http://127.0.0.1:18640/v1")
    monkeypatch.setattr(settings, "vlm_provider", "openai")
    monkeypatch.setattr(settings, "vlm_base_url", "http://127.0.0.1:18660/v1")
    monkeypatch.setattr(settings, "vlm_model", "qwen3-omni")
    clock = [0.0]
    monkeypatch.setattr(credits.time, "monotonic", lambda: clock[0])

    def handler(req):
        clock[0] += 0.5    # 每次在显卡上跑 0.5 秒
        if req.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "你好"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "一只猫"}}]})

    real = httpx.Client
    monkeypatch.setattr(voice.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert voice.transcribe(b"x", "audio/wav", payer=user.info["id"]) == "你好"
    assert voice.describe_image(b"x", "image/png", payer=user.info["id"]) == "一只猫"
    assert user.ok("get", "/api/credits")["spent"] == 10  # 两次各 0.5 元 = 10 积分
