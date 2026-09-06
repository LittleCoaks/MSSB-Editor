"""The seven stadiums: files, models and props."""
from __future__ import annotations

from ... import stadiums
from .. import HttpError, Request, router


@router.get(r"/api/stadiums")
def get_stadiums(req: Request):
    st = req.ctx.require_store()
    req.json({"stadiums": stadiums.summary(st)})


@router.get(r"/api/stadiums/(?P<sid>\d+)")
def get_stadium(req: Request, sid: str):
    st = req.ctx.require_store()
    try:
        req.json(stadiums.detail(st, int(sid)))
    except KeyError as ex:
        raise HttpError(404, str(ex))
