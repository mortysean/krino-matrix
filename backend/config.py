import logging
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

log = logging.getLogger("krino")


class Settings:
    # PostgreSQL in production, e.g. postgresql+psycopg://krino:pw@localhost:5432/krino; SQLite only for local dev
    database_url = os.getenv("DATABASE_URL") or f"sqlite:///{ROOT / 'data' / 'krino.db'}"
    secret_key = os.getenv("KRINO_SECRET_KEY") or ""
    session_days = int(os.getenv("KRINO_SESSION_DAYS", "14"))
    cookie_secure = os.getenv("KRINO_COOKIE_SECURE", "false").lower() == "true"     # true behind HTTPS
    daily_quota = int(os.getenv("KRINO_DAILY_QUOTA", "50"))                         # turns per user per day
    max_questions = int(os.getenv("KRINO_MAX_QUESTIONS", "3"))
    login_attempts = int(os.getenv("KRINO_LOGIN_ATTEMPTS", "5"))                   # failures per window
    login_window_s = int(os.getenv("KRINO_LOGIN_WINDOW_S", "600"))
    frontend_dist = ROOT / "frontend" / "dist"


settings = Settings()
if not settings.secret_key:
    settings.secret_key = secrets.token_urlsafe(32)
    log.warning("KRINO_SECRET_KEY is not set: using a random key, sessions end when the server restarts")
