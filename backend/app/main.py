"""Application entry point.

This is a single monolithic application: one process, one port, one origin.
It owns the database, the business rules, the REST API, the uploaded files and
the compiled React frontend. There is no separate web server, no API gateway
and no service boundary to keep in sync.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import api_router
from .config import settings
from .database import SessionLocal
from .services import bootstrap
from .web import mount_spa

logger = logging.getLogger("scheduler")


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap.initialise()
    logger.info(
        "Scheduler ready — database=%s storage=%s frontend=%s",
        settings.database_url.split("://", 1)[0],
        settings.storage_dir,
        "built" if (settings.frontend_dist / "index.html").is_file() else "not built",
    )
    yield


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Weekly production deployment slot scheduler.",
    lifespan=lifespan,
)

# Because the SPA is served from this same origin, the browser never makes a
# cross-origin request in production and CORS is not involved at all. It is
# enabled only for the optional Vite dev server on another port.
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,  # bearer tokens only; no cookies are issued
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
    # Never leak stack traces or SQL to the client.
    logger.exception("Unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": "An unexpected error occurred."})


def _database_ready() -> bool:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1")).scalar_one()
        return True
    except Exception:
        logger.exception("Database readiness check failed")
        return False


def _health_payload(*, ready: bool = True) -> dict:
    return {
        "status": "ok" if ready else "degraded",
        "ready": ready,
        "timezone": settings.timezone,
        "database": "ok" if ready else "unavailable",
    }


@app.get("/health", tags=["meta"])
def health() -> dict:
    return _health_payload(ready=_database_ready())


@app.get("/health/ready", tags=["meta"])
def ready() -> dict:
    ready_state = _database_ready()
    if not ready_state:
        raise HTTPException(status_code=503, detail={"status": "degraded", "database": "unavailable"})
    return _health_payload(ready=True)


@app.get("/api/health", tags=["meta"])
def api_health() -> dict:
    return _health_payload(ready=_database_ready())


app.include_router(api_router)

# Registered last so every real endpoint takes precedence over the SPA
# catch-all.
mount_spa(app, settings.frontend_dist)
