"""Serving of the built single-page application.

This is what makes the project a single deployable monolith: one FastAPI
process answers both `/api/...` and every browser URL, from one origin. No
reverse proxy, no second web server, and no CORS — the SPA fetches relative
`/api` paths on the origin it was served from.

The frontend is still a separate *build* (Vite), just not a separate
*deployment*: `npm run build` writes `frontend/dist`, and everything below
serves that directory.
"""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, Response

logger = logging.getLogger("scheduler")

#: Prefixes owned by the API/tooling. Anything else is an SPA route.
API_PREFIXES = ("/api", "/docs", "/redoc", "/openapi.json")

#: Vite emits content-hashed filenames into this directory, so they can be
#: cached forever. index.html must never be cached or clients would keep
#: booting an old bundle after a release.
IMMUTABLE_DIRS = ("assets",)

NO_BUILD_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Frontend not built</title>
<style>
 body{font:16px/1.6 system-ui,sans-serif;max-width:40rem;margin:4rem auto;padding:0 1.5rem;color:#1e293b}
 h1{font-size:1.25rem} code{background:#f1f5f9;padding:.15rem .4rem;border-radius:.25rem}
 pre{background:#f8fafc;border:1px solid #e2e8f0;border-radius:.5rem;padding:1rem;overflow:auto}
</style></head><body>
<h1>Production Deployment Scheduler — frontend not built</h1>
<p>The API is running, but no compiled frontend was found at <code>{dist}</code>.</p>
<pre>cd frontend
npm install
npm run build</pre>
<p>Then reload this page. The API itself is available at
<a href="/docs">/docs</a>.</p>
</body></html>
"""


def _safe_asset(dist: Path, url_path: str) -> Path | None:
    """Resolve a request path to a file inside ``dist``, or None.

    Rejects anything that escapes the build directory, so a crafted URL such
    as ``/../../.env`` can never be served.
    """
    candidate = (dist / url_path.lstrip("/")).resolve()
    if candidate != dist and dist not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _cache_headers(url_path: str) -> dict[str, str]:
    first = url_path.lstrip("/").split("/", 1)[0]
    if first in IMMUTABLE_DIRS:
        return {"Cache-Control": "public, max-age=31536000, immutable"}
    return {"Cache-Control": "no-store, max-age=0"}


def mount_spa(app: FastAPI, dist: Path) -> None:
    """Register the catch-all that serves the SPA.

    Must be called *after* the API router so real endpoints win, and an
    unknown `/api/...` path still returns a JSON 404 rather than HTML.
    """

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str, request: Request) -> Response:
        url_path = request.url.path

        if url_path.startswith(API_PREFIXES):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Endpoint not found.")

        index = dist / "index.html"
        if not index.is_file():
            logger.warning("No frontend build found at %s", dist)
            return HTMLResponse(NO_BUILD_PAGE.format(dist=dist), status_code=503)

        asset = _safe_asset(dist, url_path)
        if asset is not None:
            return FileResponse(asset, headers=_cache_headers(url_path))

        # Every other path is a client-side route (including
        # /booking/manage/<token>): hand back the shell and let React route.
        return FileResponse(index, headers={"Cache-Control": "no-store, max-age=0"})
