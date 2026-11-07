"""自建语音服务（算力服务器上跑）：Qwen3-TTS 合成 + SenseVoice 识别，接口和 OpenAI 兼容。

    POST /v1/audio/speech          {"input": "...", "voice": "dafeiyu-zh", "speed": 1.0}  → audio/wav
    GET  /v1/voices                已经设计好的音色
    POST /v1/audio/transcriptions  multipart: file=音频  → {"text": "..."}
    GET  /health

后端这样接：TTS_PROVIDER=qwen，QWEN_TTS_URL=http://<服务器>:8640；STT_PROVIDER=openai，STT_BASE_URL=http://<服务器>:8640/v1
音色文件（<音色>.wav + <音色>.json）放在 VOICE_DIR，跟 app/tts/server.py 用的是同一份。

    CUDA_VISIBLE_DEVICES=4 uvicorn speech_server:app --host 0.0.0.0 --port 8640
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
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
MODELS = Path(os.getenv("MODELS_DIR", HERE.parent / "models"))
VOICE_DIR = Path(os.getenv("VOICE_DIR", MODELS / "voices"))
TTS_MODEL = MODELS / os.getenv("QWEN_TTS_MODEL", "Qwen3-TTS-12Hz-1.7B-Base")
ASR_MODEL = MODELS / os.getenv("ASR_MODEL", "SenseVoiceSmall")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s speech: %(message)s")
log = logging.getLogger("speech")
app = FastAPI(title="KRINO speech")
_tts_lock = threading.Lock()
_asr_lock = threading.Lock()
_tts = None
_asr = None
_prompts: dict = {}


def tts():
    global _tts
    if _tts is None:
        from qwen_tts import Qwen3TTSModel

        t = time.time()
        _tts = Qwen3TTSModel.from_pretrained(str(TTS_MODEL), device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
        log.info("合成模型已加载：%s（%.1fs）", TTS_MODEL.name, time.time() - t)
    return _tts


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


def prompt_for(voice: str):
    if voice not in _prompts:
        meta = voices().get(voice)
        if meta is None:
            raise HTTPException(404, f"没有这个音色：{voice}")
        _prompts[voice] = tts().create_voice_clone_prompt(ref_audio=str(VOICE_DIR / f"{voice}.wav"), ref_text=meta["text"])
    return _prompts[voice]


def clean(text: str) -> str:
    text = re.sub(r"（[^）]{0,40}）|\([^)]{0,40}\)|\*[^*]{0,40}\*", "", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


class SpeechIn(BaseModel):
    input: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default="dafeiyu-zh", max_length=40)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    model: str | None = None
    response_format: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "tts": _tts is not None, "asr": _asr is not None, "voices": list(voices())}


@app.get("/v1/voices")
def list_voices():
    return [{"id": k, "language": v.get("language")} for k, v in voices().items()]


@app.post("/v1/audio/speech")
def speech(body: SpeechIn):
    text = clean(body.input)
    if not text:
        raise HTTPException(400, "没有可以读的文字")
    if body.voice not in voices():
        raise HTTPException(404, f"没有这个音色：{body.voice}")
    lang = "Chinese" if re.search(r"[一-鿿]", text) else "English"
    t = time.time()
    with _tts_lock:
        wavs, sr = tts().generate_voice_clone(text=text, language=lang, voice_clone_prompt=prompt_for(body.voice))
    audio = np.asarray(wavs[0], dtype=np.float32)
    if abs(body.speed - 1.0) > 0.02:
        n = max(1, int(len(audio) / body.speed))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    log.info("合成 %s %d 字 → %.1fs 音频，用时 %.2fs", body.voice, len(text), len(audio) / sr, time.time() - t)
    return Response(buf.getvalue(), media_type="audio/wav")


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
    log.info("识别 %.1fs 音频 → %d 字，用时 %.2fs", len(audio) / 16000, len(text), time.time() - t)
    return {"text": text}


@app.on_event("startup")
def warmup():
    def run():
        try:
            asr()
            for v in voices():
                prompt_for(v)
            log.info("预热完成：%s", ", ".join(voices()) or "（没有音色文件）")
        except Exception:  # noqa: BLE001
            log.exception("预热失败")
    threading.Thread(target=run, daemon=True).start()
