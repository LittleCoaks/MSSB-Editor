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

from . import c3, catalog, music
from .edit import EditError, Editor
from .thumbs import ThumbJob

THUMBS = ThumbJob()
from .disc import Game, current_game, default_dump_dir, dump_iso, list_dir, set_game
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
        if audio.name.startswith("zzzzdat_"):  # only delete our own upload copies
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
DIST_DIR = UI_DIR / "dist"
MIME = {".js": "application/javascript", ".css": "text/css", ".html": "text/html; charset=utf-8", ".svg": "image/svg+xml",
        ".png": "image/png", ".ico": "image/x-icon", ".woff2": "font/woff2", ".json": "application/json", ".map": "application/json"}


def entry_summary(e) -> dict:
    return {"id": e.id, "offset": e.offset, "disc_size": e.disc_size, "size": e.size,
            "compressed": e.compressed, "lookback_bits": e.lookback_bits, "repeat_bits": e.repeat_bits,
            "kind": e.kind, "ntex": e.ntex, "nsec": e.nsec, "module": e.module, "symbol": e.symbol,
            "archive": e.archive, "name": e.name, "refs": e.refs, "label": e.label, "names": e.names, "known": e.known, "naud": e.naud, "thumb": e.thumb}


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
    protocol_version = "HTTP/1.1"  # keep-alive + ranges, which <audio> needs
    store: Store | None = None  # None when no game is configured yet
    store_error: str = ""
    lock = threading.Lock()

    @classmethod
    def load_store(cls) -> None:
        THUMBS.stop()
        try:
            cls.store = Store()
            cls.store_error = ""
            THUMBS.start(cls.store)
        except Exception as ex:
            cls.store = None
            cls.store_error = str(ex)

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

    def send_stream(self, total: int, gen, ctype: str):
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
        try:
            for chunk in gen:
                if left <= 0:
                    break
                cstart, cend = pos, pos + len(chunk)
                pos = cend
                if cend <= start:
                    continue
                piece = chunk[max(0, start - cstart):]
                piece = piece[:left]
                self.wfile.write(piece)
                left -= len(piece)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass

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
            if parts[:2] == ["api", "game"]:
                return self.game_post(parts[2:], q, body)
            if parts[:2] == ["api", "entry"] and len(parts) == 4:
                return self.entry_post(parts[2], parts[3], q, body)
            return self.fail("not found")
        except EditError as ex:
            return self.fail(str(ex), 400)
        except Exception as ex:
            return self.fail(f"{type(ex).__name__}: {ex}", 500)

    def game_post(self, rest, q, body):
        if not rest:
            path = q.get("path") or body.decode("utf-8", "replace").strip()
            try:
                g = set_game(path)
            except FileNotFoundError as ex:
                return self.fail(str(ex), 400)
            with self.lock:
                Handler.load_store()
            return self.send_json({**g.describe(), "entries": len(self.store.entries) if self.store else 0,
                                   "error": self.store_error or None})
        if rest == ["dump"]:
            g = current_game()
            if not g.iso:
                return self.fail("the current game is not an ISO", 400)
            dest = q.get("dest") or str(default_dump_dir(g))
            only = q.get("only") or None
            job = {"id": uuid.uuid4().hex, "state": "running", "progress": 0.0, "dest": dest}
            JOBS[job["id"]] = job

            def work():
                try:
                    dump_iso(dest, only, progress=lambda d, t: job.__setitem__("progress", d / max(t, 1)), game=g)
                    with self.lock:
                        Handler.load_store()
                    job["state"] = "done"
                except Exception as ex:
                    job["state"] = "error"
                    job["error"] = f"{type(ex).__name__}: {ex}"
            threading.Thread(target=work, daemon=True).start()
            return self.send_json({"job": job["id"]})
        return self.fail("not found")

    def entry_post(self, id_, action, q, body):
        st = self.store
        if st is None:
            return self.fail("no game selected", 400)
        e = st.get(id_)
        with self.lock:
            ed = Editor(st.game)
            if action == "replace":
                form = parse_multipart(self.headers, body)
                if "file" in form:
                    _fname, payload = form["file"]
                else:
                    payload = Path(form["path"]).read_bytes()
                r = ed.replace(e, payload)
                st.forget(e)
                st.thumb_png(e, build=True)
                return self.send_json(r)
            if action == "restore":
                ed.restore(e)
                st.forget(e)
                return self.send_json({"ok": True})
        return self.fail("not found")

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
            track = form.get("track") or q.get("track")
            pad = (form.get("pad") or q.get("pad", "1")) not in ("0", "false", "")
            if "file" in form:
                fname, payload = form["file"]
                tmp = Path(tempfile.gettempdir()) / f"zzzzdat_{uuid.uuid4().hex}_{Path(fname).name}"
                tmp.write_bytes(payload)
            else:  # a path picked with the native dialog: encode in place
                tmp = Path(form["path"])
                if not tmp.is_file():
                    return self.fail(f"{tmp} not found", 400)
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
                page = DIST_DIR / "index.html" if (DIST_DIR / "index.html").exists() else UI_DIR / "index.html"
                return self.send_bytes(page.read_bytes(), "text/html; charset=utf-8")
            if parts == ["legacy"]:
                return self.send_bytes((UI_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
            if parts[0] == "assets" and len(parts) == 2 and (DIST_DIR / "assets" / parts[1]).is_file():
                p = DIST_DIR / "assets" / parts[1]
                return self.send_bytes(p.read_bytes(), MIME.get(p.suffix, "application/octet-stream"))
            if parts[0] == "vendor" and len(parts) == 2 and parts[1].endswith(".js"):
                p = UI_DIR / "vendor" / parts[1]
                if p.exists():
                    return self.send_bytes(p.read_bytes(), "application/javascript")
                return self.fail("not found")
            if parts[0] != "api":
                return self.fail("not found")
            # reads run concurrently; the Store serialises per entry, and only
            # mutations (POST) take the global lock
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
            if st is None:
                return self.send_json({"meta": {}, "archive": None, "archive_size": 0, "entries": [],
                                       "error": self.store_error or "no game selected"})
            doc = json.loads(st.index_path.read_text(encoding="utf-8")) if st.index_path.exists() else {}
            return self.send_json({"meta": doc.get("meta", {}), "archive": str(st.archive.path),
                                   "archive_size": st.archive.size, "extract_dir": str(EXTRACT_DIR),
                                   "entries": [entry_summary(e) for e in st.entries]})
        if parts[0] == "game":
            g = current_game()
            edit_ready = bool(g.files_dir and (g.files_dir / "ZZZZ.dat").exists() and (g.files_dir / "aaaa.dat").exists() and g.dol_path())
            return self.send_json({**g.describe(), "entries": len(st.entries) if st else 0, "edit_ready": edit_ready,
                                   "thumbs": THUMBS.state(),
                                   "error": self.store_error or None, "default_dump": str(default_dump_dir(g)) if g.iso else None})
        if parts[0] == "fs":
            return self.send_json(list_dir(q.get("path") or None))
        if parts[0] == "job" and len(parts) == 2:
            return self.send_json(JOBS.get(parts[1]) or {"error": "no such job"})
        if st is None:
            return self.fail(self.store_error or "no game selected", 400)
        if parts[0] == "thumb" and len(parts) == 2:
            e = st.get(parts[1].split(".")[0])
            png = st.thumb_png(e, build=bool(q.get("build")))
            if png is None:
                return self.fail("not built yet")
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "max-age=3600")
            self.end_headers()
            self.wfile.write(png)
            return
        if parts == ["modified"]:
            return self.send_json({"ids": st.modified_ids()})
        if parts == ["thumbs"]:
            return self.send_json(THUMBS.state())
        if parts == ["catalog"]:
            return self.send_json(catalog.build_catalog(st.entries))
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
            return self.send_bytes(st.texture_png(e, n), "image/png")
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
            if q.get("download"):
                return self.send_bytes(st.wav(e, n, secs), "audio/wav", f"{st.file_name(e).rsplit('.', 1)[0]}_{n}.wav")
            return self.send_stream(st.wav_size(e, n, secs), st.wav_stream(e, n, secs), "audio/wav")
        if rest == ["extract"]:
            paths = st.extract(e, EXTRACT_DIR, raw=bool(q.get("raw")), png=bool(q.get("png")), wav=bool(q.get("wav")),
                               model=q.get("model"))
            return self.send_json({"written": [str(p) for p in paths]})
            return self.send_json({"written": [str(p) for p in paths]})
        return self.fail("not found")


def serve(port: int = 8420, open_browser: bool = True):
    Handler.load_store()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    if Handler.store:
        print(f"MSSB Editor: {url}  (archive: {Handler.store.archive.path}, {len(Handler.store.entries)} entries)")
    else:
        print(f"MSSB Editor: {url}  (no game selected yet: {Handler.store_error})")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
