"""Run the whole application with one command.

    python -m app              # serve API + UI on http://127.0.0.1:8000
    python -m app --reload     # auto-reload for backend development
    python -m app --port 9000

Build the frontend once first (``cd frontend && npm run build``); this process
then serves it.
"""
from __future__ import annotations

import argparse

import uvicorn

from .config import settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app", description=settings.app_name)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Reload on backend code changes.")
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    if not (settings.frontend_dist / "index.html").is_file():
        print(
            f"! No frontend build at {settings.frontend_dist}\n"
            "  Run: cd frontend && npm install && npm run build\n"
            "  The API will still start; the web UI will show build instructions.\n"
        )

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        # uvicorn rejects workers>1 together with reload.
        workers=None if args.reload else args.workers,
    )


if __name__ == "__main__":
    main()
