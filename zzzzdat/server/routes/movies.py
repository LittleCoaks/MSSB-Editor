"""HVQM4 movies: decode through the native helper (as a job), then serve
frames by number and the audio track; export frames + WAV, or the whole movie
as one MP4 (also a job - encoding the intro is not a request-sized wait)."""
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
    mp4job = req.ctx.jobs.find(f"movie-mp4:{e.id}")
    out = {"ready": m is not None, "helper": hvqm.helper_path() is not None,
           "job": job.id if job and job.state == "running" else None,
           "ffmpeg": hvqm.ffmpeg_path() is not None,
           "mp4": m is not None and m.has_mp4(),
           "mp4_job": mp4job.id if mp4job and mp4job.state == "running" else None}
    if m:
        out.update(m.info)
        if out["mp4"]:
            out["mp4_size"] = m.mp4_path().stat().st_size
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


@router.post(r"/api/entry/(?P<eid>\d+)/movie/mp4")
def post_mp4(req: Request, eid: str):
    """Encode (or mux) the decoded movie into one MP4, as a job."""
    _st, e, m = _movie(req, eid)
    if m is None:
        raise HttpError(404, "movie not decoded yet")
    if m.has_mp4():
        return req.json({"ready": True})
    existing = req.ctx.jobs.find(f"movie-mp4:{e.id}")
    if existing and existing.state == "running":
        return req.json({"job": existing.id})

    def work(job):
        m.make_mp4(progress=job.set_progress)
        return {"ready": True}

    req.json({"job": req.ctx.jobs.start(f"movie-mp4:{e.id}", work).id})


@router.get(r"/api/entry/(?P<eid>\d+)/movie\.mp4")
def get_mp4(req: Request, eid: str):
    st, e, m = _movie(req, eid)
    if m is None or not m.has_mp4():
        raise HttpError(404, "no MP4 for this movie yet; POST movie/mp4 first")
    path = m.mp4_path()
    size = path.stat().st_size

    def chunks():
        with open(path, "rb") as f:
            while True:
                b = f.read(1 << 20)
                if not b:
                    return
                yield b

    name = st.file_name(e).rsplit(".", 1)[0] + ".mp4"
    req.stream(size, chunks(), "video/mp4", name, inline=False)


@router.get(r"/api/entry/(?P<eid>\d+)/movie/export")
def get_export(req: Request, eid: str):
    st, e, m = _movie(req, eid)
    if m is None:
        raise HttpError(404, "movie not decoded yet")
    dest = EXTRACT_DIR / (st.file_name(e).rsplit(".", 1)[0] + "_movie")
    written = m.export(dest)
    req.json({"written": [str(p) for p in written], "dest": str(dest)})
