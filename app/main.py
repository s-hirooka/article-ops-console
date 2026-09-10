"""FastAPI entrypoint.

    uvicorn app.main:app --reload            # local
    uvicorn app.main:app --host 0.0.0.0 --port $PORT   # Render

P2 scope: read-only API + server-rendered dashboard. Writes (article wizard,
prompt editing, job triggering) arrive in P3.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes_oauth import router as oauth_router
from app.api.routes_read import router as read_router
from app.api.routes_write import router as write_router
from app.config import AppSettings
from app.db.session import engine
from app.web.dashboard import router as web_router

_settings = AppSettings.from_env()

app = FastAPI(
    title=_settings.app_name,
    version="0.2.0",
    description="AI 記事作成 / SEO 解析パイプラインの運用コンソール（P2: 読み取り専用）",
)

app.include_router(read_router)
app.include_router(write_router)
app.include_router(oauth_router)
app.include_router(web_router)


@app.get("/healthz", tags=["ops"])
def healthz() -> JSONResponse:
    """Liveness + DB reachability. Render points its health check here."""
    db_ok = False
    detail = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_ok = True
    except Exception as exc:  # pragma: no cover - reported, not raised
        detail = str(exc)
    status = 200 if db_ok else 503
    return JSONResponse(
        {"status": "ok" if db_ok else "degraded", "db": db_ok, "detail": detail},
        status_code=status,
    )
