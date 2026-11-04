"""KRINO WORLD 后端入口：FastAPI + PostgreSQL。前端（原生 JS，无构建）由同一个端口提供。"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, chat, devices, events, memory, personas, policy, voice, workshop
from .config import ROOT_DIR, locale, settings
from .i18n import tr
from .db import SessionLocal, migrate


def _setup_logging() -> None:
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    if not root.handlers:
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        root.addHandler(h)
    root.setLevel(logging.INFO)
    try:  # 错误日志另存一份文件，方便排查
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(settings.log_dir / "error.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(logging.WARNING)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass


_setup_logging()
log = logging.getLogger("krino")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.auto_migrate:
        migrate()
    db = SessionLocal()
    try:
        memory.purge_expired_candidates(db)
        personas.refresh_official(db)
        from . import catalog

        catalog.seed(db)
    finally:
        db.close()
    if settings.policy_mode == "matrix":  # 模型加载要十几秒：后台预热，别让第一位用户等
        import threading

        from .policy import MatrixPolicy
        threading.Thread(target=MatrixPolicy.evaluator, name="matrix-warmup", daemon=True).start()
    if settings.tts_provider == "local":  # 预热本地语音，第一句话不用等加载
        from .tts_local import warmup
        warmup()
    log.info("KRINO WORLD 启动（%s 版）：LLM=%s/%s policy=%s STT=%s TTS=%s VLM=%s", settings.edition, settings.llm_provider, settings.llm_model,
             settings.policy_mode, settings.stt_provider, settings.tts_provider, settings.vlm_provider)
    yield


app = FastAPI(title="KRINO WORLD", version="0.1.0", lifespan=lifespan)
for module in (auth, personas, chat, memory, policy, voice, workshop, devices, events):
    app.include_router(module.router)


COMPANY = {"zh": "杭州决策矩阵科技有限公司", "en": "Hangzhou Krino Matrix Tech Co., Ltd."}


@app.get("/api/site")
def site():
    """站点版本信息，前端启动时先取：商标、语言、页脚（国内版的备案号）。不需要登录。"""
    return {"edition": settings.edition, "locale": locale(), "product": "KRINO WORLD",
            "brand": {"zh": "决策矩阵", "en": "KRINO MATRIX"}, "company": COMPANY[locale()],
            "icp": settings.icp_number if settings.edition == "cn" else "",
            "police": settings.police_number if settings.edition == "cn" else "",
            "switch": {"url": settings.other_edition_url, "label": "Global" if settings.edition == "cn" else "中国大陆"}
            if settings.other_edition_url else None}


@app.exception_handler(HTTPException)
async def translated_errors(request: Request, exc: HTTPException):
    """海外版：报错信息翻译成英文（国内版原样）。"""
    if isinstance(exc.detail, str):
        exc.detail = tr(exc.detail)
    return await http_exception_handler(request, exc)


@app.middleware("http")
async def timing(request: Request, call_next):
    """记录每个接口的延迟和 5xx；前端文件不带哈希，让浏览器每次先问一下有没有新版本（304 很便宜）。"""
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception as e:  # noqa: BLE001
        log.exception("未处理的错误：%s %s", request.method, request.url.path)
        events.error(request.url.path, f"{type(e).__name__}: {e}")
        resp = JSONResponse({"detail": tr("服务器出错了，请稍后再试")}, status_code=500)
    path = request.url.path
    if path.startswith("/api/"):
        route = request.scope.get("route")
        events.observe(f"{request.method} {getattr(route, 'path', path)}", (time.perf_counter() - t0) * 1000,
                       resp.status_code)
    elif path == "/" or path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


if settings.models_dir.exists():  # 下载的 Live2D 模型等素材（scripts/fetch_assets.py），只读
    app.mount("/models", StaticFiles(directory=settings.models_dir), name="models")
LANDING_DIR = ROOT_DIR / "app" / "landing"  # krinomatrix.com 品牌首页（Caddy 把整站改写到 /landing/）
if LANDING_DIR.exists():
    app.mount("/landing", StaticFiles(directory=LANDING_DIR, html=True), name="landing")
if settings.frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=settings.frontend_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(settings.frontend_dir / "index.html")
