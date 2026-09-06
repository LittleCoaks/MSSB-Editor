"""Decoded media: textures, thumbnails, models, audio."""
from __future__ import annotations

from ... import c3
from .. import HttpError, Request, router


@router.get(r"/api/thumb/(?P<eid>\d+)(?:\.png)?")
def get_thumb(req: Request, eid: str):
    st = req.ctx.require_store()
    png = st.thumb_png(st.get(eid), build=req.flag("build"))
    if png is None:
        raise HttpError(404, "not built yet")
    req.bytes(png, "image/png", cache="max-age=3600")


@router.get(r"/api/entry/(?P<eid>\d+)/tex/(?P<n>\d+)(?:\.png)?")
def get_texture(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    req.bytes(st.texture_png(st.get(eid), int(n)), "image/png", cache="max-age=3600")


@router.get(r"/api/entry/(?P<eid>\d+)/model/(?P<sec>\d+)\.(?P<ext>glb|obj)")
def get_model(req: Request, eid: str, sec: str, ext: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    stem = f"{st.file_name(e).rsplit('.', 1)[0]}_s{sec}"
    if ext == "glb":
        banks = tuple(k for k in (req.q("anim") or "").split(",") if k)
        parts = req.q("parts") or ""
        variant = int(req.q("variant")) if (req.q("variant") or "").isdigit() else None
        req.bytes(st.glb(e, int(sec), rig=bool(banks) or bool(parts) or req.flag("rig"), bank_keys=banks, parts=parts,
                         variant=variant), "model/gltf-binary", stem + ".glb")
    else:
        req.bytes(c3.to_obj(st.model(e, int(sec))).encode(), "text/plain", stem + ".obj")


@router.get(r"/api/entry/(?P<eid>\d+)/song/mix\.wav")
def get_song_mix(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    ns = tuple(sorted({int(x) for x in (req.q("songs") or "").split(",") if x.strip().isdigit()}))
    if not ns:
        raise HttpError(400, "songs=0,1,... is required")
    loops = max(1, min(int(req.q("loops", "1")), 8))
    try:
        w = st.song_mix_wav(e, ns, loops)
    except RuntimeError as ex:
        raise HttpError(501, str(ex))
    stem = st.file_name(e).rsplit(".", 1)[0]
    if req.flag("download"):
        req.bytes(w, "audio/wav", f"{stem}_songs{'+'.join(str(n + 1) for n in ns)}.wav")
    else:
        req.bytes(w, "audio/wav")


@router.get(r"/api/entry/(?P<eid>\d+)/song/(?P<n>\d+)\.wav")
def get_song_wav(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    try:
        w = st.song_wav(e, int(n))
    except RuntimeError as ex:
        raise HttpError(501, str(ex))
    stem = st.file_name(e).rsplit(".", 1)[0]
    if req.flag("download"):
        req.bytes(w, "audio/wav", f"{stem}_song{int(n) + 1}.wav")
    else:
        req.bytes(w, "audio/wav")


@router.get(r"/api/entry/(?P<eid>\d+)/song/(?P<n>\d+)(?:\.mid)?")
def get_midi(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    req.bytes(st.midi(e, int(n)), "audio/midi", f"{st.file_name(e).rsplit('.', 1)[0]}_song{int(n) + 1}.mid")


@router.get(r"/api/entry/(?P<eid>\d+)/audio/(?P<n>\d+)(?:\.wav)?")
def get_audio(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    secs = float(req.q("seconds")) if req.q("seconds") else None
    if req.flag("download"):
        req.bytes(st.wav(e, int(n), secs), "audio/wav", f"{st.file_name(e).rsplit('.', 1)[0]}_{n}.wav")
    else:
        req.stream(st.wav_size(e, int(n), secs), st.wav_stream(e, int(n), secs), "audio/wav")
