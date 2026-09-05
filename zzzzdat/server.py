"""Local web UI: python -m zzzzdat serve

Serves zzzzdat/ui/index.html plus a small JSON API over the Store.
"""
from __future__ import annotations

import json
import tempfile
import threading
import uuid
import webbrowser
from email.parser import BytesParser
from email.policy import default as email_default
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import c3, music
from .store import EXTRACT_DIR, Store

JOBS: dict[str, dict] = {}


def run_install_job(job: dict, audio: Path, root, track: str, pad: bool) -> None:
    def prog(done, total):
        job["progress"] = done / max(total, 1)
    try:
        job["result"] = music.install(str(audio), root, track, progress=prog, pad_to_stock=pad)
        job["state"] = "done"
    except Exception as ex:  # surfaced to the page
        job["state"] = "error"
        job["error"] = f"{type(ex).__name__}: {ex}"
    finally:
        try:
            audio.unlink()
        except OSError:
            pass


def parse_multipart(headers, body: bytes) -> dict:
    msg = BytesParser(policy=email_default).parsebytes(
        b"Content-Type: " + headers["Content-Type"].encode() + b"\r\n\r\n" + body)
    out = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        fname = part.get_filename()
        payload = part.get_payload(decode=True)
        out[name] = (fname, payload) if fname else payload.decode("utf-8", "replace")
    return out

UI_DIR = Path(__file__).resolve().parent / "ui"


def entry_summary(e) -> dict:
    return {"id": e.id, "offset": e.offset, "disc_size": e.disc_size, "size": e.size,
            "compressed": e.compressed, "lookback_bits": e.lookback_bits, "repeat_bits": e.repeat_bits,
            "kind": e.kind, "ntex": e.ntex, "nsec": e.nsec, "module": e.module, "symbol": e.symbol,
            "archive": e.archive, "name": e.name, "refs": e.refs, "label": e.label, "names": e.names, "known": e.known, "naud": e.naud}


def entry_detail(store: Store, e) -> dict:
    d = entry_summary(e)
    fi = store.info(e)
    d["file_kind"] = fi.kind
    d["hvqm4"] = fi.hvqm4
    d["sections"] = [{"index": s.index, "offset": s.offset, "size": s.size, "kind": s.kind,
                      "magic": s.magic, "ntex": len(s.textures)} for s in fi.sections]
    d["textures"] = [{"n": n, "section": sec.index if sec else None, "index": t.index, "width": t.width,
                      "height": t.height, "fmt": t.fmt_name, "mips": t.mips, "offset": t.abs_data_offset,
                      "size": t.data_size, "tlut": t.tlut_count, "flags": t.flags.hex()}
                     for n, (sec, t) in enumerate(fi.all_textures())]
    d["audio"] = fi.audio
    d["models"] = store.models(e) if fi.kind == "container" else []
    d["file_name"] = store.file_name(e)
    return d


class Handler(BaseHTTPRequestHandler):
    store: Store = None  # set by serve()
    lock = threading.Lock()

    def log_message(self, fmt, *args):  # quieter
        pass

    # ---------------------------------------------------------- helpers --
    def send_json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, body: bytes, ctype: str, filename: str | None = None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def fail(self, msg, status=404):
        self.send_json({"error": msg}, status)

    # ------------------------------------------------------------ routes --
    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length) if length else b""
        try:
            if parts[:2] == ["api", "music"]:
                return self.music_post(parts[2:], q, body)
            return self.fail("not found")
        except Exception as ex:
            return self.fail(f"{type(ex).__name__}: {ex}", 500)

    def music_post(self, rest, q, body):
        if rest == ["root"]:
            root = music.set_game_root(q.get("path") or body.decode("utf-8", "replace").strip())
            return self.send_json({"root": str(root)})
        root = music.game_root()
        if root is None:
            return self.fail("no game dump found; run `python -m zzzzdat dump` or set the game root", 400)
        if rest == ["restore"]:
            music.restore(root, q["track"])
            return self.send_json({"ok": True})
        if rest == ["install"]:
            form = parse_multipart(self.headers, body)
            fname, payload = form["file"]
            track = form.get("track") or q.get("track")
            pad = (form.get("pad") or q.get("pad", "1")) not in ("0", "false", "")
            tmp = Path(tempfile.gettempdir()) / f"zzzzdat_{uuid.uuid4().hex}_{Path(fname).name}"
            tmp.write_bytes(payload)
            job = {"id": uuid.uuid4().hex, "state": "running", "progress": 0.0, "track": track}
            JOBS[job["id"]] = job
            threading.Thread(target=run_install_job, args=(job, tmp, root, track, pad), daemon=True).start()
            return self.send_json({"job": job["id"]})
        return self.fail("not found")

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        parts = [p for p in u.path.split("/") if p]
        try:
            if not parts:
                return self.send_bytes((UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if parts[0] == "vendor" and len(parts) == 2 and parts[1].endswith(".js"):
                p = UI_DIR / "vendor" / parts[1]
                if p.exists():
                    return self.send_bytes(p.read_bytes(), "application/javascript")
                return self.fail("not found")
            if parts[0] != "api":
                return self.fail("not found")
            with self.lock:
                return self.api(parts[1:], q)
        except KeyError as ex:
            return self.fail(str(ex))
        except Exception as ex:  # surface errors to the page instead of dying
            return self.fail(f"{type(ex).__name__}: {ex}", 500)

    def music_get(self, rest, q):
        if rest and rest[0] == "job":
            job = JOBS.get(rest[1]) if len(rest) > 1 else None
            return self.send_json(job or {"error": "no such job"})
        root = music.game_root()
        self.store.refresh_disc_entries()
        disc_ids = {e.name.rsplit("/", 1)[-1]: e.id for e in self.store.entries if e.archive == "disc"}
        tracks = music.status(root) if root else []
        for t in tracks:
            t["entry"] = disc_ids.get(t["file"])
        return self.send_json({"root": str(root) if root else None, "tracks": tracks, **music.backends(),
                               "dump_hint": "python -m zzzzdat dump" if root is None else None})

    def api(self, parts, q):
        st = self.store
        if parts == ["index"]:
            doc = json.loads(st.index_path.read_text(encoding="utf-8")) if st.index_path.exists() else {}
            return self.send_json({"meta": doc.get("meta", {}), "archive": str(st.archive.path),
                                   "archive_size": st.archive.size, "extract_dir": str(EXTRACT_DIR),
                                   "entries": [entry_summary(e) for e in st.entries]})
        if parts[0] == "music":
            return self.music_get(parts[1:], q)
        if parts[0] != "entry" or len(parts) < 2:
            return self.fail("not found")
        e = st.get(parts[1])
        rest = parts[2:]
        if not rest:
            return self.send_json(entry_detail(st, e))
        if rest == ["hex"]:
            data = st.raw(e) if q.get("raw") else st.data(e)
            off = int(q.get("offset", "0"), 0)
            ln = min(int(q.get("length", "4096"), 0), 65536)
            chunk = data[off:off + ln]
            return self.send_json({"offset": off, "total": len(data), "hex": chunk.hex()})
        if rest == ["data"]:
            return self.send_bytes(st.data(e), "application/octet-stream", st.file_name(e))
        if rest == ["raw"]:
            return self.send_bytes(st.raw(e), "application/octet-stream", st.file_name(e, "lz" if e.compressed else "bin"))
        if rest[0] == "section" and len(rest) == 2:
            s = st.info(e).sections[int(rest[1])]
            return self.send_bytes(st.data(e)[s.offset:s.offset + s.size], "application/octet-stream",
                                   f"{st.file_name(e).rsplit('.', 1)[0]}_sec{s.index}.bin")
        if rest[0] == "tex" and len(rest) == 2:
            n = int(rest[1].split(".")[0])
            sec, t = st.info(e).all_textures()[n]
            return self.send_bytes(t.decode_png(st.data(e)), "image/png")
        if rest[0] == "model" and len(rest) == 2:
            sec, ext = rest[1].rsplit(".", 1)
            stem = f"{st.file_name(e).rsplit('.', 1)[0]}_s{sec}"
            if ext == "glb":
                return self.send_bytes(st.glb(e, int(sec)), "model/gltf-binary", stem + ".glb")
            if ext == "obj":
                return self.send_bytes(c3.to_obj(st.model(e, int(sec))).encode(), "text/plain", stem + ".obj")
            return self.fail("not found")
        if rest[0] == "audio" and len(rest) == 2:
            n = int(rest[1].split(".")[0])
            secs = float(q["seconds"]) if q.get("seconds") else None
            return self.send_bytes(st.wav(e, n, secs), "audio/wav")
        if rest == ["extract"]:
            paths = st.extract(e, EXTRACT_DIR, raw=bool(q.get("raw")), png=bool(q.get("png")), wav=bool(q.get("wav")),
                               model=q.get("model"))
            return self.send_json({"written": [str(p) for p in paths]})
        return self.fail("not found")


def serve(port: int = 8420, open_browser: bool = True):
    Handler.store = Store()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"zzzzdat viewer: {url}  (archive: {Handler.store.archive.path}, {len(Handler.store.entries)} entries)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
