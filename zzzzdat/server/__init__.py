"""Local HTTP server: python -m zzzzdat serve

A small router over BaseHTTPRequestHandler. Routes live in `routes/`; state in
`context.AppContext`; long work in `jobs.Jobs`. Reads run concurrently (the
Store serialises per entry); mutations take `ctx.write_lock`.
"""
from __future__ import annotations

import json
import re
import threading
import webbrowser
from email.parser import BytesParser
from email.policy import default as email_default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlparse

from ..edit import EditError
from .context import AppContext, NoGame


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class Request:
    """What a route handler gets: parsed URL, body, and response helpers."""

    def __init__(self, handler: "Handler", body: bytes):
        u = urlparse(handler.path)
        self.path = u.path
        self.query = {k: v[0] for k, v in parse_qs(u.query).items()}
        self.headers = handler.headers
        self.body = body
        self.ctx: AppContext = handler.ctx
        self._h = handler

    def q(self, key: str, default: str | None = None) -> str | None:
        return self.query.get(key, default)

    def flag(self, key: str) -> bool:
        return self.query.get(key, "") not in ("", "0", "false")

    def form(self) -> dict:
        """Multipart form fields: files as (filename, bytes), others as str."""
        msg = BytesParser(policy=email_default).parsebytes(
            b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + self.body)
        out = {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            fname = part.get_filename()
            payload = part.get_payload(decode=True)
            out[name] = (fname, payload) if fname else payload.decode("utf-8", "replace")
        return out

    # responses --------------------------------------------------------
    def json(self, obj, status: int = 200) -> None:
        self._h.send_json(obj, status)

    def bytes(self, body: bytes, ctype: str, filename: str | None = None, cache: str = "no-cache") -> None:
        self._h.send_bytes(body, ctype, filename, cache)

    def stream(self, total: int, gen, ctype: str) -> None:
        self._h.send_stream(total, gen, ctype)


Route = tuple[str, "re.Pattern[str]", Callable[..., None]]


class Router:
    def __init__(self):
        self.routes: list[Route] = []

    def _add(self, method: str, pattern: str, fn: Callable) -> Callable:
        self.routes.append((method, re.compile(pattern), fn))
        return fn

    def get(self, pattern: str):
        return lambda fn: self._add("GET", pattern, fn)

    def post(self, pattern: str):
        return lambda fn: self._add("POST", pattern, fn)

    def dispatch(self, method: str, req: Request) -> bool:
        for m, rx, fn in self.routes:
            if m != method:
                continue
            match = rx.fullmatch(req.path)
            if match:
                fn(req, **match.groupdict())
                return True
        return False


router = Router()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # keep-alive and byte ranges, which <audio> needs
    ctx: AppContext = None  # set by start_server

    def log_message(self, fmt, *args):  # quiet
        pass

    def _handle(self, method: str) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        req = Request(self, body)
        try:
            if not router.dispatch(method, req):
                self.send_json({"error": "not found"}, 404)
        except HttpError as ex:
            self.send_json({"error": str(ex)}, ex.status)
        except (NoGame, EditError, FileNotFoundError) as ex:
            self.send_json({"error": str(ex)}, 400)
        except KeyError as ex:
            self.send_json({"error": str(ex)}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as ex:  # surfaced to the page rather than killing the server
            self.send_json({"error": f"{type(ex).__name__}: {ex}"}, 500)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    # low-level responses ----------------------------------------------
    def send_json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, ctype: str, filename: str | None = None, cache: str = "no-cache") -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def send_stream(self, total: int, gen, ctype: str) -> None:
        """Stream a body of known length, honouring a single byte Range."""
        rng = self.headers.get("Range")
        start, end = 0, total - 1
        if rng and rng.startswith("bytes="):
            a, _, b = rng[6:].partition("-")
            start = int(a) if a else max(0, total - int(b))
            end = int(b) if (b and a) else total - 1
            end = min(end, total - 1)
        partial = rng is not None
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        pos = 0
        left = end - start + 1
        for chunk in gen:
            if left <= 0:
                break
            cstart, cend = pos, pos + len(chunk)
            pos = cend
            if cend <= start:
                continue
            piece = chunk[max(0, start - cstart):][:left]
            self.wfile.write(piece)
            left -= len(piece)
        self.wfile.flush()


def start_server(port: int | None = None) -> tuple[ThreadingHTTPServer, str, AppContext]:
    """Start serving on a background thread. Returns (server, url, context)."""
    from . import routes  # noqa: F401  (registers the routes)
    ctx = AppContext()
    ctx.load_store()
    Handler.ctx = ctx
    httpd = ThreadingHTTPServer(("127.0.0.1", port or 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True, name="http").start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}/", ctx


def serve(port: int = 8420, open_browser: bool = True) -> None:
    httpd, url, ctx = start_server(port)
    if ctx.store:
        print(f"MSSB Editor: {url}  (archive: {ctx.store.archive.path}, {len(ctx.store.entries)} entries)")
    else:
        print(f"MSSB Editor: {url}  (no game selected yet: {ctx.store_error})")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.shutdown()
