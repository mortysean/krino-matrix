"""联网：聊天回复时带上 OpenRouter 的搜索工具，来源存进回复，正文里不留网址；用户和服务端都能关。"""
import json

import httpx

from app import llm
from app.config import settings
from app.prompt import StreamFilter, strip_links


def test_reply_cites_sources_without_urls(user):
    sid = user.session(user.official["id"])
    r = user.say(sid, "帮我查一下今天杭州天气", wait=False)
    reply = r["reply"]
    assert "模拟联网" in reply["content"] and "http" not in reply["content"] and "example.com" not in reply["content"]
    assert reply["meta"]["sources"] == [{"url": "https://example.com/search", "title": "（模拟）搜索结果"}]


def test_user_can_turn_web_off(user):
    user.ok("patch", "/api/me", json={"interaction": {"web": False}})
    sid = user.session(user.official["id"])
    reply = user.say(sid, "帮我查一下今天杭州天气", wait=False)["reply"]
    assert "模拟联网" not in reply["content"] and not reply["meta"]["sources"]


def test_strip_links_keeps_normal_brackets():
    assert strip_links("小雨 [nmc.cn](https://www.nmc.cn/a)。带伞") == "小雨。带伞"
    assert strip_links("答案是 3（三）个 [好]") == "答案是 3（三）个 [好]"
    f = StreamFilter()
    out = "".join(f.feed(c) for c in ["小雨 [nm", "c.cn](https://www.n", "mc.cn/a)。带伞", "<state>{}</state>"])
    assert "http" not in out and "nmc" not in out


def test_openrouter_gets_tool_and_falls_back(monkeypatch):
    """只有 context.web 时带搜索工具；拿到 url_citation 就记成来源；工具不被支持（400）时去掉工具再来一次。"""
    monkeypatch.setattr(settings, "llm_api_key", "k")
    seen = []

    def handler(req):
        body = json.loads(req.content)
        seen.append(body.get("tools"))
        if body.get("tools") and fail[0]:
            return httpx.Response(400, json={"error": {"message": "tools not supported"}})
        ann = [{"type": "url_citation", "url_citation": {"url": "https://nmc.cn/a", "title": "气象台"}}] if body.get("tools") else []
        return httpx.Response(200, json={"choices": [{"message": {"content": "小雨", "annotations": ann}}], "usage": {}})

    real = httpx.Client
    monkeypatch.setattr(llm.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    o = llm.OpenRouterLLM()
    fail = [False]
    ctx = {"web": True, "sources": []}
    r = o.complete(system="s", messages=[{"role": "user", "content": "天气"}], context=ctx)
    assert seen[-1][0]["type"] == "openrouter:web_search" and ctx["sources"] == [{"url": "https://nmc.cn/a", "title": "气象台"}]
    o.complete(system="s", messages=[{"role": "user", "content": "hi"}], context={"task": "summary"})
    assert seen[-1] is None  # 后台任务不联网
    fail[0] = True
    r = o.complete(system="s", messages=[{"role": "user", "content": "天气"}], context={"web": True, "sources": []})
    assert r.text == "小雨" and seen[-2] and seen[-1] is None


def _wav(seconds=1.0):
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    import base64
    return "data:audio/wav;base64," + base64.b64encode(buf.getvalue()).decode()


def test_she_hears_voice_directly(user):
    """语音：录音直接交给能听的模型，不先转文字；她听到的原话存成你这句话，<heard> 不出现在回复里，也不会被念出来。"""
    k = user.krino["id"]
    sid = user.session(k)
    assert user.ok("get", "/api/voice/config")["hear"] is True
    r = user.post(f"/api/sessions/{sid}/stream", json={"audio": _wav(), "character_id": k})
    assert r.status_code == 200
    body = r.text
    assert "<heard>" not in body.split("event: done")[0]  # 流式文字里没有
    done = json.loads(body.split("event: done\ndata: ")[1].split("\n")[0])
    assert done["user"]["content"].startswith("（模拟听到的话）") and done["user"]["meta"]["audio"] is True
    assert "我听见了" in done["reply"]["content"] and "heard" not in done["reply"]["content"]
    # 不是 WAV、太长、什么都没有：拒绝
    assert user.post(f"/api/sessions/{sid}/stream", json={"audio": "data:audio/wav;base64,AAAA", "character_id": k}).status_code == 400
    assert user.post(f"/api/sessions/{sid}/stream", json={"audio": _wav(70), "character_id": k}).status_code == 413
    assert user.post(f"/api/sessions/{sid}/stream", json={"character_id": k}).status_code == 400
