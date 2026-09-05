"""Custom music: track status, install (background), restore."""
from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from ... import music
from .. import HttpError, Request, router


@router.get(r"/api/music")
def get_music(req: Request):
    st = req.ctx.require_store()
    root = music.game_root()
    st.refresh_disc_entries()
    disc_ids = {e.name.rsplit("/", 1)[-1]: e.id for e in st.entries if e.archive == "disc"}
    tracks = music.status(root) if root else []
    for t in tracks:
        t["entry"] = disc_ids.get(t["file"])
    req.json({"root": str(root) if root else None, "tracks": tracks, **music.backends()})


@router.get(r"/api/music/job/(?P<job_id>[0-9a-f]+)")
def get_music_job(req: Request, job_id: str):
    job = req.ctx.jobs.get(job_id)
    if not job:
        raise HttpError(404, "no such job")
    req.json(job.to_dict())


@router.post(r"/api/music/root")
def post_root(req: Request):
    root = music.set_game_root(req.q("path") or req.body.decode("utf-8", "replace").strip())
    with req.ctx.write_lock:
        req.ctx.load_store()
    req.json({"root": str(root)})


@router.post(r"/api/music/restore")
def post_restore(req: Request):
    root = music.game_root()
    if root is None:
        raise HttpError(400, "the game is read-only; extract it to a folder first")
    with req.ctx.write_lock:
        music.restore(root, req.q("track"))
        req.ctx.store.refresh_disc_entries()
    req.json({"ok": True})


@router.post(r"/api/music/install")
def post_install(req: Request):
    root = music.game_root()
    if root is None:
        raise HttpError(400, "the game is read-only; extract it to a folder first")
    form = req.form()
    track = form.get("track") or req.q("track")
    pad = (form.get("pad") or req.q("pad", "1")) not in ("0", "false", "")
    if "file" in form:
        fname, payload = form["file"]
        src = Path(tempfile.gettempdir()) / f"zzzzdat_{uuid.uuid4().hex}_{Path(fname).name}"
        src.write_bytes(payload)
        temporary = True
    else:  # a path picked with the native dialog: encode in place
        src = Path(form["path"])
        temporary = False
        if not src.is_file():
            raise HttpError(400, f"{src} not found")
    ctx = req.ctx

    def work(job):
        try:
            with ctx.write_lock:
                r = music.install(str(src), root, track, progress=job.set_progress, pad_to_stock=pad)
                if ctx.store:
                    ctx.store.refresh_disc_entries()
            return r
        finally:
            if temporary:
                src.unlink(missing_ok=True)

    job = ctx.jobs.start("music-install", work, track=track)
    req.json({"job": job.id})
