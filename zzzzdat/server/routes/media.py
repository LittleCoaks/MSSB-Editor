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
        req.bytes(st.glb(e, int(sec), rig=bool(banks) or bool(parts) or req.flag("rig"), bank_keys=banks, parts=parts),
                  "model/gltf-binary", stem + ".glb")
    else:
        req.bytes(c3.to_obj(st.model(e, int(sec))).encode(), "text/plain", stem + ".obj")


@router.get(r"/api/entry/(?P<eid>\d+)/audio/(?P<n>\d+)(?:\.wav)?")
def get_audio(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    secs = float(req.q("seconds")) if req.q("seconds") else None
    if req.flag("download"):
        req.bytes(st.wav(e, int(n), secs), "audio/wav", f"{st.file_name(e).rsplit('.', 1)[0]}_{n}.wav")
    else:
        req.stream(st.wav_size(e, int(n), secs), st.wav_stream(e, int(n), secs), "audio/wav")
