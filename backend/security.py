import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User

COOKIE = "krino_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except ValueError:
        return False


def make_token(user_id: str) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_days)
    return jwt.encode({"sub": user_id, "exp": expires}, settings.secret_key, algorithm="HS256")


def new_reset_token() -> tuple[str, str]:
    """A reset token and the hash that is stored; the token itself is never stored."""
    token = secrets.token_urlsafe(32)
    return token, hash_reset_token(token)


def hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "not_authenticated")
    try:
        user_id = jwt.decode(token, settings.secret_key, algorithms=["HS256"])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(401, "not_authenticated")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(401, "not_authenticated")
    return user


class LoginLimiter:
    """Failed logins per email and per client address within a sliding window. In-process: one instance per worker."""

    def __init__(self):
        self.failures: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def _recent(self, key: str) -> deque[float]:
        q = self.failures[key]
        while q and time.monotonic() - q[0] > settings.login_window_s:
            q.popleft()
        return q

    def blocked(self, *keys: str) -> bool:
        with self.lock:
            return any(len(self._recent(k)) >= settings.login_attempts for k in keys)

    def fail(self, *keys: str):
        with self.lock:
            for k in keys:
                self._recent(k).append(time.monotonic())

    def clear(self, *keys: str):
        with self.lock:
            for k in keys:
                self.failures.pop(k, None)


limiter = LoginLimiter()
