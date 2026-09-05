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
    Handler.load_store()
    port = port or free_port()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{port}/"


class Api:
    """Native dialogs exposed to the page as window.pywebview.api.*"""

    def __init__(self):
        self.window = None

    def pick_iso(self):
        import webview
        r = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=("GameCube images (*.iso;*.gcm)", "All files (*.*)"))
        return r[0] if r else None

    def pick_folder(self):
        import webview
        r = self.window.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else None

    def pick_audio(self):
        import webview
        r = self.window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=("Audio (*.wav;*.mp3;*.flac;*.ogg;*.m4a;*.aac;*.opus;*.wma)", "All files (*.*)"))
        return r[0] if r else None


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
        api = Api()
        api.window = webview.create_window(TITLE, url, width=width, height=height, min_size=(900, 600), js_api=api)
        webview.start()
    httpd.shutdown()
