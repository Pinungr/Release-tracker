"""Application entry point.

This is a single monolithic application: one process, one port, one origin.
It owns the database, the business rules, the REST API, the uploaded files and
the compiled React frontend. There is no separate web server, no API gateway
and no service boundary to keep in sync.
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .api import api_router
from .config import settings
from .database import SessionLocal
from .services import ai_access_service, bootstrap
from .web import mount_spa

logger = logging.getLogger("scheduler")


@asynccontextmanager
async def lifespan(_: FastAPI):
    bootstrap.initialise()
    logger.info(
        "Scheduler ready — database=%s storage=%s frontend=%s mcp=%s ai_provider=%s",
        settings.database_url.split("://", 1)[0],
        settings.storage_dir,
        "built" if (settings.frontend_dist / "index.html").is_file() else "not built",
        "enabled" if settings.mcp_enabled else "disabled",
        settings.ai_provider,
    )
    if settings.mcp_enabled:
        from .mcp_server import mcp

        async with mcp.session_manager.run():
            yield
    else:
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
async def mcp_bearer_auth(request: Request, call_next):
    """Protect the external MCP endpoint with a dedicated read-only service key."""
    if settings.mcp_enabled and (request.url.path == "/mcp" or request.url.path.startswith("/mcp/")):
        header = request.headers.get("authorization") or ""
        token = header[7:].strip() if header.lower().startswith("bearer ") else ""
        if not token or not hmac.compare_digest(token, settings.mcp_api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "Valid MCP bearer token required."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Environment configuration only exposes the MCP transport. The
        # administrator's master AI switch is the hard runtime gate: when OFF,
        # no group, tenant or AI Users override may use MCP.
        with SessionLocal() as db:
            if not ai_access_service.master_ai_enabled(db):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "AI access is disabled centrally by the PDS administrator."},
                )
    return await call_next(request)


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


app.include_router(api_router)

if settings.mcp_enabled:
    # Imported only when enabled so normal PDS operation has no runtime MCP
    # dependency beyond the package listed in requirements.txt.
    from .mcp_server import mcp_app

    app.mount("/mcp", mcp_app)

# Registered last so every real endpoint takes precedence over the SPA
# catch-all.
mount_spa(app, settings.frontend_dist)
