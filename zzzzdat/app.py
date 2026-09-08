"""Desktop window: python -m zzzzdat app

Runs the same HTTP server as `serve` on a loopback port in a background
thread and shows the UI in a native window through pywebview (Edge WebView2
on Windows, WebKit on macOS/Linux). If pywebview is not installed it falls
back to the default browser so the tool still works.
"""
from __future__ import annotations

import sys
import threading
import webbrowser

from .paths import UI_DIR
from .server import start_server

TITLE = "MSSB Editor"
# Window icon (drawn by tools/make_icon.py). WinForms wants an .ico; GTK, Qt and Cocoa take a .png.
ICON = UI_DIR / ("icon.ico" if sys.platform == "win32" else "icon.png")


class Api:
    """Native dialogs exposed to the page as window.pywebview.api.*"""

    def __init__(self):
        self._window = None

    def pick_iso(self):
        import webview
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=("GameCube images (*.iso;*.gcm)", "All files (*.*)"))
        return r[0] if r else None

    def pick_folder(self):
        import webview
        r = self._window.create_file_dialog(webview.FOLDER_DIALOG)
        return r[0] if r else None

    def pick_audio(self):
        import webview
        r = self._window.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                           file_types=("Audio (*.wav;*.mp3;*.flac;*.ogg;*.m4a;*.aac;*.opus;*.wma)", "All files (*.*)"))
        return r[0] if r else None


def run(port: int | None = None, width: int = 1400, height: int = 900) -> None:
    httpd, url, ctx = start_server(port)
    print(f"{TITLE}: {url}  ({len(ctx.store.entries) if ctx.store else 0} entries)")
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
        # pywebview cancels every download unless this is set, so in the desktop
        # window the WAV / glTF / SoundFont / raw-file links would do nothing at
        # all; with it, each backend asks where to save (WinForms SaveFileDialog
        # on Windows) using the name the server's Content-Disposition gives.
        webview.settings["ALLOW_DOWNLOADS"] = True
        api = Api()
        api._window = webview.create_window(TITLE, url, width=width, height=height, min_size=(900, 600), js_api=api, text_select=True)
        webview.start(icon=str(ICON) if ICON.is_file() else None)
    httpd.shutdown()
