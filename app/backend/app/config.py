"""运行配置：全部来自环境变量（可放在项目根目录的 .env，示例见 .env.example）。

API 密钥只在这里读取、只在服务端使用；任何接口都不会把密钥返回给浏览器（/api/services 只报告“是否已配置”）。
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[3]  # 仓库根目录（app/backend/app/config.py 往上三层）


def _load_dotenv() -> None:
    # ENV_FILE 可以指定别的配置文件（例如本机同时跑海外版：ENV_FILE=.env.global）；环境变量优先于文件
    env_file = Path(os.environ["ENV_FILE"]) if os.getenv("ENV_FILE") else ROOT_DIR / ".env"
    if not env_file.is_absolute():
        env_file = ROOT_DIR / env_file
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


def _user_limits(raw: str) -> dict[str, int]:
    out = {}
    for item in raw.split(","):
        name, _, n = item.strip().rpartition(":")
        if name and n.strip().isdigit():
            out[name.strip()] = int(n)
    return out


def _list(key: str, default: str) -> tuple[str, ...]:
    return tuple(x.strip() for x in _env(key, default).split(",") if x.strip())


DEFAULT_LLM = "~deepseek/deepseek-flash-latest"  # OpenRouter 上最新的 DeepSeek Flash


@dataclass
class Settings:
    # 站点版本：cn = 国内版（中文、带中文商标和备案号）| global = 海外版（英文）。两个版本是两套独立部署，各用各的数据库
    edition: str = field(default_factory=lambda: _env("SITE_EDITION", "cn"))
    icp_number: str = field(default_factory=lambda: _env("ICP_NUMBER", ""))          # 国内版页脚的 ICP 备案号
    police_number: str = field(default_factory=lambda: _env("POLICE_RECORD_NUMBER", ""))  # 公安联网备案号（可选）
    # 另一个版本的网址（页脚的切换链接）：按 IP 分流不一定准，用了代理的人要能手动切过去
    other_edition_url: str = field(default_factory=lambda: _env("OTHER_EDITION_URL", ""))
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL", "postgresql+psycopg://krino:krino@localhost:5433/krino_world"))
    frontend_dir: Path = ROOT_DIR / "app" / "frontend"
    models_dir: Path = ROOT_DIR / "data" / "models"
    media_dir: Path = field(default_factory=lambda: Path(_env("MEDIA_DIR", str(ROOT_DIR / "data" / "media"))))  # 工作台生成的立绘
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
    # 直接听：按麦克风说话时，录音直接交给全模态模型（百炼 Qwen-Omni），她听得见语气和情绪，不先转成文字。
    # dashscope = 开（共用 DASHSCOPE_API_KEY）| off = 关（退回“先识别成文字”）。打字聊天不受影响，照旧用 LLM_MODEL
    hear_provider: str = field(default_factory=lambda: _env("HEAR_PROVIDER", "dashscope"))
    hear_model: str = field(default_factory=lambda: _env("HEAR_MODEL", "qwen3-omni-flash"))
    hear_max_seconds: int = field(default_factory=lambda: _int("HEAR_MAX_SECONDS", 60))
    # 价格（元 / 百万 token，按百炼北京价估算；用来记积分）
    hear_price_text_in: float = field(default_factory=lambda: _float("HEAR_PRICE_TEXT_IN", 3.2))
    hear_price_audio_in: float = field(default_factory=lambda: _float("HEAR_PRICE_AUDIO_IN", 15.8))
    hear_price_out: float = field(default_factory=lambda: _float("HEAR_PRICE_OUT", 12.7))
    # 联网：聊天时给模型一个搜索工具（OpenRouter 的 openrouter:web_search，服务端执行），她觉得需要时才查。off = 关
    web_search: str = field(default_factory=lambda: _env("WEB_SEARCH", "exa"))            # exa | parallel | perplexity | auto | off
    web_search_results: int = field(default_factory=lambda: _int("WEB_SEARCH_RESULTS", 5))  # 每次搜几条
    web_search_max_uses: int = field(default_factory=lambda: _int("WEB_SEARCH_MAX_USES", 2))  # 一句回复最多搜几次

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
    # TTS：qwen = 自建 Qwen3-TTS 语音服务（需要显卡）| dashscope = 阿里云百炼（国内版推荐）| elevenlabs = Eleven v4 | openai = OpenAI
    #      | local = 只用本地 Kokoro | browser = 浏览器朗读 | mock = 测试。qwen 和各云端出错时都自动退回 Kokoro
    tts_provider: str = field(default_factory=lambda: _env("TTS_PROVIDER", "qwen"))
    qwen_tts_url: str = field(default_factory=lambda: _env("QWEN_TTS_URL", "http://127.0.0.1:8640"))  # app/tts/server.py
    kokoro_dir: str = field(default_factory=lambda: _env("KOKORO_DIR", ""))
    tts_default_voice: str = field(default_factory=lambda: _env("TTS_DEFAULT_VOICE", ""))  # 空 = 按语言默认
    # openai：OpenAI 或兼容接口。gpt-4o-mini-tts 会按角色的声音描述（app/tts/voices.py）调整语气
    tts_model: str = field(default_factory=lambda: _env("TTS_MODEL", "gpt-4o-mini-tts"))
    tts_base_url: str = field(default_factory=lambda: _env("TTS_BASE_URL", "https://api.openai.com/v1"))
    tts_api_key: str | None = field(default_factory=lambda: os.getenv("TTS_API_KEY") or os.getenv("OPENAI_API_KEY") or None)
    tts_voices: tuple[str, ...] = field(default_factory=lambda: _list("TTS_VOICES", "coral,sage,nova,shimmer,alloy"))
    # 角色音色 → 平台自带音色（openai 和 dashscope 共用这一张表，各取认识的）
    tts_voice_map: tuple[str, ...] = field(default_factory=lambda: _list(
        "TTS_VOICE_MAP", "dafeiyu-en=coral,krino-en=sage,dafeiyu-zh=Cherry,krino-zh=Serena"))
    # dashscope：阿里云百炼 Qwen3-TTS 指令版，同样按声音描述说话。北京地域；新加坡用 https://dashscope-intl.aliyuncs.com/api/v1
    dashscope_api_key: str | None = field(default_factory=lambda: os.getenv("DASHSCOPE_API_KEY") or None)
    dashscope_base_url: str = field(default_factory=lambda: _env("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"))
    # 默认用 Qwen-Audio 3.1（2026 年 11 月 Artificial Analysis 语音榜第 4，国内能直连）；改回 qwen3-tts-instruct-flash 走旧接口
    dashscope_tts_model: str = field(default_factory=lambda: _env("DASHSCOPE_TTS_MODEL", "qwen-audio-3.1-tts-flash"))
    # Qwen-Audio 走 SpeechSynthesizer 接口，文档给的是带业务空间的域名；填了 DASHSCOPE_WORKSPACE 就用 https://{空间}.cn-beijing.maas.aliyuncs.com
    dashscope_workspace: str = field(default_factory=lambda: _env("DASHSCOPE_WORKSPACE", ""))
    dashscope_region: str = field(default_factory=lambda: _env("DASHSCOPE_REGION", "cn-beijing"))
    dashscope_voice_map: tuple[str, ...] = field(default_factory=lambda: _list(
        "DASHSCOPE_VOICE_MAP", "dafeiyu-zh=qiaoxiaojiao_v3.1,krino-zh=xuyanchu_v3.1,"  # 大肥鱼：俏丽可爱；KRINO：沉稳磁性
                               "dafeiyu-en=Cally_v3.1,krino-en=Emily_v3.1"))
    # ---------- 外观工作台：用一句话生成立绘和整套表情。dashscope = 百炼千问图像（共用 DASHSCOPE_API_KEY）
    #            | self = 自建生图服务（app/gpu/image_server.py，接口和百炼一样；出错且配了百炼密钥时退回百炼）| mock = 测试用色块 ----------
    image_provider: str = field(default_factory=lambda: _env("IMAGE_PROVIDER", "dashscope"))
    image_base_url: str = field(default_factory=lambda: _env("IMAGE_BASE_URL", ""))  # self 用：http://<服务器>:8641/api/v1
    image_api_key: str | None = field(default_factory=lambda: os.getenv("IMAGE_API_KEY") or None)
    image_model: str = field(default_factory=lambda: _env("IMAGE_MODEL", "qwen-image-3.0"))
    image_daily_limit: int = field(default_factory=lambda: int(_env("IMAGE_DAILY_LIMIT", "40")))  # 每人每天最多生成几张
    # 个别账号单独的每日张数（比如测试账号少给点）：IMAGE_USER_LIMITS=krino_demo:20,tester:0
    image_user_limits: dict = field(default_factory=lambda: _user_limits(_env("IMAGE_USER_LIMITS", "")))

    # ---------- 积分（credits.py）：对话、图片、云端语音的花费折成积分，按天限额 ----------
    credits_per_cny: float = field(default_factory=lambda: _float("CREDITS_PER_CNY", 10))     # 1 元 = 10 积分
    credit_daily_limit: float = field(default_factory=lambda: _float("CREDIT_DAILY_LIMIT", 0))  # 每人每天多少积分，0 = 不限
    credit_user_limits: dict = field(default_factory=lambda: _user_limits(_env("CREDIT_USER_LIMITS", "")))  # krino_demo:1000
    usd_cny: float = field(default_factory=lambda: _float("USD_CNY", 7.2))
    llm_price_in: float = field(default_factory=lambda: _float("LLM_PRICE_IN", 2))     # 元 / 百万输入 token（OpenRouter 没返回花费时用）
    llm_price_out: float = field(default_factory=lambda: _float("LLM_PRICE_OUT", 8))   # 元 / 百万输出 token
    image_price_cny: float = field(default_factory=lambda: _float("IMAGE_PRICE_CNY", 0.25))  # 元 / 张
    tts_price_cny: float = field(default_factory=lambda: _float("TTS_PRICE_CNY", 1))   # 元 / 万字
    # elevenlabs：Eleven v4（同一榜单第 1，海外版推荐；国内服务器要能访问 api.elevenlabs.io）。音色是 ElevenLabs 自带的 voice_id
    elevenlabs_api_key: str | None = field(default_factory=lambda: os.getenv("ELEVENLABS_API_KEY") or None)
    elevenlabs_model: str = field(default_factory=lambda: _env("ELEVENLABS_MODEL", "eleven_v4"))
    elevenlabs_base_url: str = field(default_factory=lambda: _env("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io/v1"))
    elevenlabs_voice_map: tuple[str, ...] = field(default_factory=lambda: _list(  # Jessica：俏皮年轻；Alice：冷静清晰
        "ELEVENLABS_VOICE_MAP", "dafeiyu-zh=cgSgspJ2msm6clMCkdW9,dafeiyu-en=cgSgspJ2msm6clMCkdW9,"
                                "krino-zh=Xb7hH8MSUJpSbSDYk0k2,krino-en=Xb7hH8MSUJpSbSDYk0k2"))

    # ---------- KRINO Evaluator（内部互动策略）：rules 规则策略（默认） | matrix 3-Head 模型（实验） | off ----------
    policy_mode: str = field(default_factory=lambda: _env("KRINO_POLICY", "rules"))
    matrix_checkpoint: Path = field(default_factory=lambda: Path(_env(
        "KRINO_MATRIX_CHECKPOINT", str(ROOT_DIR / "model" / "checkpoints" / "mmbert-uncertainty"))))

    # ---------- 角色、上传、创意工坊 ----------
    companion_limit: int = field(default_factory=lambda: _int("COMPANION_LIMIT", 8))
    max_import_bytes: int = field(default_factory=lambda: _int("MAX_IMPORT_BYTES", 12 * 1024 * 1024))
    workshop_admins: tuple[str, ...] = field(default_factory=lambda: _list("WORKSHOP_ADMINS", ""))
    workshop_auto_hide_reports: int = field(default_factory=lambda: _int("WORKSHOP_AUTO_HIDE_REPORTS", 3))
    workshop_require_review: bool = field(default_factory=lambda: _env("WORKSHOP_REQUIRE_REVIEW", "0") == "1")

    token_ttl_hours: int = field(default_factory=lambda: _int("TOKEN_TTL_HOURS", 168))
    auto_migrate: bool = field(default_factory=lambda: _env("AUTO_MIGRATE", "1") == "1")
    device_heartbeat_timeout_s: float = field(default_factory=lambda: _float("DEVICE_HEARTBEAT_TIMEOUT_S", 10))


settings = Settings()
if settings.edition not in ("cn", "global"):
    raise SystemExit(f"SITE_EDITION 只能是 cn 或 global，现在是 {settings.edition!r}")


def locale() -> str:
    """界面和角色用的语言：国内版中文，海外版英文。"""
    return "en" if settings.edition == "global" else "zh"


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
        "tts": _tts_status(svc),
    }


def _tts_status(svc) -> dict:
    s = settings
    if s.tts_provider == "qwen":
        from .voice import _qwen_voices

        if _qwen_voices():
            return svc("qwen", "Qwen3-TTS 1.7B", True, "按人设设计的音色：" + "、".join(_qwen_voices()))
    if s.tts_provider in ("local", "qwen"):
        from .tts_local import available

        ok, why = available()
        note = "本地合成，免费离线" if ok else why + "；暂时用浏览器朗读"
        if s.tts_provider == "qwen":
            note = "Qwen3-TTS 语音服务没有启动，暂时用 Kokoro（scripts/world.sh tts 启动）"
        return svc("local", "Kokoro-82M", ok, note)
    if s.tts_provider == "dashscope":
        return svc("dashscope", s.dashscope_tts_model, bool(s.dashscope_api_key),
                   "阿里云百炼，按人设描述说话" if s.dashscope_api_key else "没有配置 DASHSCOPE_API_KEY，暂时用 Kokoro")
    if s.tts_provider == "elevenlabs":
        return svc("elevenlabs", s.elevenlabs_model, bool(s.elevenlabs_api_key),
                   "ElevenLabs，按角色选的自带音色" if s.elevenlabs_api_key else "没有配置 ELEVENLABS_API_KEY，暂时用 Kokoro")
    if s.tts_provider == "openai":
        return svc("openai", s.tts_model, bool(s.tts_api_key),
                   "OpenAI，按人设描述说话" if s.tts_api_key else "没有配置 OPENAI_API_KEY，暂时用 Kokoro")
    return svc(s.tts_provider, "",
               s.tts_provider in ("browser", "mock"),
               {"browser": "浏览器自带语音合成", "mock": "测试用，返回提示音"}.get(s.tts_provider, ""))
