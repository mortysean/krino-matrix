"""自建语音服务（算力服务器上跑）：合成交给 vllm-omni 跑的 Qwen3-TTS（流式、低延迟），识别用 SenseVoice。接口和 OpenAI 兼容。

    POST /v1/audio/speech          {"input": "...", "voice": "dafeiyu-zh", "speed": 1.0}  → audio/wav
                                   加 "stream": true → 边合成边返回 16-bit PCM（24kHz 单声道），首包几百毫秒
    GET  /v1/voices                已经设计好的音色
    POST /v1/voices/design         {"description": "声音描述", "text": "试听用的一句话", "language": "zh"}
                                   → audio/wav（这个声音念的试听句），响应头 X-Voice-Id = 新音色的编号（之后合成直接用它）
    POST /v1/audio/transcriptions  multipart: file=音频  → {"text": "..."}
    GET  /health

后端这样接：TTS_PROVIDER=qwen，QWEN_TTS_URL=http://<服务器>:8640；STT_PROVIDER=openai，STT_BASE_URL=http://<服务器>:8640/v1
音色文件（<音色>.wav + <音色>.json）放在 VOICE_DIR，跟 app/tts/server.py 用的是同一份；启动时注册到 vllm-omni。
vllm-omni 由 run.sh 在 127.0.0.1:8650 启动（只对本机开放）。
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import httpx
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
MODELS = Path(os.getenv("MODELS_DIR", HERE.parent / "models"))
VOICE_DIR = Path(os.getenv("VOICE_DIR", MODELS / "voices"))
ASR_MODEL = MODELS / os.getenv("ASR_MODEL", "SenseVoiceSmall")
OMNI = os.getenv("OMNI_URL", "http://127.0.0.1:8650")
DESIGN = os.getenv("DESIGN_URL", "http://127.0.0.1:8651")  # VoiceDesign：按描述造一个新声音
SAMPLE_RATE = 24000

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s speech: %(message)s")
log = logging.getLogger("speech")
app = FastAPI(title="KRINO speech")
_asr_lock = threading.Lock()
_asr = None
_registered: set[str] = set()
_http = httpx.Client(timeout=httpx.Timeout(120, connect=3), trust_env=False)
_async_client: httpx.AsyncClient | None = None


def _ahttp() -> httpx.AsyncClient:  # 流式合成专用，在事件循环里用（要等循环起来再建）
    global _async_client
    if _async_client is None:
        _async_client = httpx.AsyncClient(timeout=httpx.Timeout(120, connect=3), trust_env=False)
    return _async_client


def asr():
    global _asr
    if _asr is None:
        from funasr import AutoModel

        t = time.time()
        _asr = AutoModel(model=str(ASR_MODEL), device="cuda:0", disable_update=True)
        log.info("识别模型已加载：%s（%.1fs）", ASR_MODEL.name, time.time() - t)
    return _asr


def voices() -> dict:
    out = {}
    for meta in sorted(VOICE_DIR.glob("*.json")):
        if (VOICE_DIR / f"{meta.stem}.wav").exists():
            out[meta.stem] = json.loads(meta.read_text(encoding="utf-8"))
    return out


def register_voices() -> None:
    """把角色音色（参考音频 + 文字）注册到 vllm-omni；已经有的跳过。"""
    have = set()
    try:
        r = _http.get(f"{OMNI}/v1/audio/voices")
        data = r.json()
        items = data.get("voices", data) if isinstance(data, dict) else data
        have = {(v.get("name") if isinstance(v, dict) else v) for v in items}
    except (httpx.HTTPError, ValueError, AttributeError):
        pass
    for name, meta in voices().items():
        if name not in have:
            with open(VOICE_DIR / f"{name}.wav", "rb") as f:
                r = _http.post(f"{OMNI}/v1/audio/voices", files={"audio_sample": (f"{name}.wav", f, "audio/wav")},
                               data={"name": name, "consent": "krino-designed-voice", "ref_text": meta["text"]})
            if r.status_code != 200:
                raise RuntimeError(f"注册音色 {name} 失败：{r.status_code} {r.text[:200]}")
        _registered.add(name)


# 设计声音时让它念的参考句：够长（八九秒）、语调有起伏，克隆出来才稳。接在试听句后面一起念
REF_TEXT = {
    "zh": "今天的风有点大，我在路上想了很多事情。如果你愿意的话，我们可以慢慢聊，从最近发生的小事说起。",
    "en": "The wind was strong today, and I thought about a lot of things on the way here. "
          "If you'd like, we can take our time and start with the little things that happened lately.",
}
_design_lock = threading.Lock()


class DesignIn(BaseModel):
    description: str = Field(min_length=2, max_length=600)
    text: str = Field(default="", max_length=200)
    language: str = Field(default="zh", pattern="^(zh|en)$")


@app.post("/v1/voices/design")
def design_voice(body: DesignIn):
    """按描述设计一个新声音：VoiceDesign 念一段参考句 → 存成音色文件 → 注册给合成引擎克隆。"""
    import hashlib
    import uuid

    lead = clean(body.text)
    text = (lead + (" " if body.language == "en" else "") + REF_TEXT[body.language]) if lead else REF_TEXT[body.language]
    req = {"input": text, "task_type": "VoiceDesign", "instructions": body.description.strip(),
           "language": "Chinese" if body.language == "zh" else "English", "response_format": "wav"}
    t = time.time()
    with _design_lock:
        try:
            r = _http.post(f"{DESIGN}/v1/audio/speech", json=req, timeout=180)
        except httpx.HTTPError as e:
            raise HTTPException(503, "声音设计引擎没有启动") from e
    if r.status_code != 200:
        log.error("设计声音出错 %s：%s", r.status_code, r.text[:300])
        raise HTTPException(502, f"设计声音出错（{r.status_code}）")
    # 编号：v + 10 位随机，后缀是语言（网站按后缀挑当前语言的音色）
    vid = f"v{uuid.uuid4().hex[:10]}-{body.language}"
    (VOICE_DIR / f"{vid}.wav").write_bytes(r.content)
    meta = {"text": text, "language": "Chinese" if body.language == "zh" else "English", "description": body.description.strip(),
            "designed": True, "sha1": hashlib.sha1(r.content).hexdigest()[:12], "created": int(time.time())}
    (VOICE_DIR / f"{vid}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    try:
        register_voices()
    except (httpx.HTTPError, RuntimeError) as e:
        log.exception("注册新音色失败")
        raise HTTPException(503, "新声音注册失败，请再试一次") from e
    with wave.open(io.BytesIO(r.content)) as w:
        dur = w.getnframes() / w.getframerate()
    log.info("设计声音 %s（%.1fs 音频，用时 %.1fs）：%s", vid, dur, time.time() - t, body.description[:60])
    return Response(r.content, media_type="audio/wav", headers={"X-Voice-Id": vid})


def clean(text: str) -> str:
    text = re.sub(r"（[^）]{0,40}）|\([^)]{0,40}\)|\*[^*]{0,40}\*", "", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


class SpeechIn(BaseModel):
    input: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default="dafeiyu-zh", max_length=40)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    stream: bool = False
    model: str | None = None
    response_format: str | None = None


@app.get("/health")
def health():
    try:
        omni = _http.get(f"{OMNI}/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        omni = False
    return {"ok": omni, "tts": omni and bool(_registered), "asr": _asr is not None, "voices": sorted(_registered)}


@app.get("/v1/voices")
def list_voices():
    return [{"id": k, "language": v.get("language")} for k, v in voices().items() if k in _registered]


def _omni_body(text: str, voice: str, speed: float, stream: bool) -> dict:
    body = {"input": text, "voice": voice, "task_type": "Base", "language": "Chinese" if re.search(r"[一-鿿]", text) else "English",
            "speed": speed, "response_format": "pcm" if stream else "wav",
            "non_streaming_mode": True}  # 整句话一次交给模型（声音照样边合成边发）：看得到后面的字，断句和语调更连贯
    if stream:
        body.update(stream=True, stream_format="audio")
    return body


@app.post("/v1/audio/speech")
def speech(body: SpeechIn):
    text = clean(body.input)
    if not text:
        raise HTTPException(400, "没有可以读的文字")
    if body.voice not in _registered:
        raise HTTPException(404, f"没有这个音色：{body.voice}")
    req = _omni_body(text, body.voice, body.speed, body.stream)
    t = time.time()
    if body.stream:
        # 用异步：用户打断（中途挂断）时请求直接被取消，合成引擎那边也马上停。
        # 以前用同步生成器，挂断后生成器挂着不收尾，过一阵被垃圾回收时去关共用连接池里的连接，
        # 正好碰上别的线程拿着连接池的锁就互相卡死，之后所有请求（连 /health）都没反应（2026-11-07 遇到）。
        async def gen():
            first = None
            n = 0
            done = False
            try:
                async with _ahttp().stream("POST", f"{OMNI}/v1/audio/speech", json=req) as r:
                    if r.status_code != 200:
                        log.error("合成出错 %s：%s", r.status_code, (await r.aread())[:200])
                        return
                    async for chunk in r.aiter_bytes():
                        if first is None:
                            first = time.time() - t
                        n += len(chunk)
                        yield chunk
                done = True
            finally:
                log.info("流式合成%s %s %d 字 → %.1fs 音频，首包 %.2fs，总 %.2fs", "" if done else "（中途挂断）", body.voice,
                         len(text), n / 2 / SAMPLE_RATE, first or 0, time.time() - t)
        return StreamingResponse(gen(), media_type="audio/pcm", headers={"X-Sample-Rate": str(SAMPLE_RATE)})
    try:
        r = _http.post(f"{OMNI}/v1/audio/speech", json=req)
    except httpx.HTTPError as e:
        raise HTTPException(503, "合成引擎没有启动") from e
    if r.status_code != 200:
        log.error("合成出错 %s：%s", r.status_code, r.text[:300])
        raise HTTPException(502, f"合成出错（{r.status_code}）")
    with wave.open(io.BytesIO(r.content)) as w:
        dur = w.getnframes() / w.getframerate()
    log.info("合成 %s %d 字 → %.1fs 音频，用时 %.2fs", body.voice, len(text), dur, time.time() - t)
    return Response(r.content, media_type="audio/wav")


def _to_wav16k(data: bytes) -> np.ndarray:
    """浏览器录的是 webm/ogg，用 ffmpeg 转成 16k 单声道。"""
    with tempfile.NamedTemporaryFile(suffix=".bin") as f:
        f.write(data)
        f.flush()
        p = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", f.name, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                           capture_output=True, timeout=60)
    if p.returncode != 0:
        raise HTTPException(400, "音频格式读不了")
    return np.frombuffer(p.stdout, dtype=np.float32)


@app.post("/v1/audio/transcriptions")
async def transcriptions(file: UploadFile = File(...), language: str = Form("auto"), model: str | None = Form(None)):
    audio = _to_wav16k(await file.read())
    if len(audio) < 1600:
        return {"text": ""}
    t = time.time()
    with _asr_lock:
        res = asr().generate(input=audio, cache={}, language=language if language in ("zh", "en", "ja", "ko", "yue") else "auto",
                             use_itn=True, batch_size_s=60)
    from funasr.utils.postprocess_utils import rich_transcription_postprocess

    text = rich_transcription_postprocess(res[0]["text"]) if res else ""
    text = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]", "", text).strip()  # SenseVoice 会在句尾加表示情绪的表情符号
    log.info("识别 %.1fs 音频 → %d 字，用时 %.2fs", len(audio) / 16000, len(text), time.time() - t)
    return {"text": text}


@app.on_event("startup")
def warmup():
    def run():
        try:
            asr()
        except Exception:  # noqa: BLE001
            log.exception("识别模型加载失败")
        for _ in range(120):  # vllm-omni 启动要一两分钟，等它好了再注册音色
            try:
                if _http.get(f"{OMNI}/health", timeout=2).status_code == 200:
                    register_voices()
                    log.info("音色已注册：%s", ", ".join(sorted(_registered)))
                    return
            except (httpx.HTTPError, RuntimeError) as e:
                log.warning("等合成引擎：%s", e)
            time.sleep(5)
        log.error("合成引擎一直没有就绪")
    threading.Thread(target=run, daemon=True).start()
