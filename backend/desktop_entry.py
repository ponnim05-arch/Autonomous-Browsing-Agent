"""Start the local FastAPI backend for the packaged desktop application."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import uvicorn


def main() -> None:
    if not os.getenv("PORT"):
        raise RuntimeError("The desktop launcher must provide a local backend port.")

    if getattr(sys, "frozen", False):
        os.environ.setdefault(
            "APP_FRONTEND_DIST",
            str(Path(sys.executable).resolve().parent / "frontend"),
        )

    from server import app

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=int(os.environ["PORT"]),
            log_level="info",
            access_log=False,
        )
    )
    app.state.desktop_uvicorn_server = server
    server.run()


if __name__ == "__main__":
    main()
