"""测试环境：独立的测试库（krino_world_test），离线 mock 模型，每次运行前清空并按迁移重建表结构。"""
import os
import uuid

import pytest

os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://krino:krino@localhost:5433/krino_world_test")
os.environ["LLM_PROVIDER"] = "mock"
os.environ["VLM_PROVIDER"] = "mock"
os.environ["STT_PROVIDER"] = "mock"
os.environ["TTS_PROVIDER"] = "mock"
os.environ["KRINO_POLICY"] = "rules"
os.environ["WORKSHOP_ADMINS"] = "admin_tester"
os.environ["WORKSHOP_AUTO_HIDE_REPORTS"] = "2"
os.environ["AUTO_MIGRATE"] = "0"
os.environ["LOG_DIR"] = "/tmp/krino-world-test-logs"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import engine, migrate  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    migrate()  # 用真实的迁移建表，顺便测试迁移本身
    with TestClient(app) as c:
        yield c


class Helper:
    def __init__(self, client, token, info):
        self.c, self.token, self.info = client, token, info
        self.h = {"Authorization": f"Bearer {token}"}

    def __getattr__(self, method):
        if method not in ("get", "post", "put", "patch", "delete"):
            raise AttributeError(method)
        return lambda url, **kw: getattr(self.c, method)(url, headers=self.h, **kw)

    def ok(self, method, url, **kw):
        r = getattr(self, method)(url, **kw)
        assert r.status_code == 200, f"{method.upper()} {url} → {r.status_code} {r.text}"
        return r.json()

    @property
    def official(self):
        return next(c for c in self.ok("get", "/api/characters") if c["official"])

    def session(self, cid):
        return self.ok("post", "/api/sessions", json={"character_id": cid})["id"]

    def say(self, sid, text, wait=True, **kw):
        out = self.ok("post", f"/api/sessions/{sid}/messages", json={"text": text, **kw})
        if wait and out.get("memory_job"):
            out["job"] = self.ok("get", f"/api/memory-jobs/{out['memory_job']}", params={"wait": 10})
            assert out["job"]["status"] in ("done", "failed"), out["job"]
        return out

    def memories(self, cid, **params):
        return self.ok("get", "/api/memories", params={"character_id": cid, **params})


def make_user(client, name=None):
    name = name or "t" + uuid.uuid4().hex[:10]
    r = client.post("/api/auth/register", json={"username": name, "password": "secret123"})
    assert r.status_code == 200, r.text
    return Helper(client, r.json()["token"], r.json()["user"])


@pytest.fixture
def user(client):
    return make_user(client)


@pytest.fixture
def other(client):
    return make_user(client)
