"""The 32 characters: models, variants, equipment, animations, sounds, files."""
from __future__ import annotations

from ... import roster
from ...paths import EXTRACT_DIR
from .. import HttpError, Request, router


@router.get(r"/api/roster")
def get_roster(req: Request):
    st = req.ctx.require_store()
    req.json({"characters": roster.summary(st)})


@router.get(r"/api/roster/(?P<cid>\d+)")
def get_character(req: Request, cid: str):
    st = req.ctx.require_store()
    try:
        req.json(roster.detail(st, int(cid)))
    except KeyError as ex:
        raise HttpError(404, str(ex))


@router.get(r"/api/roster/(?P<cid>\d+)/export")
def get_export(req: Request, cid: str):
    st = req.ctx.require_store()
    what = {w for w in (req.q("what") or "models,textures,sounds").split(",") if w}
    try:
        paths = roster.export(st, int(cid), EXTRACT_DIR / "characters", what)
    except KeyError as ex:
        raise HttpError(404, str(ex))
    req.json({"written": [str(p) for p in paths], "dest": str(EXTRACT_DIR / "characters")})
