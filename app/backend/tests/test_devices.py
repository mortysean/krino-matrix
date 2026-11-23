"""KRINO GLASSES 模拟器：设备输入（文字 / 画面 / 头部姿态）→ 互动流程 → 结构化 AR 输出事件。"""
import base64
import io

import pytest
from PIL import Image
from pydantic import ValidationError

from app import devices


def _frame() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (230, 230, 230)).save(buf, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _turn(ws) -> list[dict]:
    """收完一轮：ar.clear → busy → delta… / ar → result（或 error）。"""
    msgs = []
    while not msgs or msgs[-1]["type"] not in ("result", "error"):
        msgs.append(ws.receive_json())
    return msgs


def test_adapters_listed(user):
    st = user.ok("get", "/api/devices")
    kinds = {a["kind"]: a for a in st["adapters"]}
    assert kinds["glasses-sim"]["available"] and kinds["glasses-desktop"]["available"] and not kinds["krino-glasses"]["available"]
    assert st["devices"] == []


def test_glasses_simulator_roundtrip(user):
    cid = user.official["id"]
    with user.c.websocket_connect(f"/api/devices/ws?token={user.token}&kind=glasses-sim") as ws:
        assert ws.receive_json()["state"] == "connected"
        ws.send_json({"type": "hello", "character_id": cid})
        assert ws.receive_json()["character_id"] == cid
        assert user.ok("get", "/api/devices")["devices"][0]["kind"] == "glasses-sim"
        ws.send_json({"type": "imu.pose", "yaw": 400, "pitch": 10, "roll": "x"})
        ws.send_json({"type": "heartbeat"})
        assert ws.receive_json()["type"] == "heartbeat"
        assert user.ok("get", "/api/devices")["devices"][0]["pose"] == {"yaw": 180.0, "pitch": 10.0, "roll": 0.0}

        ws.send_json({"type": "mic.text", "text": "你好呀"})
        msgs = _turn(ws)
        types = [m["type"] for m in msgs]
        assert msgs[0] == {"type": "ar", "events": [{"type": "ar.clear"}]} and types[1] == "busy" and types[-1] == "result"
        deltas = "".join(m["text"] for m in msgs if m["type"] == "delta")
        assert deltas and deltas.strip() in msgs[-1]["reply"]  # 字幕边生成边推，拼起来就是回复
        assert types.index("delta") < types.index("result")
        ar = [m for m in msgs if m["type"] == "ar"][-1]["events"]
        # 头转到了 180°（正后方），她原本在 20°：要开口时走到眼前
        assert ar[0]["type"] == "ar.avatar" and ar[0]["anchor"] == {"yaw": -160.0, "pitch": 5.0, "distance": 1.5}
        assert any(e["type"] == "ar.subtitle" and e["speaker"] == "大肥鱼" for e in ar)

        ws.send_json({"type": "anchor.set", "yaw": 190, "pitch": 80, "distance": 9})  # 越界的值被夹住
        placed = ws.receive_json()["events"][0]
        assert placed["type"] == "ar.avatar" and placed["anchor"] == {"yaw": -180.0, "pitch": 45.0, "distance": 5.0}
        assert user.ok("get", "/api/devices")["devices"][0]["anchor"] == placed["anchor"]

        ws.send_json({"type": "camera.frame", "image": _frame(), "question": "我在哪"})
        result = _turn(ws)[-1]
        assert result["decision"]["actions"][0] == "PERCEIVE" and result["reply"]

        ws.send_json({"type": "rm -rf"})
        assert ws.receive_json()["type"] == "error"
    assert user.ok("get", "/api/devices")["devices"] == []
    # 设备输入也进了聊天记录
    sessions = user.ok("get", "/api/sessions", params={"character_id": cid})
    msgs = user.ok("get", f"/api/sessions/{sessions[0]['id']}")["messages"]
    assert any(m["role"] == "event" and m["meta"].get("source") == "glasses" for m in msgs)


def test_real_glasses_not_available_and_bad_token(client, user):
    with user.c.websocket_connect(f"/api/devices/ws?token={user.token}&kind=krino-glasses") as ws:
        assert "SDK" in ws.receive_json()["message"]
    with client.websocket_connect("/api/devices/ws?token=nope") as ws:
        assert ws.receive_json()["type"] == "error"


def test_she_stays_in_the_world_and_comes_over_only_to_talk():
    here = {"yaw": 20.0, "pitch": -5.0, "distance": 2.0}
    assert devices.follow(here, {"yaw": 0, "pitch": 0}) == here                    # 看得到她：待在原地
    assert devices.follow(here, {"yaw": -90, "pitch": 0}) == {"yaw": -70.0, "pitch": -5.0, "distance": 2.0}
    assert devices.follow({"yaw": 170.0, "pitch": 0.0, "distance": 1.5}, {"yaw": -170, "pitch": 0})["yaw"] == 170.0  # 跨过 ±180 也算看得到
    away = {"yaw": 0, "pitch": 0}
    assert devices.to_ar("K", [{"type": "emote", "expression": "happy"}], {"yaw": 120}, here)[0]["anchor"] == here  # 不说话就不走过来
    assert devices.to_ar("K", [{"type": "say", "text": "嗨"}], {"yaw": 120}, here)[0]["anchor"]["yaw"] == 140.0
    assert devices.to_ar("K", [{"type": "say", "text": "嗨"}], away, here)[0]["anchor"] == here


def test_desktop_glasses_connects(user):
    with user.c.websocket_connect(f"/api/devices/ws?token={user.token}&kind=glasses-desktop") as ws:
        st = ws.receive_json()
        assert st["kind"] == "glasses-desktop" and st["state"] == "connected" and st["anchor"]["distance"] == 1.5


def test_ar_events_are_validated():
    evs = devices.to_ar("大肥鱼", [{"type": "say", "text": "嗨" * 500}, {"type": "emote", "expression": "happy"},
                                  {"type": "remember_suggest", "candidate_id": "x", "content": "一起看日落"}], {})
    assert evs[0] == {"type": "ar.avatar", "expression": "happy", "animation": None,
                      "anchor": {"yaw": 20.0, "pitch": -5.0, "distance": 1.5}}
    assert len(evs[1]["text"]) == 198 and evs[1]["ttl_ms"] == 15000
    assert evs[2]["kind"] == "memory"
    with pytest.raises(ValidationError):
        devices._ar.validate_python([{"type": "ar.shader", "code": "..."}])
    with pytest.raises(ValidationError):
        devices._ar.validate_python([{"type": "ar.avatar", "anchor": {"yaw": 0, "pitch": 0, "distance": 99}}])


def test_glasses_input_respects_the_daily_limit(user, monkeypatch):
    """眼镜说的话和聊天一样计额度：超了就不回复，不能绕过聊天接口白用。"""
    from app import credits
    from app.config import settings
    monkeypatch.setattr(settings, "credit_user_limits", {user.info["username"]: 1000})
    credits.charge(user.info["id"], "image", 100.0)
    with user.c.websocket_connect(f"/api/devices/ws?token={user.token}&kind=glasses-desktop") as ws:
        ws.receive_json()
        ws.send_json({"type": "hello", "character_id": user.official["id"]})
        ws.receive_json()
        ws.send_json({"type": "mic.text", "text": "你好呀"})
        last = _turn(ws)[-1]
        assert last["type"] == "error" and "积分" in last["message"]
