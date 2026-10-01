"""AtmosGuard FastAPI application.

Run in development:      uvicorn app.main:app --reload --port 8000
Serve the built UI too:  npm --prefix ../frontend run build && uvicorn app.main:app
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import settings

app = FastAPI(
    title="AtmosGuard API",
    version=settings.version,
    description=(
        "AI-based forecast bust risk and early-warning system. "
        "Decision support only - not an official weather warning service."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)


def _mount_frontend() -> None:
    """Serve the built React app so the demo runs from a single process."""
    dist = settings.frontend_dist
    if not settings.serve_frontend or not dist.is_dir():
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(dist / "index.html")

    # Client-side routing: any non-/api path falls back to the SPA shell.
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = dist / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


_mount_frontend()
