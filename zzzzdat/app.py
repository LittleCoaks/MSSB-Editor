"""Desktop window: python -m zzzzdat app

Runs the same HTTP server as `serve` on a loopback port in a background
thread and shows the UI in a native window through pywebview (Edge WebView2
on Windows, WebKit on macOS/Linux). If pywebview is not installed it falls
back to the default browser so the tool still works.
"""
from __future__ import annotations

import socket
import threading
import webbrowser
from http.server import ThreadingHTTPServer

from .server import Handler
from .store import Store

TITLE = "MSSB Editor"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int | None = None) -> tuple[ThreadingHTTPServer, str]:
    Handler.store = Store()
    port = port or free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}/"


def run(port: int | None = None, width: int = 1400, height: int = 900) -> None:
    httpd, url = start_server(port)
    print(f"{TITLE}: {url}  ({len(Handler.store.entries)} entries)")
    try:
        import webview
    except ImportError:
        print("pywebview is not installed (pip install pywebview); opening in the browser instead")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
    else:
        webview.create_window(TITLE, url, width=width, height=height, min_size=(900, 600))
        webview.start()
    httpd.shutdown()
