"""KRINO MATRIX web backend.

    uvicorn backend.main:app --reload             # API on :8000; run the frontend with `npm run dev` in frontend/
    (cd frontend && npm run build) && uvicorn backend.main:app      # serves the built frontend too
"""
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .db import Base, engine
from .routers import account, auth, conversations, decisions, memories


def lazy_engine_factory():
    """Builds the decision engine on first use and reuses it; a failed build is retried on the next turn."""
    lock, built = Lock(), []

    def factory():
        with lock:
            if not built:
                from krino.engine import build_engine
                built.append(build_engine())
            return built[0]
    return factory


@asynccontextmanager
async def lifespan(app: FastAPI):
    # No migrations yet: create missing tables. Switch to Alembic before the schema changes in production.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="KRINO MATRIX", version="0.1.0", lifespan=lifespan)
app.state.engine_factory = lazy_engine_factory()
for r in (auth, conversations, decisions, memories, account):
    app.include_router(r.router)


@app.get("/api/health")
def health():
    return {"ok": True}


if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "not_found")
        file = settings.frontend_dist / path
        if path and file.is_file() and settings.frontend_dist in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(settings.frontend_dist / "index.html")
