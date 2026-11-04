"""本地语音合成：Kokoro-82M 中文版（hexgrad/Kokoro-82M-v1.1-zh，Apache-2.0）。

不需要密钥、不联网，CPU 上约 2 秒生成 5 秒语音。模型和音色在 data/models/kokoro-zh/，
用 scripts/fetch_assets.py 下载（git 不收录）。没有模型或没装 kokoro 时 available() 为 False，前端退回浏览器朗读。

国内版说中文：100 个音色，zf_* 女声、zm_* 男声。海外版说英文：af_maple、af_sol（美式）、bf_vale（英式），
英文发音规则需要 misaki[en]。编号没有含义，只能试听挑选。
"""
from __future__ import annotations

import io
import logging
import re
import threading
import wave
from pathlib import Path

from .config import ROOT_DIR, locale, settings

log = logging.getLogger("krino.tts")
MODEL_DIR = Path(settings.kokoro_dir) if settings.kokoro_dir else ROOT_DIR / "data" / "models" / "kokoro-zh"
REPO = "hexgrad/Kokoro-82M-v1.1-zh"
RATE = 24000

LANG = {"zh": ("z", ("zf_", "zm_"), "zf_001"), "en": ("a", ("af_", "bf_"), "af_maple")}  # 语言 → (Kokoro 语言码, 音色前缀, 默认音色)

# 按人设设计的 Qwen3-TTS 音色 → 语音服务不在时用的最接近的 Kokoro 音色
FALLBACK = {"dafeiyu-zh": "zf_017", "krino-zh": "zf_032", "dafeiyu-en": "af_maple", "krino-en": "bf_vale"}

_lock = threading.Lock()
_model = None
_pipes: dict = {}
_voices: dict = {}
_failed: str | None = None


def voices() -> list[str]:
    d = MODEL_DIR / "voices"
    prefixes = LANG[locale()][1]
    return sorted(p.stem for p in d.glob("*.pt") if p.stem.startswith(prefixes)) if d.exists() else []


def default_voice() -> str:
    v = settings.tts_default_voice
    return v if v in voices() else LANG[locale()][2]


def available() -> tuple[bool, str]:
    if _failed:
        return False, _failed
    if not (MODEL_DIR / "kokoro-v1_1-zh.pth").exists():
        return False, "没有本地语音模型，运行 scripts/fetch_assets.py tts 下载"
    try:
        import kokoro  # noqa: F401
    except ImportError:
        return False, "没有安装 kokoro（pip install -r requirements.txt）"
    return True, ""


def _load():
    """加载模型（两种语言共用一个模型）和当前语言的发音管线。"""
    global _model, _failed
    with _lock:
        lang = LANG[locale()][0]
        if lang not in _pipes and _failed is None:
            try:
                from kokoro import KModel, KPipeline

                if _model is None:
                    _model = KModel(repo_id=REPO, config=str(MODEL_DIR / "config.json"),
                                    model=str(MODEL_DIR / "kokoro-v1_1-zh.pth")).eval()
                _pipes[lang] = KPipeline(lang_code=lang, repo_id=REPO, model=_model)
                log.info("本地语音模型已加载：%s（%s）", MODEL_DIR, lang)
            except Exception as e:  # noqa: BLE001
                _failed = f"语音模型加载失败：{type(e).__name__}: {e}"[:200]
                log.exception("Kokoro 加载失败")
        return _pipes.get(lang)


def _voice(name: str):
    import torch

    if name not in _voices:
        p = MODEL_DIR / "voices" / f"{name}.pt"
        if not p.exists():
            raise ValueError(f"没有这个音色：{name}")
        _voices[name] = torch.load(p, weights_only=True)
    return _voices[name]


def clean(text: str) -> str:
    """去掉括号里的动作描写和颜文字，只读对白。"""
    text = re.sub(r"（[^）]{0,40}）|\([^)]{0,40}\)|\*[^*]{0,40}\*", "", text)
    text = re.sub(r"[~～]+", "，", text)
    return re.sub(r"\s+", " ", text).strip()[:400]


def synthesize(text: str, voice: str | None, speed: float = 1.0) -> bytes:
    """返回 24kHz 单声道 16-bit WAV。"""
    import numpy as np

    pipe = _load()
    if pipe is None:
        raise RuntimeError(_failed or "语音模型不可用")
    voice = FALLBACK.get(voice or "", voice)
    name = voice if voice in voices() else default_voice()
    text = clean(text) or "……"
    with _lock:  # 模型不是线程安全的
        chunks = [r.audio for r in pipe(text, voice=_voice(name), speed=max(0.6, min(1.6, speed)))]
    audio = np.concatenate([c.numpy() for c in chunks]) if chunks else np.zeros(RATE // 10, "float32")
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def warmup() -> None:
    if available()[0]:
        threading.Thread(target=lambda: _load() and synthesize("你好", None), name="tts-warmup", daemon=True).start()
