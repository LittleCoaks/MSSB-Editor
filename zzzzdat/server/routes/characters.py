"""Character slots: cloning one character onto another slot and undoing it."""
from __future__ import annotations

from ...chars import SLOT_NAMES
from ...clone import Cloner, slot_table
from ...edit import EditError, Editor
from .. import HttpError, Request, router


def _editor(req: Request) -> Editor | None:
    st = req.ctx.require_store()
    try:
        return Editor(st.game)
    except EditError:
        return None


@router.get(r"/api/characters")
def get_characters(req: Request):
    ed = _editor(req)
    req.json({"slots": slot_table(ed), "editable": ed is not None})


@router.post(r"/api/characters/clone")
def post_clone(req: Request):
    st = req.ctx.require_store()
    try:
        source, target = int(req.q("source", "")), int(req.q("target", ""))
    except ValueError:
        raise HttpError(400, "source and target slot numbers are required")
    copy = req.q("copy", "1") not in ("0", "false")
    with req.ctx.write_lock:
        r = Cloner(Editor(st.game)).clone(source, target, copy)
        req.ctx.load_store()
    r["source_name"], r["target_name"] = SLOT_NAMES[source], SLOT_NAMES[target]
    req.json(r)


@router.post(r"/api/characters/restore")
def post_restore(req: Request):
    st = req.ctx.require_store()
    try:
        target = int(req.q("target", ""))
    except ValueError:
        raise HttpError(400, "target slot number is required")
    with req.ctx.write_lock:
        Cloner(Editor(st.game)).restore(target)
        req.ctx.load_store()
    req.json({"ok": True})
