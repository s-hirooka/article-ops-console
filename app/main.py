"""FastAPI entrypoint.

    uvicorn app.main:app --reload            # local
    uvicorn app.main:app --host 0.0.0.0 --port $PORT   # Render

Serves the read/write API, the Google OAuth flow, and the server-rendered
holding dashboard. The Next.js frontend (P5) is a separate origin and calls
this API cross-origin — hence CORS below (set CORS_ORIGINS to the Vercel URL).
"""
from __future__ import annotations

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes_cron import router as cron_router
from app.api.routes_oauth import router as oauth_router
from app.api.routes_read import router as read_router
from app.api.routes_write import router as write_router
from app.config import AppSettings
from app.db.session import engine
from app.web.dashboard import router as web_router

_settings = AppSettings.from_env()

app = FastAPI(
    title=_settings.app_name,
    version="0.5.0",
    description="AI 記事作成 / SEO 解析パイプラインの運用コンソール",
)

# CORS_ORIGINS: comma-separated exact origins for the frontend. Falls back to
# allowing any localhost port + *.onrender.com + *.vercel.app for convenience
# (the API has no cookie auth, so this is acceptable for a single-tenant tool).
_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["http://localhost:3000"],
    allow_origin_regex=r"https://[a-z0-9-]+\.(onrender\.com|vercel\.app)|http://localhost:\d+",
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)

app.include_router(read_router)
app.include_router(write_router)
app.include_router(oauth_router)
app.include_router(cron_router)
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
