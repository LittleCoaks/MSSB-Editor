"""Replacing and restoring entries."""
from __future__ import annotations

from pathlib import Path

from ...edit import Editor
from ...texedit import replace_texture
from .. import Request, router


@router.post(r"/api/entry/(?P<eid>\d+)/replace")
def post_replace(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    form = req.form()
    payload = form["file"][1] if "file" in form else Path(form["path"]).read_bytes()
    with req.ctx.write_lock:
        r = Editor(st.game).replace(e, payload)
        st.forget(e)
        st.thumb_png(e, build=True)
        req.ctx.invalidate()
    req.json(r)


@router.post(r"/api/entry/(?P<eid>\d+)/restore")
def post_restore(req: Request, eid: str):
    st = req.ctx.require_store()
    e = st.get(eid)
    with req.ctx.write_lock:
        Editor(st.game).restore(e)
        st.forget(e)
        st.thumb_png(e, build=True)
        req.ctx.invalidate()
    req.json({"ok": True})


@router.post(r"/api/entry/(?P<eid>\d+)/tex/(?P<n>\d+)/replace")
def post_replace_texture(req: Request, eid: str, n: str):
    """Swap one texture for an uploaded PNG; the rest of the entry is unchanged."""
    st = req.ctx.require_store()
    e = st.get(eid)
    form = req.form()
    image = form["file"][1] if "file" in form else Path(form["path"]).read_bytes()
    with req.ctx.write_lock:
        resize = req.flag("resize") or form.get("resize", (None, b""))[1] in (b"1", b"true", "1", "true")
        new, info = replace_texture(st.data(e), st.info(e), int(n), image, resize=resize)
        r = Editor(st.game).replace(e, new)
        st.forget(e)
        st.thumb_png(e, build=True)
        req.ctx.invalidate()
    req.json({**r, "texture": info.as_dict()})
