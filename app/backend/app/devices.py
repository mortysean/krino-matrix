"""KRINO GLASSES 兼容层：统一的 Device Adapter + 浏览器眼镜模拟器 + AR 显示事件。

当前没有真实眼镜通信。首版用浏览器的摄像头、麦克风和一个 3D 场景模拟器（前端“眼镜模拟器”页）当作设备，
通过 WebSocket 接入；以后接入设备 SDK 时，新写一个 DeviceAdapter 子类注册到 ADAPTERS 即可。

    设备输入  camera.frame / mic.text / mic.audio（她直接听）/ imu.pose / heartbeat   → 互动流程（chat.py）
    设备输出  AR 显示事件（结构化、白名单、有范围限制）         ← 角色行为（say / emote / animate / …）
模型不会直接操作渲染：AR 事件只由 present() 根据已经执行的行为生成，并在发出前逐条校验。
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from abc import ABC
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from . import events
from .auth import current_user, user_from_token
from .config import settings
from .db import SessionLocal
from .models import Character, User

log = logging.getLogger("krino.devices")
router = APIRouter(prefix="/api/devices", tags=["devices"])


# ---------- AR 显示事件 ----------

class Anchor(BaseModel):
    """角色在用户周围的位置：相对用户头部的水平角、俯仰角（度）和距离（米）。"""
    yaw: float = Field(ge=-180, le=180)
    pitch: float = Field(ge=-45, le=45)
    distance: float = Field(ge=0.5, le=5)


class ARSubtitle(BaseModel):
    type: Literal["ar.subtitle"] = "ar.subtitle"
    speaker: str = Field(max_length=40)
    text: str = Field(max_length=200)
    ttl_ms: int = Field(default=6000, ge=500, le=15000)


class ARAvatar(BaseModel):
    type: Literal["ar.avatar"] = "ar.avatar"
    expression: str | None = Field(default=None, max_length=16)
    animation: str | None = Field(default=None, max_length=16)
    anchor: Anchor


class ARPanel(BaseModel):
    type: Literal["ar.panel"] = "ar.panel"
    kind: Literal["memory", "perceive", "story"]
    title: str = Field(max_length=40)
    body: str = Field(max_length=200)
    ttl_ms: int = Field(default=8000, ge=500, le=20000)


class ARClear(BaseModel):
    type: Literal["ar.clear"] = "ar.clear"


AREvent = Annotated[ARSubtitle | ARAvatar | ARPanel | ARClear, Field(discriminator="type")]
_ar = TypeAdapter(list[AREvent])


def to_ar(char_name: str, actions: list[dict], pose: dict) -> list[dict]:
    """角色行为 → AR 事件。角色默认站在用户正前方偏右 20°、1.5 米处，跟随世界坐标（不随头转）。"""
    anchor = {"yaw": 20.0, "pitch": -5.0, "distance": 1.5}
    out: list[dict] = []
    avatar: dict = {}
    for a in actions:
        t = a.get("type")
        if t == "say":
            text = a["text"]
            out.append({"type": "ar.subtitle", "speaker": char_name, "text": text[:197] + "…" if len(text) > 200 else text,
                        "ttl_ms": min(15000, 2500 + 120 * len(text))})
            if a.get("story"):
                out.append({"type": "ar.panel", "kind": "story", "title": "幻想剧情", "body": "这段是虚构故事"})
        elif t == "emote":
            avatar["expression"] = a["expression"]
        elif t == "animate":
            avatar["animation"] = a["name"]
        elif t == "remember_suggest":
            out.append({"type": "ar.panel", "kind": "memory", "title": "要记下这段经历吗？", "body": a["content"][:200]})
        elif t == "perceive_request":
            out.append({"type": "ar.panel", "kind": "perceive", "title": "想看看你那边", "body": "在模拟器里点“分享画面”"})
    out.insert(0, {"type": "ar.avatar", **avatar, "anchor": anchor})
    return [e.model_dump() for e in _ar.validate_python(out)]


# ---------- 设备适配器 ----------

@dataclass
class Capabilities:
    camera: bool = False
    microphone: bool = False
    speaker: bool = False
    ar_display: bool = False
    imu: bool = False


class DeviceUnavailable(RuntimeError):
    pass


class DeviceAdapter(ABC):
    """一台设备：摄像头 / 麦克风输入，扬声器 / AR 显示输出，头部姿态，连接状态。"""

    kind = "base"
    label = ""
    available = True
    note = ""
    capabilities = Capabilities()

    def connect(self) -> None:  # 真机：握手、配对
        if not self.available:
            raise DeviceUnavailable(self.note or "设备不可用")


class GlassesSimulator(DeviceAdapter):
    """浏览器里的眼镜模拟器：摄像头 = getUserMedia，麦克风 = 浏览器语音识别，AR 显示 = 页面上的叠加层。"""

    kind = "glasses-sim"
    label = "KRINO GLASSES 模拟器（浏览器）"
    capabilities = Capabilities(camera=True, microphone=True, speaker=True, ar_display=True, imu=True)


class KrinoGlasses(DeviceAdapter):
    """真机占位：设备 SDK 接入后实现 connect / 输入输出。"""

    kind = "krino-glasses"
    label = "KRINO GLASSES"
    available = False
    note = "真机 SDK 尚未接入"
    capabilities = Capabilities(camera=True, microphone=True, speaker=True, ar_display=True, imu=True)


ADAPTERS: dict[str, type[DeviceAdapter]] = {a.kind: a for a in (GlassesSimulator, KrinoGlasses)}


@dataclass
class Connection:
    id: str
    user_id: str
    adapter: DeviceAdapter
    queue: asyncio.Queue
    character_id: str | None = None
    pose: dict = field(default_factory=lambda: {"yaw": 0.0, "pitch": 0.0, "roll": 0.0})
    connected_at: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)

    def state(self) -> str:
        return "connected" if time.time() - self.last_seen <= settings.device_heartbeat_timeout_s else "stale"

    def out(self) -> dict:
        return {"id": self.id, "kind": self.adapter.kind, "label": self.adapter.label, "state": self.state(),
                "capabilities": self.adapter.capabilities.__dict__, "pose": self.pose, "character_id": self.character_id,
                "last_seen_s": round(time.time() - self.last_seen, 1)}


class Hub:
    """进程内的设备连接表（单 worker）。业务线程通过 present() 把 AR 事件交给事件循环里的 WebSocket。"""

    def __init__(self) -> None:
        self.conns: dict[str, Connection] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    def add(self, c: Connection) -> None:
        self.conns[c.id] = c

    def remove(self, cid: str) -> None:
        self.conns.pop(cid, None)

    def of(self, user_id: str) -> list[Connection]:
        return [c for c in self.conns.values() if c.user_id == user_id]

    def status(self, user_id: str) -> dict:
        return {"devices": [c.out() for c in self.of(user_id)],
                "adapters": [{"kind": a.kind, "label": a.label, "available": a.available, "note": a.note,
                              "capabilities": a.capabilities.__dict__} for a in ADAPTERS.values()]}

    def send(self, c: Connection, msg: dict) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(c.queue.put_nowait, msg)

    def present(self, user_id: str, char: Character, actions: list[dict]) -> list[dict]:
        """把这一轮的行为转成 AR 事件，发给这个用户连着的、有 AR 显示的设备。没有设备时返回空列表。"""
        targets = [c for c in self.of(user_id) if c.adapter.capabilities.ar_display
                   and (c.character_id in (None, char.id))]
        if not targets:
            return []
        try:
            evs = to_ar(char.name, actions, targets[0].pose)
        except ValidationError as e:
            events.error("ar", f"AR 事件校验失败：{e.errors()[:1]}")
            return []
        for c in targets:
            self.send(c, {"type": "ar", "events": evs})
        events.record("ar", "present", user_id=user_id, character_id=char.id,
                      payload={"types": [e["type"] for e in evs], "devices": len(targets)})
        return evs


hub = Hub()


# ---------- 接口 ----------

@router.get("")
def status(user: User = Depends(current_user)):
    return hub.status(user.id)


class TestAR(BaseModel):
    text: str = Field(default="AR 显示测试：看得到我吗？", max_length=120)


@router.post("/test-ar")
def test_ar(body: TestAR, user: User = Depends(current_user)):
    """给连着的模拟器发一组测试 AR 事件。"""
    char = Character(persona={"name": "KRINO"}, slug="test", behavior={})
    evs = hub.present(user.id, char, [{"type": "say", "text": body.text}, {"type": "emote", "expression": "happy"},
                                      {"type": "animate", "name": "wave"}])
    return {"sent": len(evs) > 0, "events": evs}


def _clamp(v, lo, hi) -> float:
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return 0.0


def _handle_input(conn: Connection, msg: dict) -> dict | None:
    """设备输入 → 互动流程。在线程池里跑（会访问数据库、调模型）。"""
    from . import chat
    from .models import ChatSession

    db = SessionLocal()
    try:
        user = db.get(User, conn.user_id)
        cid = conn.character_id
        char = db.get(Character, cid) if cid else None
        if char is None or char.owner_id != user.id:
            return {"type": "error", "message": "先在模拟器里选一位角色"}
        sess = db.query(ChatSession).filter(ChatSession.user_id == user.id, ChatSession.character_id == cid,
                                            ChatSession.ended_at.is_(None)).order_by(ChatSession.updated_at.desc()).first()
        if sess is None:
            sess = ChatSession(user_id=user.id, character_id=cid, title="眼镜模拟器")
            db.add(sess)
            db.flush()
        if msg["type"] == "camera.frame":
            img = chat.decode_image(msg.get("image"))
            p = chat.plan_turn(db, user, sess, event="perception", text=str(msg.get("question") or "")[:200],
                               image=img, source="glasses")
        elif msg["type"] == "mic.audio":  # 眼镜的麦克风：她直接听
            audio = chat.decode_audio(str(msg.get("audio") or ""))
            p = chat.plan_turn(db, user, sess, event="message", text=chat.tr("（语音）"), source="glasses")
            chat.hear_turn(p, audio)
        else:
            p = chat.plan_turn(db, user, sess, event="message", text=str(msg.get("text") or "")[:1000], source="glasses")
        r = chat.run_turn(db, p)
        return {"type": "result", "session_id": sess.id, "reply": (r["reply"] or {}).get("content"),
                "heard": (r.get("user") or {}).get("content") if msg["type"] == "mic.audio" else None,
                "actions": r["actions"], "decision": {"actions": p.decision.actions(), "label": p.decision.label}}
    except Exception as e:  # noqa: BLE001  设备输入出错只回报，不断开
        log.exception("设备输入处理失败")
        db.rollback()
        detail = getattr(e, "detail", None) or str(e)
        return {"type": "error", "message": str(detail)[:200]}
    finally:
        db.close()


@router.websocket("/ws")
async def ws(websocket: WebSocket, token: str = "", kind: str = "glasses-sim"):
    db = SessionLocal()
    try:
        user = user_from_token(db, token)
    finally:
        db.close()
    adapter_cls = ADAPTERS.get(kind)
    await websocket.accept()
    if user is None or adapter_cls is None:
        await websocket.send_json({"type": "error", "message": "未登录或不支持的设备类型"})
        await websocket.close(code=4401)
        return
    adapter = adapter_cls()
    try:
        adapter.connect()
    except DeviceUnavailable as e:
        await websocket.send_json({"type": "error", "message": str(e)})
        await websocket.close(code=4404)
        return
    hub.loop = asyncio.get_running_loop()
    conn = Connection(id=uuid.uuid4().hex[:12], user_id=user.id, adapter=adapter, queue=asyncio.Queue())
    hub.add(conn)
    events.record("device", "connect", user_id=user.id, payload={"kind": kind})
    await websocket.send_json({"type": "state", **conn.out()})

    async def pump():
        while True:
            await websocket.send_json(await conn.queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, dict):
                continue
            conn.last_seen = time.time()
            t = msg.get("type")
            if t == "hello":
                conn.character_id = str(msg.get("character_id") or "") or None
                await websocket.send_json({"type": "state", **conn.out()})
            elif t == "heartbeat":
                await websocket.send_json({"type": "heartbeat", "state": conn.state()})
            elif t == "imu.pose":
                conn.pose = {"yaw": _clamp(msg.get("yaw"), -180, 180), "pitch": _clamp(msg.get("pitch"), -90, 90),
                             "roll": _clamp(msg.get("roll"), -90, 90)}
            elif t in ("camera.frame", "mic.text", "mic.audio"):
                events.record("device", t, user_id=user.id, character_id=conn.character_id,
                              payload={"has_image": bool(msg.get("image")), "chars": len(str(msg.get("text") or ""))})
                await websocket.send_json({"type": "busy"})
                reply = await asyncio.get_running_loop().run_in_executor(None, _handle_input, conn, msg)
                if reply:
                    await websocket.send_json(reply)
            else:
                await websocket.send_json({"type": "error", "message": f"不认识的输入：{t}"})
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        hub.remove(conn.id)
        events.record("device", "disconnect", user_id=user.id, payload={"kind": kind})
