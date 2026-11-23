"""实时语音：被打断时只留下你听到的那部分；要查网时她先说一声；语音不等识别结果就开始听。"""
import json

from app import chat
from app.db import SessionLocal

from .test_web import _wav


def _events(body: str) -> list[tuple[str, dict]]:
    out = []
    for block in body.split("\n\n"):
        if block.startswith("event: "):
            head, _, data = block.partition("\ndata: ")
            out.append((head[7:], json.loads(data)))
    return out


def test_cut_at_follows_what_was_actually_said():
    full = "(｡･ω･｡) 今天好累呀，不过看到你就开心多了。要不要一起去散步？"
    heard = "今天好累呀，不过看到你就开心多了。"  # 念的时候去掉了颜文字
    pos = chat.cut_at(full, heard)
    assert full[:pos].endswith("开心多了。") and "散步" not in full[:pos]
    assert chat.cut_at(full, "") == 0
    assert chat.cut_at(full, "完全不相干的一句话") <= 12  # 对不上的字跳过，不会一下跳到末尾
    assert chat.cut_at("abc", "abc") == 3


def test_interrupted_reply_keeps_only_what_you_heard(user, other):
    k = user.krino["id"]
    sid = user.session(k)
    r = user.say(sid, "你好呀", wait=False)
    reply = r["reply"]
    full = reply["content"]
    heard = chat.cut_at(full, full) and full[: max(2, len(full) // 2)]
    m = user.ok("post", f"/api/sessions/{sid}/messages/{reply['id']}/heard", json={"heard": heard})
    assert m["meta"]["interrupted"] is True and m["meta"]["full"] == full
    assert m["content"].endswith("……") and len(m["content"]) < len(full) + 2
    assert full.startswith(m["content"][:-2].rstrip("，,、"))  # 只能截短她自己的原话
    # 下一轮她知道自己被打断了
    db = SessionLocal()
    try:
        user.say(sid, "等一下，我想说", wait=False)
        hist = chat._history(db, sid)
    finally:
        db.close()
    assert any(h["role"] == "user" and h["content"].startswith("（对方打断了你）等一下") for h in hist)
    assert any(h["role"] == "assistant" and h["content"] == m["content"] for h in hist)
    # 再报一次（比如晚到的重复请求）：还是按原文截，不会越截越短
    again = user.ok("post", f"/api/sessions/{sid}/messages/{reply['id']}/heard", json={"heard": heard})
    assert again["content"] == m["content"]
    # 别人的回复、你自己说的话：不能改
    assert other.post(f"/api/sessions/{sid}/messages/{reply['id']}/heard", json={"heard": ""}).status_code == 404
    assert user.post(f"/api/sessions/{sid}/messages/{r['user']['id']}/heard", json={"heard": ""}).status_code == 404


def test_heard_everything_changes_nothing(user):
    k = user.krino["id"]
    sid = user.session(k)
    reply = user.say(sid, "你好呀", wait=False)["reply"]
    m = user.ok("post", f"/api/sessions/{sid}/messages/{reply['id']}/heard", json={"heard": reply["content"]})
    assert m["content"] == reply["content"] and not (m["meta"] or {}).get("interrupted")


def test_voice_web_question_says_wait_a_moment_first(user, monkeypatch):
    """语音问要查的事：先推一句“我查一下”（只念，不进记录），再推联网的回答；平常的话不说这句。"""
    k = user.krino["id"]
    sid = user.session(k)
    monkeypatch.setattr(chat, "transcribe_for_record", lambda *a, **kw: "帮我查一下今天杭州天气")
    evs = _events(user.post(f"/api/sessions/{sid}/stream", json={"audio": _wav(), "character_id": k}).text)
    names = [e for e, _ in evs]
    assert "filler" in names and names.index("filler") < names.index("delta")
    done = dict(evs)["done"]
    assert dict(evs)["filler"]["text"] == "我查一下哦。"
    assert "我查一下哦" not in done["reply"]["content"] and "模拟联网" in done["reply"]["content"]

    monkeypatch.setattr(chat, "transcribe_for_record", lambda *a, **kw: "今天有点累")
    evs = _events(user.post(f"/api/sessions/{sid}/stream", json={"audio": _wav(), "character_id": k}).text)
    assert "filler" not in [e for e, _ in evs] and "我听见了" in dict(evs)["done"]["reply"]["content"]


def test_hearing_starts_before_transcript_is_back(user, monkeypatch):
    """不等识别结果：识别慢的时候，她已经在直接听着回答了（识别只用来判断要不要联网）。"""
    import threading
    import time

    from app import llm

    k = user.krino["id"]
    sid = user.session(k)
    gate = threading.Event()
    started = []

    def slow_transcript(*a, **kw):
        gate.wait(5)
        return "今天有点累"

    hear = llm.get_hear_llm() or llm.get_llm()
    orig = type(hear).stream

    def spy(self, **kw):
        started.append(time.perf_counter())
        gate.set()  # 模型开始听了，识别才回来
        yield from orig(self, **kw)

    monkeypatch.setattr(chat, "transcribe_for_record", slow_transcript)
    monkeypatch.setattr(type(hear), "stream", spy)
    t0 = time.perf_counter()
    r = user.post(f"/api/sessions/{sid}/stream", json={"audio": _wav(), "character_id": k})
    assert started and started[0] - t0 < 3, "她要等识别结果回来才开始听"
    assert "我听见了" in dict(_events(r.text))["done"]["reply"]["content"]


def test_voice_with_frame_lets_her_see_only_when_camera_allowed(user, monkeypatch):
    """AR / 眼镜：说话时带一帧眼前的画面，和录音一起交给能听的模型（不单独识图）；没允许摄像头就不给她看。"""
    import base64
    import io

    from PIL import Image
    from app import llm as llm_mod

    buf = io.BytesIO()
    Image.new("RGB", (32, 24), "red").save(buf, "JPEG")
    frame = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    seen = []
    real = llm_mod.get_hear_llm()

    class Spy:
        def stream(self, *, system, messages, max_tokens=None, context=None):
            seen.append(((context or {}).get("image"), "眼前的画面" in system))
            yield from real.stream(system=system, messages=messages, max_tokens=max_tokens, context=context)

    monkeypatch.setattr(chat, "get_hear_llm", lambda: Spy())
    from app import voice
    monkeypatch.setattr(voice, "describe_image", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("不该单独识图")))
    k = user.krino["id"]
    sid = user.session(k)
    body = {"audio": _wav(), "image": frame, "character_id": k}

    evs = _events(user.post(f"/api/sessions/{sid}/stream", json=body).text)  # 默认没允许摄像头
    assert any(e == "done" for e, _ in evs) and seen[-1] == (None, False)

    user.ok("patch", "/api/me", json={"privacy": {"camera": True}})
    evs = _events(user.post(f"/api/sessions/{sid}/stream", json=body).text)
    done = next(d for e, d in evs if e == "done")
    assert seen[-1][0] == frame and seen[-1][1]
    assert done["user"]["meta"]["glance"] is True
