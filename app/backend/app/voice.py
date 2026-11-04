"""语音（STT / TTS）与视觉理解（VLM）的适配层。密钥只在服务端，浏览器只拿到“用哪种方式”。

STT  browser：浏览器 Web Speech API（不经过本服务）  openai：转发到 OpenAI 兼容 /audio/transcriptions  mock：测试
TTS  browser：浏览器 speechSynthesis                  openai：转发到 OpenAI 兼容 /audio/speech        mock：一段提示音
VLM  mock：只读颜色和亮度（明确标注为模拟）           openai：OpenAI 兼容 /chat/completions + image_url
上传的音频和图片只在内存里处理，不落库。
"""
from __future__ import annotations

import base64
import io
import logging
import math
import struct
import time
import wave

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import events
from .auth import current_user
from .config import settings
from .models import User

log = logging.getLogger("krino.voice")
router = APIRouter(prefix="/api", tags=["voice"])

AUDIO_TYPES = {"audio/webm", "audio/ogg", "audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp4", "audio/m4a"}


class ServiceError(RuntimeError):
    pass


def _client(timeout: float = 60) -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=10))


# ---------- STT ----------

def transcribe(data: bytes, mime: str, filename: str = "audio.webm") -> str:
    if settings.stt_provider == "mock":
        return "你好，这是一段模拟识别的语音"
    if settings.stt_provider != "openai" or not settings.stt_base_url:
        raise ServiceError("服务端没有配置语音识别（STT_PROVIDER=openai），请使用浏览器识别")
    headers = {"Authorization": f"Bearer {settings.stt_api_key}"} if settings.stt_api_key else {}
    try:
        with _client() as c:
            r = c.post(settings.stt_base_url.rstrip("/") + "/audio/transcriptions", headers=headers,
                       data={"model": settings.stt_model, "language": "zh"}, files={"file": (filename, data, mime)})
    except httpx.HTTPError as e:
        raise ServiceError("无法连接语音识别服务") from e
    if r.status_code != 200:
        log.error("STT %s: %s", r.status_code, r.text[:200])
        raise ServiceError(f"语音识别出错（{r.status_code}）")
    return str(r.json().get("text", "")).strip()


# ---------- TTS ----------

def _beep_wav(seconds: float = 0.4) -> bytes:
    rate = 16000
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        n = int(rate * seconds)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 660 * i / rate)
                                                        * min(1, (n - i) / 800))) for i in range(n)))
    return buf.getvalue()


def synthesize(text: str, voice: str | None, speed: float) -> tuple[bytes, str]:
    if settings.tts_provider == "mock":
        return _beep_wav(), "audio/wav"
    if settings.tts_provider == "local":
        from . import tts_local

        ok, why = tts_local.available()
        if not ok:
            raise ServiceError(why)
        try:
            return tts_local.synthesize(text, voice, speed), "audio/wav"
        except (RuntimeError, ValueError) as e:
            raise ServiceError(str(e)) from e
    if settings.tts_provider != "openai" or not settings.tts_base_url:
        raise ServiceError("服务端没有配置语音合成（TTS_PROVIDER=openai），请使用浏览器朗读")
    voice = voice if voice in settings.tts_voices else settings.tts_voices[0]
    headers = {"Authorization": f"Bearer {settings.tts_api_key}"} if settings.tts_api_key else {}
    try:
        with _client() as c:
            r = c.post(settings.tts_base_url.rstrip("/") + "/audio/speech", headers=headers,
                       json={"model": settings.tts_model, "input": text, "voice": voice, "speed": speed,
                             "response_format": "mp3"})
    except httpx.HTTPError as e:
        raise ServiceError("无法连接语音合成服务") from e
    if r.status_code != 200:
        log.error("TTS %s: %s", r.status_code, r.text[:200])
        raise ServiceError(f"语音合成出错（{r.status_code}）")
    return r.content, r.headers.get("content-type", "audio/mpeg")


# ---------- VLM ----------

_COLORS = [("红", (200, 60, 60)), ("橙", (220, 140, 50)), ("黄", (220, 200, 70)), ("绿", (70, 160, 80)),
           ("青", (60, 170, 170)), ("蓝", (60, 90, 200)), ("紫", (140, 80, 180)), ("白", (230, 230, 230)),
           ("灰", (128, 128, 128)), ("黑", (25, 25, 25))]


def _mock_describe(data: bytes) -> str:
    from PIL import Image, UnidentifiedImageError

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise ServiceError("图片打不开") from e
    w, h = img.size
    small = img.resize((32, 32))
    px = list(small.getdata())
    avg = tuple(sum(p[i] for p in px) / len(px) for i in range(3))
    name = min(_COLORS, key=lambda c: sum((a - b) ** 2 for a, b in zip(avg, c[1])))[0]
    light = sum(avg) / 3
    mood = "很亮" if light > 170 else ("偏暗" if light < 70 else "亮度适中")
    shape = "横构图" if w > h * 1.2 else ("竖构图" if h > w * 1.2 else "方形构图")
    return f"［模拟视觉，未理解内容］一张{shape}的图片，整体偏{name}色，{mood}（{w}×{h}）"


def describe_image(data: bytes, mime: str, question: str = "") -> str:
    """返回给角色看的画面描述。mock 只读颜色和亮度，描述里会写明是模拟。"""
    if settings.vlm_provider != "openai":
        return _mock_describe(data)
    if not (settings.vlm_base_url and settings.vlm_model):
        raise ServiceError("视觉理解没有配置完整（VLM_BASE_URL / VLM_MODEL）")
    url = f"data:{mime};base64,{base64.b64encode(data).decode()}"
    body = {"model": settings.vlm_model, "max_tokens": 300, "messages": [{"role": "user", "content": [
        {"type": "text", "text": "用中文客观描述这张图片里有什么（不超过 100 字），不要猜测人物身份。"
                                 + (f"对方的问题：{question[:200]}" if question else "")},
        {"type": "image_url", "image_url": {"url": url}}]}]}
    headers = {"Authorization": f"Bearer {settings.vlm_api_key}"} if settings.vlm_api_key else {}
    try:
        with _client() as c:
            r = c.post(settings.vlm_base_url.rstrip("/") + "/chat/completions", json=body, headers=headers)
    except httpx.HTTPError as e:
        raise ServiceError("无法连接视觉理解服务") from e
    if r.status_code != 200:
        log.error("VLM %s: %s", r.status_code, r.text[:200])
        raise ServiceError(f"视觉理解出错（{r.status_code}）")
    return str(((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()[:400]


# ---------- 接口 ----------

@router.get("/voice/config")
def voice_config(user: User = Depends(current_user)):
    """前端据此决定用浏览器还是服务端。"""
    return {"stt": {"provider": settings.stt_provider, "server": settings.stt_provider in ("openai", "mock")},
            "tts": _tts_config(),
            "vlm": {"provider": settings.vlm_provider, "simulated": settings.vlm_provider != "openai"}}


def _tts_config() -> dict:
    p = settings.tts_provider
    if p == "local":
        from . import tts_local

        ok, _ = tts_local.available()
        return {"provider": p, "server": ok, "voices": tts_local.voices() if ok else [], "default": settings.tts_default_voice}
    return {"provider": p, "server": p in ("openai", "mock"),
            "voices": list(settings.tts_voices) if p == "openai" else [], "default": ""}


@router.post("/voice/stt")
async def stt(file: UploadFile = File(...), user: User = Depends(current_user)):
    mime = (file.content_type or "").split(";")[0]
    if mime not in AUDIO_TYPES:
        raise HTTPException(415, "不支持的音频格式")
    data = await file.read(settings.max_audio_bytes + 1)
    if len(data) > settings.max_audio_bytes:
        raise HTTPException(413, "音频太长了")
    t0 = time.perf_counter()
    try:
        text = transcribe(data, mime, file.filename or "audio.webm")
    except ServiceError as e:
        raise HTTPException(503, str(e)) from e
    events.record("voice", "stt", user_id=user.id, latency_ms=(time.perf_counter() - t0) * 1000,
                  payload={"provider": settings.stt_provider, "bytes": len(data)})
    return {"text": text}


class TTSIn(BaseModel):
    text: str = Field(min_length=1, max_length=600)
    voice: str | None = Field(default=None, max_length=40)
    rate: float = Field(default=1.0, ge=0.5, le=2.0)


@router.post("/voice/tts")
def tts(body: TTSIn, user: User = Depends(current_user)):
    t0 = time.perf_counter()
    try:
        audio, mime = synthesize(body.text, body.voice, body.rate)
    except ServiceError as e:
        raise HTTPException(503, str(e)) from e
    events.record("voice", "tts", user_id=user.id, latency_ms=(time.perf_counter() - t0) * 1000,
                  payload={"provider": settings.tts_provider, "chars": len(body.text)})
    return Response(audio, media_type=mime)


class VisionIn(BaseModel):
    image: str = Field(max_length=8_000_000)
    question: str = Field(default="", max_length=200)


@router.post("/vision/describe")
def vision(body: VisionIn, user: User = Depends(current_user)):
    from .chat import decode_image

    img = decode_image(body.image)
    try:
        return {"description": describe_image(img[0], img[1], body.question),
                "simulated": settings.vlm_provider != "openai"}
    except ServiceError as e:
        raise HTTPException(503, str(e)) from e
