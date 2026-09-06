"""The UI itself: the built Svelte app (zzzzdat/ui/dist)."""
from __future__ import annotations

from ...paths import UI_DIR
from .. import HttpError, Request, router

DIST_DIR = UI_DIR / "dist"
MIME = {".js": "application/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2",
        ".json": "application/json", ".map": "application/json"}


@router.get(r"/")
def index(req: Request):
    page = DIST_DIR / "index.html"
    if not page.exists():
        raise HttpError(500, "the UI is not built: run `npm install && npm run build` in frontend/")
    req.bytes(page.read_bytes(), "text/html; charset=utf-8")


@router.get(r"/(?P<name>favicon\.svg|icons\.svg)")
def top_level(req: Request, name: str):
    """Files Vite copies from frontend/public into the bundle root."""
    asset(req, name, DIST_DIR)


@router.get(r"/assets/(?P<name>[A-Za-z0-9_.-]+)")
def asset(req: Request, name: str, folder=DIST_DIR / "assets"):
    p = folder / name
    if not p.is_file():
        raise HttpError(404, "not found")
    req.bytes(p.read_bytes(), MIME.get(p.suffix, "application/octet-stream"), cache="max-age=86400")

