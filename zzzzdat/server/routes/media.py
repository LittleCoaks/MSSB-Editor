"""Decoded media: textures, thumbnails, models, audio."""
from __future__ import annotations

from ... import c3
from .. import HttpError, Request, router


@router.get(r"/api/thumb/(?P<eid>\d+)(?:\.png)?")
def get_thumb(req: Request, eid: str):
    st = req.ctx.require_store()
    # built on demand and cached: only the Characters and Stadiums pages ask for
    # thumbnails now, a few dozen images rather than every entry in the archive
    png = st.thumb_png(st.get(eid), build=True)
    if png is None:
        raise HttpError(404, "this entry has no texture to make one from")
    req.bytes(png, "image/png", cache="max-age=3600")


@router.get(r"/api/entry/(?P<eid>\d+)/tex/(?P<n>\d+)(?:\.png)?")
def get_texture(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    req.bytes(st.texture_png(st.get(eid), int(n)), "image/png", cache="max-age=3600")


@router.get(r"/api/entry/(?P<eid>\d+)/collision\.json")
def get_collision(req: Request, eid: str):
    st = req.ctx.require_store()
    req.json(st.collision_mesh(st.get(eid)))


@router.get(r"/api/entry/(?P<eid>\d+)/model/all\.glb")
def get_scene(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    req.bytes(st.scene_glb(e), "model/gltf-binary", f"{st.file_name(e).rsplit('.', 1)[0]}_scene.glb")


@router.get(r"/api/entry/(?P<eid>\d+)/model/all\.dae")
def get_scene_dae(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    stem = f"{st.file_name(e).rsplit('.', 1)[0]}_scene"
    xml, _pngs = st.scene_collada(e, stem)
    req.bytes(xml.encode(), "model/vnd.collada+xml", stem + ".dae")


@router.get(r"/api/entry/(?P<eid>\d+)/model/(?P<sec>\d+)\.(?P<ext>glb|obj|dae)")
def get_model(req: Request, eid: str, sec: str, ext: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    stem = f"{st.file_name(e).rsplit('.', 1)[0]}_s{sec}"
    if ext == "glb":
        banks = tuple(k for k in (req.q("anim") or "").split(",") if k)
        parts = req.q("parts") or ""
        variant = int(req.q("variant")) if (req.q("variant") or "").isdigit() else None
        pose = int(req.q("pose")) if (req.q("pose") or "").isdigit() else None
        req.bytes(st.glb(e, int(sec), rig=bool(banks) or bool(parts) or req.flag("rig"), bank_keys=banks, parts=parts,
                         variant=variant, pose=pose), "model/gltf-binary", stem + ".glb")
    elif ext == "dae":
        banks = tuple(k for k in (req.q("anim") or "").split(",") if k)
        parts = req.q("parts") or ""
        variant = int(req.q("variant")) if (req.q("variant") or "").isdigit() else None
        pose = int(req.q("pose")) if (req.q("pose") or "").isdigit() else None
        xml, _pngs = st.collada(e, int(sec), stem, rig=bool(banks) or bool(parts) or req.flag("rig"),
                                bank_keys=banks, parts=parts, variant=variant, pose=pose)
        req.bytes(xml.encode(), "model/vnd.collada+xml", stem + ".dae")
    else:
        pose = int(req.q("pose")) if (req.q("pose") or "").isdigit() else None
        req.bytes(c3.to_obj(st.model(e, int(sec), pose=pose)).encode(), "text/plain", stem + ".obj")


@router.get(r"/api/entry/(?P<eid>\d+)/soundfont\.sf2")
def get_soundfont(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    req.bytes(st.soundfont(e), "audio/x-soundfont", f"{st.file_name(e).rsplit('.', 1)[0]}.sf2")


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
    name = f"{stem}_songs{'+'.join(str(n + 1) for n in ns)}.wav"
    req.bytes(w, "audio/wav", name, inline=not req.flag("download"))


@router.get(r"/api/entry/(?P<eid>\d+)/song/(?P<n>\d+)\.wav")
def get_song_wav(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    try:
        w = st.song_wav(e, int(n))
    except RuntimeError as ex:
        raise HttpError(501, str(ex))
    stem = st.file_name(e).rsplit(".", 1)[0]
    req.bytes(w, "audio/wav", f"{stem}_song{int(n) + 1}.wav", inline=not req.flag("download"))


@router.get(r"/api/entry/(?P<eid>\d+)/song/(?P<n>\d+)(?:\.mid)?")
def get_midi(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    req.bytes(st.midi(e, int(n)), "audio/midi", f"{st.file_name(e).rsplit('.', 1)[0]}_song{int(n) + 1}.mid")


@router.get(r"/api/entry/(?P<eid>\d+)/audio/(?P<n>\d+)/stereo\.wav")
def get_audio_stereo(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    w = st.stereo_wav(e, int(n))
    stem = st.file_name(e).rsplit(".", 1)[0]
    name = f"{stem}_{n}+{int(n) + 1}_stereo.wav"
    req.bytes(w, "audio/wav", name, inline=not req.flag("download"))


@router.get(r"/api/entry/(?P<eid>\d+)/audio/(?P<n>\d+)(?:\.wav)?")
def get_audio(req: Request, eid: str, n: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    secs = float(req.q("seconds")) if req.q("seconds") else None
    name = f"{st.file_name(e).rsplit('.', 1)[0]}_{n}.wav"
    if req.flag("download"):
        req.bytes(st.wav(e, int(n), secs), "audio/wav", name)
    else:
        # named even when it plays inline, so the player's own download menu
        # saves "<file>_3.wav" rather than the URL's bare "3.wav"
        req.stream(st.wav_size(e, int(n), secs), st.wav_stream(e, int(n), secs), "audio/wav", name)
