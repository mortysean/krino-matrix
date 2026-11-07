"""语音（STT / TTS）与视觉理解（VLM）的适配层。密钥只在服务端，浏览器只拿到“用哪种方式”。

STT  browser：浏览器 Web Speech API（不经过本服务）  openai：转发到 OpenAI 兼容 /audio/transcriptions  mock：测试
TTS  qwen：自建 Qwen3-TTS  dashscope：阿里云百炼 Qwen-Audio 3.1  elevenlabs：Eleven v4  openai：OpenAI  local：Kokoro  browser：浏览器朗读  mock：提示音
     云端和自建的都按角色的声音描述（app/tts/voices.py）说话，出错退回 Kokoro。
VLM  mock：只读颜色和亮度（明确标注为模拟）           openai：OpenAI 兼容 /chat/completions + image_url
上传的音频和图片只在内存里处理，不落库。
"""
from __future__ import annotations

import base64
import io
import logging
import math
import re
import struct
import time
import unicodedata
import wave

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import credits, events
from .auth import current_user
from .config import locale, settings
from .db import get_db
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

_ACTION = re.compile(r"[（(][^（()）\n]{0,40}[）)]|\*[^*\n]{0,40}\*")
# 颜文字连同括号外面的装饰一起认出来：ヾ(≧▽≦*)o、m(_ _)m、٩(ˊᗜˋ)و、(￣▽￣)ゞ、(－ω－) zzZ
_KAO_CLOSED = re.compile(r"[ヾヽ٩mｍo＼\\～~φΦ]{0,2}[（(]([^（()）\n]{0,40})[）)][ゞゝو*oｍm／/～~ﾉノ]{0,2}(?:\s?z+Z+)?")
# 少了右括号的颜文字：(・_・ゞ —— 括号后面全是符号（没有字、字母、数字），一直到文字或空格为止
_KAO_OPEN = re.compile(r"(?<![A-Za-z0-9_])[（(](?=[^\s（()）一-鿿]*[^A-Za-z0-9_\s（()）一-鿿])[^\s（()）\n一-鿿A-Za-z0-9]{1,12}")
_WORDISH = re.compile(r"[一-鿿]|[A-Za-z]{3,}")


def strip_kaomoji(text: str) -> str:
    """去掉颜文字（包括括号外的装饰和没写完的括号）。括号里是动作描述（有汉字或英文单词）的不在这里处理。"""
    text = _KAO_CLOSED.sub(lambda m: m.group(0) if _WORDISH.search(m.group(1)) else "", text)
    return _KAO_OPEN.sub("", text)
_KAOMOJI_CHARS = set("・°ﾟ｡´｀`ω∀▽ᴗ˘◕‿╹ㅂ")


def speakable(text: str) -> str:
    """朗读前去掉不该念出来的东西：括号里的动作、*动作*、颜文字、emoji 和装饰符号。"""
    text = _ACTION.sub("", strip_kaomoji(text))
    text = "".join(ch for ch in text if ch not in _KAOMOJI_CHARS and unicodedata.category(ch) not in ("So", "Sm", "Sk", "Co", "Cs")
                   and ch not in "()（）" and not "\ufe30" <= ch <= "\ufe4f")
    return re.sub(r"[ \t]{2,}", " ", text).strip()


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


def _qwen_voices() -> list[str]:
    """语音服务里已经设计好、并且是当前站点语言的音色（结果缓存 60 秒）。"""
    now = time.time()
    if now - _qwen_cache["at"] > 60:
        try:
            with httpx.Client(timeout=3, trust_env=False) as c:
                r = c.get(settings.qwen_tts_url.rstrip("/") + "/v1/voices")
            _qwen_cache["voices"] = [v["id"] for v in r.json()] if r.status_code == 200 else []
        except (httpx.HTTPError, ValueError):
            _qwen_cache["voices"] = []
        _qwen_cache["at"] = now
    suffix = "-en" if locale() == "en" else "-zh"
    return [v for v in _qwen_cache["voices"] if v.endswith(suffix)]


_qwen_cache: dict = {"at": 0.0, "voices": []}


def _qwen(text: str, voice: str | None, speed: float) -> bytes:
    """Qwen3-TTS 语音服务（app/tts/server.py）。角色的音色没设计过时用当前语言的第一个。"""
    vs = _qwen_voices()
    if not vs:
        raise ServiceError("语音服务没有启动或还没有设计音色")
    from .tts_local import FALLBACK

    voice = {v: k for k, v in FALLBACK.items()}.get(voice or "", voice)  # 以前存的 Kokoro 音色 → 对应的设计音色
    name = voice if voice in vs else vs[0]
    try:
        with httpx.Client(timeout=httpx.Timeout(60, connect=3), trust_env=False) as c:
            r = c.post(settings.qwen_tts_url.rstrip("/") + "/v1/audio/speech", json={"input": text, "voice": name, "speed": speed})
    except httpx.HTTPError as e:
        raise ServiceError("无法连接语音服务") from e
    if r.status_code != 200:
        raise ServiceError(f"语音服务出错（{r.status_code}）")
    return r.content


def _qwen_stream(text: str, voice: str | None, speed: float):
    """自建语音服务的流式合成，原样转给浏览器（audio/pcm，24kHz 单声道 16-bit）。
    第一段声音拿到了才开始回应；连不上、出错就返回 None，由调用方按整句合成（还会退回 Kokoro）。"""
    text = speakable(text)
    vs = _qwen_voices()
    if not text or not vs:
        return None
    from fastapi.responses import StreamingResponse

    from .tts_local import FALLBACK

    voice = {v: k for k, v in FALLBACK.items()}.get(voice or "", voice)
    name = voice if voice in vs else vs[0]
    client = httpx.Client(timeout=httpx.Timeout(60, connect=3), trust_env=False)
    try:
        cm = client.stream("POST", settings.qwen_tts_url.rstrip("/") + "/v1/audio/speech",
                           json={"input": text, "voice": name, "speed": speed, "stream": True})
        r = cm.__enter__()
        if r.status_code != 200 or not r.headers.get("content-type", "").startswith("audio/pcm"):
            cm.__exit__(None, None, None); client.close()
            return None
        it = r.iter_bytes()
        first = next(it, b"")
        if not first:
            cm.__exit__(None, None, None); client.close()
            return None
    except httpx.HTTPError as e:
        log.warning("流式语音不可用，改整句合成：%s", e)
        client.close()
        return None

    def gen():
        try:
            yield first
            yield from it
        except httpx.HTTPError as e:
            log.warning("流式语音中途断开：%s", e)
        finally:
            cm.__exit__(None, None, None); client.close()

    rate = r.headers.get("x-sample-rate", "24000")
    return StreamingResponse(gen(), media_type="audio/pcm", headers={"X-Sample-Rate": rate, "Cache-Control": "no-store",
                                                                    "X-Accel-Buffering": "no"})


def _styles() -> dict:
    """角色音色的声音描述（app/tts/voices.py，和自建语音服务共用一份）。"""
    if not _style_cache:
        import importlib.util

        from .config import ROOT_DIR

        spec = importlib.util.spec_from_file_location("krino_voice_styles", ROOT_DIR / "app" / "tts" / "voices.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _style_cache.update(mod.VOICES)
    return _style_cache


_style_cache: dict = {}


def _role(voice: str | None) -> str:
    """把角色存的音色（设计音色名，或以前的 Kokoro 编号）归到当前语言的角色音色名。"""
    from .tts_local import FALLBACK

    voice = {v: k for k, v in FALLBACK.items()}.get(voice or "", voice or "")
    suffix = "-en" if locale() == "en" else "-zh"
    if voice in _styles() and voice.endswith(suffix):
        return voice
    return "dafeiyu" + suffix


def _platform_voice(role: str, known: tuple[str, ...] | None = None, table: tuple[str, ...] | None = None) -> str:
    m = dict(x.split("=", 1) for x in (table or settings.tts_voice_map) if "=" in x)
    v = m.get(role, "")
    if known is not None and v not in known:
        v = known[0]
    return v


def _openai(text: str, voice: str | None, speed: float) -> tuple[bytes, str]:
    if not settings.tts_api_key:
        raise ServiceError("没有配置 OPENAI_API_KEY")
    role = _role(voice)
    body = {"model": settings.tts_model, "input": text, "voice": _platform_voice(role, settings.tts_voices),
            "response_format": "mp3"}
    if settings.tts_model.startswith("gpt-"):  # 新模型按描述说话；speed 只有 tts-1 系列认
        body["instructions"] = _styles()[role]["instruct"]
    else:
        body["speed"] = speed
    try:
        with _client() as c:
            r = c.post(settings.tts_base_url.rstrip("/") + "/audio/speech", json=body,
                       headers={"Authorization": f"Bearer {settings.tts_api_key}"})
    except httpx.HTTPError as e:
        raise ServiceError("无法连接 OpenAI 语音") from e
    if r.status_code != 200:
        log.error("OpenAI TTS %s: %s", r.status_code, r.text[:200])
        raise ServiceError(f"OpenAI 语音出错（{r.status_code}）")
    return r.content, r.headers.get("content-type", "audio/mpeg")


# 生成的角色可以选的百炼音色（qwen-audio-3.1-tts-flash）：id → (中文说明, 英文说明, 语言)。
# 官方的 KRINO、大肥鱼用自己的角色音色（app/tts/voices.py）；一句话生成的角色从这里挑一个，再配一句声音描述（behavior.voice.style）
VOICE_CATALOG = {
    "qiaoxiaojiao_v3.1": ("俏丽可爱的少女", "cute, pretty girl", "zh"),
    "longanlingxi_v3.1": ("甜美可爱", "sweet and cute", "zh"),
    "longhua_v3.1": ("元气甜美", "energetic and sweet", "zh"),
    "longanhuan_v3.1": ("欢脱元气", "cheerful and lively", "zh"),
    "longanlingxin_v3.1": ("温柔治愈", "gentle and soothing", "zh"),
    "xuyanchu_v3.1": ("沉稳磁性的御姐", "calm, magnetic, mature", "zh"),
    "guyunshu_v3.1": ("成熟稳重", "mature and steady", "zh"),
    "longanya_v3.1": ("高雅有气质", "elegant", "zh"),
    "xuyuyuan_v3.1": ("知性", "intellectual", "zh"),
    "longling_v3.1": ("稚气童声", "childlike", "zh"),
    "xunanchuan_v3.1": ("磁性男声", "magnetic male", "zh"),
    "longshu_v3.1": ("沉稳男声", "calm male", "zh"),
    "longanyang_v3.1": ("阳光少年", "sunny boy", "zh"),
    "Cally_v3.1": ("美式甜美女声", "sweet American girl", "en"),
    "Ava_v3.1": ("美式年轻女声", "young American woman", "en"),
    "Emily_v3.1": ("英式冷静女声", "calm British woman", "en"),
    "Luna_v3.1": ("英式柔和女声", "soft British woman", "en"),
    "Donna_v3.1": ("美式成熟女声", "mature American woman", "en"),
    "Brian_v3.1": ("美式男声", "American man", "en"),
    "Eric_v3.1": ("英式男声", "British man", "en"),
}


def catalog_voices(lang: str | None = None) -> list[str]:
    lang = lang or ("en" if locale() == "en" else "zh")
    return [k for k, v in VOICE_CATALOG.items() if v[2] == lang]


def _dashscope(text: str, voice: str | None, speed: float, style: str | None = None) -> tuple[bytes, str]:
    """阿里云百炼：系统音色 + 声音描述。返回的是 24 小时有效的音频链接，取回来再给浏览器。
    qwen-audio-* 走 SpeechSynthesizer 接口（字段是 instruction）；qwen3-tts-* 走多模态生成接口（字段是 instructions）。"""
    if not settings.dashscope_api_key:
        raise ServiceError("没有配置 DASHSCOPE_API_KEY")
    if voice in VOICE_CATALOG and settings.dashscope_tts_model.startswith("qwen-audio"):  # 生成的角色：清单里的音色 + 她自己的声音描述
        return _dashscope_call(text, voice, (style or VOICE_CATALOG[voice][0]).strip()[:300], VOICE_CATALOG[voice][2])
    role = _role(voice)
    style = _styles()[role]
    model = settings.dashscope_tts_model
    if model.startswith("qwen-audio"):
        base = (f"https://{settings.dashscope_workspace}.{settings.dashscope_region}.maas.aliyuncs.com/api/v1"
                if settings.dashscope_workspace else settings.dashscope_base_url.rstrip("/"))
        url = base + "/services/audio/tts/SpeechSynthesizer"
        lang = "用中文说。" if style["language"] == "Chinese" else "Speak in English. "
        body = {"model": model, "input": {
            "text": text, "voice": _platform_voice(role, table=settings.dashscope_voice_map) or "longanhuan_v3.1",
            "format": "wav", "sample_rate": 24000, "instruction": lang + style["instruct"]}}
    else:
        url = settings.dashscope_base_url.rstrip("/") + "/services/aigc/multimodal-generation/generation"
        body = {"model": model, "input": {
            "text": text, "voice": _platform_voice(role) or "Cherry", "language_type": style["language"],
            "instructions": style["instruct"], "optimize_instructions": True}}
    try:
        with _client() as c:
            r = c.post(url, json=body, headers={"Authorization": f"Bearer {settings.dashscope_api_key}"})
            if r.status_code != 200:
                log.error("百炼 TTS %s: %s", r.status_code, r.text[:300])
                raise ServiceError(f"百炼语音出错（{r.status_code}）")
            audio = (r.json().get("output") or {}).get("audio") or {}
            if audio.get("data"):
                return base64.b64decode(audio["data"]), "audio/wav"
            if not audio.get("url"):
                raise ServiceError("百炼语音没有返回音频")
            a = c.get(audio["url"])
    except httpx.HTTPError as e:
        raise ServiceError("无法连接百炼语音") from e
    except ValueError as e:
        raise ServiceError("百炼语音返回的不是 JSON") from e
    if a.status_code != 200:
        raise ServiceError(f"取百炼音频出错（{a.status_code}）")
    return a.content, a.headers.get("content-type", "audio/wav").split(";")[0]


def _dashscope_call(text: str, voice: str, instruct: str, lang: str) -> tuple[bytes, str]:
    base = (f"https://{settings.dashscope_workspace}.{settings.dashscope_region}.maas.aliyuncs.com/api/v1"
            if settings.dashscope_workspace else settings.dashscope_base_url.rstrip("/"))
    body = {"model": settings.dashscope_tts_model, "input": {
        "text": text, "voice": voice, "format": "wav", "sample_rate": 24000,
        "instruction": ("Speak in English. " if lang == "en" else "用中文说。") + instruct}}
    try:
        with _client() as c:
            r = c.post(base + "/services/audio/tts/SpeechSynthesizer", json=body,
                       headers={"Authorization": f"Bearer {settings.dashscope_api_key}"})
            if r.status_code != 200:
                log.error("百炼 TTS %s: %s", r.status_code, r.text[:300])
                raise ServiceError(f"百炼语音出错（{r.status_code}）")
            audio = (r.json().get("output") or {}).get("audio") or {}
            if audio.get("data"):
                return base64.b64decode(audio["data"]), "audio/wav"
            if not audio.get("url"):
                raise ServiceError("百炼语音没有返回音频")
            a = c.get(audio["url"])
    except httpx.HTTPError as e:
        raise ServiceError("无法连接百炼语音") from e
    except ValueError as e:
        raise ServiceError("百炼语音返回的不是 JSON") from e
    if a.status_code != 200:
        raise ServiceError(f"取百炼音频出错（{a.status_code}）")
    return a.content, a.headers.get("content-type", "audio/wav").split(";")[0]


def _elevenlabs(text: str, voice: str | None, speed: float) -> tuple[bytes, str]:
    """ElevenLabs Eleven v4。没有声音描述参数，靠角色对应的自带音色；语速只认 0.7–1.2。"""
    if not settings.elevenlabs_api_key:
        raise ServiceError("没有配置 ELEVENLABS_API_KEY")
    voice_id = _platform_voice(_role(voice), table=settings.elevenlabs_voice_map) or "cgSgspJ2msm6clMCkdW9"
    body = {"text": text, "model_id": settings.elevenlabs_model,
            "voice_settings": {"speed": max(0.7, min(1.2, speed))}}
    try:
        with _client() as c:
            r = c.post(f"{settings.elevenlabs_base_url.rstrip('/')}/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                       json=body, headers={"xi-api-key": settings.elevenlabs_api_key})
    except httpx.HTTPError as e:
        raise ServiceError("无法连接 ElevenLabs") from e
    if r.status_code != 200:
        log.error("ElevenLabs TTS %s: %s", r.status_code, r.text[:300])
        raise ServiceError(f"ElevenLabs 语音出错（{r.status_code}）")
    return r.content, r.headers.get("content-type", "audio/mpeg").split(";")[0]


CLOUD = {"openai": _openai, "dashscope": _dashscope, "elevenlabs": _elevenlabs}


def synthesize(text: str, voice: str | None, speed: float, style: str | None = None) -> tuple[bytes, str]:
    p = settings.tts_provider
    text = speakable(text)
    if not text:
        raise ServiceError("没有需要朗读的文字")
    if p == "mock":
        return _beep_wav(), "audio/wav"
    try:  # 首选的服务不在或出错就退回本地 Kokoro，不让她哑掉
        if p == "qwen":
            return _qwen(text, voice, speed), "audio/wav"
        if p == "dashscope":
            return _dashscope(text, voice, speed, style)
        if p in CLOUD:
            return CLOUD[p](text, voice, speed)
    except ServiceError as e:
        log.warning("%s 语音不可用，改用 Kokoro：%s", p, e)
    if p not in ("local", "qwen", *CLOUD):
        raise ServiceError("服务端没有配置语音合成，请使用浏览器朗读")
    from . import tts_local

    ok, why = tts_local.available()
    if not ok:
        raise ServiceError(why)
    try:
        return tts_local.synthesize(text, voice, speed), "audio/wav"
    except (RuntimeError, ValueError) as e:
        raise ServiceError(str(e)) from e


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
    from .llm import get_hear_llm

    return {"hear": get_hear_llm() is not None,  # 能直接听：麦克风录音直接发给她，不先转文字
            "stt": {"provider": settings.stt_provider, "server": settings.stt_provider in ("openai", "mock")},
            "tts": _tts_config(),
            "vlm": {"provider": settings.vlm_provider, "simulated": settings.vlm_provider != "openai"}}


def _tts_config() -> dict:
    p = settings.tts_provider
    if p == "qwen" and _qwen_voices():
        return {"provider": p, "server": True, "voices": _qwen_voices(), "default": _qwen_voices()[0]}
    keys = {"openai": settings.tts_api_key, "dashscope": settings.dashscope_api_key, "elevenlabs": settings.elevenlabs_api_key}
    if keys.get(p):
        roles = [k for k in _styles() if k.endswith("-en" if locale() == "en" else "-zh")]
        extra = catalog_voices() if p == "dashscope" else []
        labels = {k: VOICE_CATALOG[k][1 if locale() == "en" else 0] for k in extra}
        return {"provider": p, "server": True, "voices": roles + extra, "labels": labels, "default": roles[0]}
    if p in ("local", "qwen", *CLOUD):
        from . import tts_local

        ok, _ = tts_local.available()
        return {"provider": "local", "server": ok, "voices": tts_local.voices() if ok else [], "default": tts_local.default_voice()}
    return {"provider": p, "server": p == "mock", "voices": [], "default": ""}


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
    style: str | None = Field(default=None, max_length=300)  # 角色自己的声音描述（一句话生成的角色才有）
    stream: bool = False  # 边合成边返回 16-bit PCM（24kHz 单声道）：第一段声音零点几秒就到，不用等整句


@router.post("/voice/tts")
def tts(body: TTSIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    credits.check(db, user)
    t0 = time.perf_counter()
    if body.stream and settings.tts_provider == "qwen":
        resp = _qwen_stream(body.text, body.voice, body.rate)
        if resp is not None:
            events.record("voice", "tts", user_id=user.id, latency_ms=(time.perf_counter() - t0) * 1000,
                          payload={"provider": "qwen", "chars": len(body.text), "stream": True})
            return resp
    try:
        audio, mime = synthesize(body.text, body.voice, body.rate, body.style)
    except ServiceError as e:
        raise HTTPException(503, str(e)) from e
    events.record("voice", "tts", user_id=user.id, latency_ms=(time.perf_counter() - t0) * 1000,
                  payload={"provider": settings.tts_provider, "chars": len(body.text)})
    credits.charge(user.id, "tts", credits.tts_cny(len(body.text)), chars=len(body.text))
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
