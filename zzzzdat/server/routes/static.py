"""The UI itself: the built Svelte app at /, the legacy page at /legacy."""
from __future__ import annotations

from ...paths import UI_DIR
from .. import HttpError, Request, router

DIST_DIR = UI_DIR / "dist"
MIME = {".js": "application/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8",
        ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2",
        ".json": "application/json", ".map": "application/json"}


@router.get(r"/")
def index(req: Request):
    page = DIST_DIR / "index.html" if (DIST_DIR / "index.html").exists() else UI_DIR / "index.html"
    req.bytes(page.read_bytes(), "text/html; charset=utf-8")


@router.get(r"/legacy")
def legacy(req: Request):
    req.bytes((UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")


@router.get(r"/assets/(?P<name>[A-Za-z0-9_.-]+)")
def asset(req: Request, name: str):
    p = DIST_DIR / "assets" / name
    if not p.is_file():
        raise HttpError(404, "not found")
    req.bytes(p.read_bytes(), MIME.get(p.suffix, "application/octet-stream"), cache="max-age=86400")


@router.get(r"/vendor/(?P<name>[A-Za-z0-9_.-]+\.js)")
def vendor(req: Request, name: str):
    p = UI_DIR / "vendor" / name
    if not p.is_file():
        raise HttpError(404, "not found")
    req.bytes(p.read_bytes(), "application/javascript", cache="max-age=86400")
