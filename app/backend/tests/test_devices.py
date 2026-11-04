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


def test_adapters_listed(user):
    st = user.ok("get", "/api/devices")
    kinds = {a["kind"]: a for a in st["adapters"]}
    assert kinds["glasses-sim"]["available"] and not kinds["krino-glasses"]["available"]
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
        msgs = [ws.receive_json() for _ in range(3)]
        types = [m["type"] for m in msgs]
        assert types[0] == "busy" and set(types[1:]) == {"ar", "result"}
        ar = next(m for m in msgs if m["type"] == "ar")["events"]
        assert ar[0]["type"] == "ar.avatar" and ar[0]["anchor"]["distance"] == 1.5
        assert any(e["type"] == "ar.subtitle" and e["speaker"] == "大肥鱼" for e in ar)

        ws.send_json({"type": "camera.frame", "image": _frame(), "question": "我在哪"})
        msgs = [ws.receive_json() for _ in range(3)]
        result = next(m for m in msgs if m["type"] == "result")
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
