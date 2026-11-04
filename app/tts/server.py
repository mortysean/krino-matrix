"""KRINO WORLD 语音服务：Qwen3-TTS（阿里开源，Apache-2.0），对外是 OpenAI 兼容的 /v1/audio/speech。

为什么单独一个服务：Qwen3-TTS 要的 torch / transformers 版本和主程序（KRINO Matrix 模型）不同，放在独立的
conda 环境 krino_tts 里；主程序通过 TTS_PROVIDER=qwen 调用，服务不可用时主程序自动退回 Kokoro。

每个角色的音色是“设计出来再克隆”的：scripts/design_voices.py 用 VoiceDesign 模型按 app/tts/voices.py 的描述
生成一段参考音频，存到 data/models/voices/<音色>.wav；这里用 Base 模型克隆它，所以同一个角色每句话的声音一致。

    scripts/world.sh tts            # 启动（默认 127.0.0.1:8640）
    POST /v1/audio/speech  {"input": "...", "voice": "dafeiyu-zh", "speed": 1.0}  → audio/wav
    GET  /v1/voices        已经设计好的音色
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
MODELS = Path(os.getenv("QWEN_TTS_DIR", ROOT / "data" / "models" / "qwen3-tts"))
VOICE_DIR = Path(os.getenv("VOICE_DIR", ROOT / "data" / "models" / "voices"))
BASE_MODEL = MODELS / os.getenv("QWEN_TTS_MODEL", "Qwen3-TTS-12Hz-1.7B-Base")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s tts: %(message)s")
log = logging.getLogger("tts")
app = FastAPI(title="KRINO WORLD TTS")
_lock = threading.Lock()
_model = None
_prompts: dict = {}


def model():
    global _model
    if _model is None:
        from qwen_tts import Qwen3TTSModel

        t = time.time()
        _model = Qwen3TTSModel.from_pretrained(str(BASE_MODEL), device_map="cuda:0" if torch.cuda.is_available() else "cpu",
                                               dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                                               attn_implementation="sdpa")
        log.info("模型已加载：%s（%.1fs）", BASE_MODEL.name, time.time() - t)
    return _model


def voices() -> dict:
    out = {}
    for meta in sorted(VOICE_DIR.glob("*.json")):
        if (VOICE_DIR / f"{meta.stem}.wav").exists():
            out[meta.stem] = json.loads(meta.read_text(encoding="utf-8"))
    return out


def prompt_for(voice: str):
    """克隆用的参考：同一个音色只算一次。"""
    if voice not in _prompts:
        meta = voices().get(voice)
        if meta is None:
            raise HTTPException(404, f"没有这个音色：{voice}")
        _prompts[voice] = model().create_voice_clone_prompt(ref_audio=str(VOICE_DIR / f"{voice}.wav"), ref_text=meta["text"])
    return _prompts[voice]


def clean(text: str) -> str:
    """去掉括号里的动作描写；保留语气词和标点（它们决定停顿和语气）。"""
    text = re.sub(r"（[^）]{0,40}）|\([^)]{0,40}\)|\*[^*]{0,40}\*", "", text)
    return re.sub(r"\s+", " ", text).strip()[:500]


class SpeechIn(BaseModel):
    input: str = Field(min_length=1, max_length=2000)
    voice: str = Field(default="dafeiyu-zh", max_length=40)
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    model: str | None = None            # 兼容 OpenAI 的字段，忽略
    response_format: str | None = None  # 只输出 wav


@app.get("/health")
def health():
    return {"ok": True, "loaded": _model is not None, "voices": list(voices())}


@app.get("/v1/voices")
def list_voices():
    return [{"id": k, "language": v.get("language")} for k, v in voices().items()]


@app.post("/v1/audio/speech")
def speech(body: SpeechIn):
    text = clean(body.input)
    if not text:
        raise HTTPException(400, "没有可以读的文字")
    meta = voices().get(body.voice)
    if meta is None:
        raise HTTPException(404, f"没有这个音色：{body.voice}")
    lang = "Chinese" if re.search(r"[一-鿿]", text) else "English"
    t = time.time()
    with _lock:  # 一张显卡一次只合成一句
        wavs, sr = model().generate_voice_clone(text=text, language=lang, voice_clone_prompt=prompt_for(body.voice))
    audio = np.asarray(wavs[0], dtype=np.float32)
    if abs(body.speed - 1.0) > 0.02:  # 简单变速：重采样（音调会跟着变一点，幅度小时听不出来）
        n = max(1, int(len(audio) / body.speed))
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    buf = io.BytesIO()
    sf.write(buf, audio, sr, format="WAV", subtype="PCM_16")
    log.info("%s %d 字 → %.1fs 音频，用时 %.1fs", body.voice, len(text), len(audio) / sr, time.time() - t)
    return Response(buf.getvalue(), media_type="audio/wav")


@app.on_event("startup")
def warmup():
    def run():
        try:
            for v in voices():
                prompt_for(v)
            log.info("预热完成：%s", ", ".join(voices()) or "（还没有设计音色，先运行 scripts/design_voices.py）")
        except Exception:  # noqa: BLE001
            log.exception("预热失败")
    threading.Thread(target=run, daemon=True).start()
