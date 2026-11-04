"""运行配置：全部来自环境变量（可放在项目根目录的 .env，示例见 .env.example）。

API 密钥只在这里读取、只在服务端使用；任何接口都不会把密钥返回给浏览器（/api/services 只报告“是否已配置”）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_file = ROOT_DIR / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if value[:1] in ('"', "'"):
            value = value[1:].split(value[0], 1)[0]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # 行尾注释
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def _env(key: str, default: str = "") -> str:
    return os.getenv(key) or default


def _int(key: str, default: int) -> int:
    return int(_env(key, str(default)))


def _float(key: str, default: float) -> float:
    return float(_env(key, str(default)))


def _list(key: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(key, default).split(",") if x.strip())


DEFAULT_LLM = "~deepseek/deepseek-flash-latest"  # OpenRouter 上最新的 DeepSeek Flash


@dataclass
class Settings:
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL", "postgresql+psycopg://krino:krino@localhost:5433/krino_world"))
    frontend_dir: Path = ROOT_DIR / "frontend"
    log_dir: Path = field(default_factory=lambda: Path(_env("LOG_DIR", str(ROOT_DIR / ".run" / "logs"))))

    # ---------- LLM：openrouter | mock（离线演示/测试，无需密钥） ----------
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "openrouter"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", DEFAULT_LLM))
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL", "https://openrouter.ai/api/v1"))
    llm_api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_OPENROUTER_API_KEY") or None)
    llm_max_tokens: int = field(default_factory=lambda: _int("LLM_MAX_TOKENS", 2000))
    llm_reasoning: str = field(default_factory=lambda: _env("LLM_REASONING", "off"))  # off | low | medium | high
    llm_timeout_s: float = field(default_factory=lambda: _float("LLM_TIMEOUT_S", 60))
    # 角色可选的聊天模型（白名单，第一个是默认）。后台任务（记忆整理、摘要）始终用 LLM_MODEL
    llm_character_models: tuple[str, ...] = field(default_factory=lambda: _list("LLM_CHARACTER_MODELS", DEFAULT_LLM))

    # ---------- VLM：上传图像 / 摄像头画面理解。mock | openai（OpenAI 兼容 /chat/completions + image_url） ----------
    vlm_provider: str = field(default_factory=lambda: _env("VLM_PROVIDER", "mock"))
    vlm_model: str = field(default_factory=lambda: _env("VLM_MODEL", ""))
    vlm_base_url: str = field(default_factory=lambda: _env("VLM_BASE_URL", ""))
    vlm_api_key: str | None = field(default_factory=lambda: os.getenv("VLM_API_KEY") or None)
    max_image_bytes: int = field(default_factory=lambda: _int("MAX_IMAGE_BYTES", 4 * 1024 * 1024))

    # ---------- 语音：browser = 浏览器自带（Web Speech API）；openai = OpenAI 兼容接口，由服务端转发；mock = 测试 ----------
    stt_provider: str = field(default_factory=lambda: _env("STT_PROVIDER", "browser"))
    stt_model: str = field(default_factory=lambda: _env("STT_MODEL", "whisper-1"))
    stt_base_url: str = field(default_factory=lambda: _env("STT_BASE_URL", ""))
    stt_api_key: str | None = field(default_factory=lambda: os.getenv("STT_API_KEY") or None)
    max_audio_bytes: int = field(default_factory=lambda: _int("MAX_AUDIO_BYTES", 10 * 1024 * 1024))
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "browser"))
    tts_model: str = field(default_factory=lambda: _env("TTS_MODEL", "tts-1"))
    tts_base_url: str = field(default_factory=lambda: _env("TTS_BASE_URL", ""))
    tts_api_key: str | None = field(default_factory=lambda: os.getenv("TTS_API_KEY") or None)
    tts_voices: tuple[str, ...] = field(default_factory=lambda: _list("TTS_VOICES", "alloy,nova,shimmer,echo"))

    # ---------- KRINO Evaluator（内部互动策略）：rules 规则策略（默认） | matrix 3-Head 模型（实验） | off ----------
    policy_mode: str = field(default_factory=lambda: _env("KRINO_POLICY", "rules"))
    matrix_checkpoint: Path = field(default_factory=lambda: Path(_env(
        "KRINO_MATRIX_CHECKPOINT", str(ROOT_DIR / "model" / "checkpoints" / "mmbert-uncertainty"))))

    # ---------- 角色、上传、创意工坊 ----------
    companion_limit: int = field(default_factory=lambda: _int("COMPANION_LIMIT", 8))
    vrm_max_bytes: int = field(default_factory=lambda: _int("VRM_MAX_BYTES", 40 * 1024 * 1024))
    max_import_bytes: int = field(default_factory=lambda: _int("MAX_IMPORT_BYTES", 12 * 1024 * 1024))
    workshop_admins: tuple[str, ...] = field(default_factory=lambda: _list("WORKSHOP_ADMINS", ""))
    workshop_auto_hide_reports: int = field(default_factory=lambda: _int("WORKSHOP_AUTO_HIDE_REPORTS", 3))
    workshop_require_review: bool = field(default_factory=lambda: _env("WORKSHOP_REQUIRE_REVIEW", "0") == "1")

    token_ttl_hours: int = field(default_factory=lambda: _int("TOKEN_TTL_HOURS", 168))
    auto_migrate: bool = field(default_factory=lambda: _env("AUTO_MIGRATE", "1") == "1")
    device_heartbeat_timeout_s: float = field(default_factory=lambda: _float("DEVICE_HEARTBEAT_TIMEOUT_S", 10))


settings = Settings()


def model_choices() -> list[dict]:
    return [{"id": m, "default": i == 0} for i, m in enumerate(settings.llm_character_models)]


def chat_model_for(chosen: str | None) -> str:
    """角色选了白名单里的模型就用它，否则用默认模型。"""
    if chosen and chosen in settings.llm_character_models:
        return chosen
    return settings.llm_character_models[0] if settings.llm_character_models else settings.llm_model


def service_status() -> dict:
    """各模型服务的配置状态，给设置页看。只说“配没配”，不返回密钥和地址。"""
    def svc(provider: str, model: str, ready: bool, note: str = "") -> dict:
        return {"provider": provider, "model": model, "ready": ready, "note": note}

    s = settings
    llm_ready = s.llm_provider == "mock" or bool(s.llm_api_key)
    return {
        "llm": svc(s.llm_provider, s.llm_model if s.llm_provider != "mock" else "", llm_ready,
                   "离线模板回复，只用于演示和测试" if s.llm_provider == "mock" else ("" if llm_ready else "缺少 OPENROUTER_API_KEY")),
        "vlm": svc(s.vlm_provider, s.vlm_model, s.vlm_provider == "mock" or bool(s.vlm_base_url and s.vlm_model),
                   "模拟描述：只读取颜色和亮度，不理解画面内容" if s.vlm_provider == "mock" else ""),
        "stt": svc(s.stt_provider, s.stt_model if s.stt_provider == "openai" else "",
                   s.stt_provider in ("browser", "mock") or bool(s.stt_base_url),
                   {"browser": "浏览器自带识别（Chrome 会把音频发给浏览器厂商的服务）", "mock": "测试用，返回固定文字"}.get(s.stt_provider, "")),
        "tts": svc(s.tts_provider, s.tts_model if s.tts_provider == "openai" else "",
                   s.tts_provider in ("browser", "mock") or bool(s.tts_base_url),
                   {"browser": "浏览器自带语音合成", "mock": "测试用，返回提示音"}.get(s.tts_provider, "")),
    }
