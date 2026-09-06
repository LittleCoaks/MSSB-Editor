"""HVQM4 movies: decode through the native helper (as a job), then serve
frames by number and the audio track; export frames + WAV."""
from __future__ import annotations

from ... import hvqm
from ...paths import EXTRACT_DIR
from ...thumbs import game_key
from .. import HttpError, Request, router


def _movie(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    if e.kind != "hvqm4":
        raise HttpError(400, "not a movie")
    return st, e, hvqm.load(game_key(st.game), e.id)


@router.get(r"/api/entry/(?P<eid>\d+)/movie")
def get_movie(req: Request, eid: str):
    st, e, m = _movie(req, eid)
    job = req.ctx.jobs.find(f"movie:{e.id}")
    out = {"ready": m is not None, "helper": hvqm.helper_path() is not None, "job": job.id if job and job.state == "running" else None}
    if m:
        out.update(m.info)
    req.json(out)


@router.post(r"/api/entry/(?P<eid>\d+)/movie/prepare")
def post_prepare(req: Request, eid: str):
    st, e, m = _movie(req, eid)
    if m is not None:
        return req.json({"ready": True})
    if hvqm.helper_path() is None:
        raise HttpError(501, "the HVQM4 helper (native/bin/hvqm4dec) is not built; see README 'Movies'")
    existing = req.ctx.jobs.find(f"movie:{e.id}")
    if existing and existing.state == "running":
        return req.json({"job": existing.id})
    key = game_key(st.game)
    data = st.data(e)

    def work(job):
        hvqm.decode(key, e.id, data, progress=job.set_progress)
        return {"ready": True}

    job = req.ctx.jobs.start(f"movie:{e.id}", work)
    req.json({"job": job.id})


@router.get(r"/api/entry/(?P<eid>\d+)/movie/frame/(?P<n>\d+)(?:\.jpg)?")
def get_frame(req: Request, eid: str, n: str):
    _st, _e, m = _movie(req, eid)
    if m is None:
        raise HttpError(404, "movie not decoded yet")
    i = int(n)
    if i >= len(m.index):
        raise HttpError(404, "no such frame")
    req.bytes(m.frame(i), "image/jpeg", cache="max-age=3600")


@router.get(r"/api/entry/(?P<eid>\d+)/movie/audio(?:\.wav)?")
def get_audio(req: Request, eid: str):
    _st, _e, m = _movie(req, eid)
    if m is None:
        raise HttpError(404, "movie not decoded yet")
    req.bytes(m.audio().read_bytes(), "audio/wav", cache="max-age=3600")


@router.get(r"/api/entry/(?P<eid>\d+)/movie/export")
def get_export(req: Request, eid: str):
    st, e, m = _movie(req, eid)
    if m is None:
        raise HttpError(404, "movie not decoded yet")
    dest = EXTRACT_DIR / (st.file_name(e).rsplit(".", 1)[0] + "_movie")
    written = m.export(dest)
    req.json({"written": [str(p) for p in written], "dest": str(dest)})
