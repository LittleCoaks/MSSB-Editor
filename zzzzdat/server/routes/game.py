"""Game selection, extraction, file browser, jobs, thumbnails status."""
from __future__ import annotations

from ...disc import current_game, default_dump_dir, dump_iso, list_dir, set_game
from .. import HttpError, Request, router


def game_state(req: Request) -> dict:
    g = current_game()
    st = req.ctx.store
    edit_ready = bool(g.files_dir and (g.files_dir / "ZZZZ.dat").exists() and (g.files_dir / "aaaa.dat").exists()
                      and g.dol_path())
    return {**g.describe(), "entries": len(st.entries) if st else 0, "edit_ready": edit_ready,
            "thumbs": req.ctx.thumbs.state(), "error": req.ctx.store_error or None,
            "default_dump": str(default_dump_dir(g)) if g.iso else None}


@router.get(r"/api/game")
def get_game(req: Request):
    req.json(game_state(req))


@router.post(r"/api/game")
def post_game(req: Request):
    path = req.q("path") or req.body.decode("utf-8", "replace").strip()
    try:
        set_game(path)
    except FileNotFoundError as ex:
        raise HttpError(400, str(ex))
    with req.ctx.write_lock:
        req.ctx.load_store()
    req.json(game_state(req))


@router.post(r"/api/game/dump")
def post_dump(req: Request):
    g = current_game()
    if not g.iso:
        raise HttpError(400, "the current game is not an ISO")
    dest = req.q("dest") or str(default_dump_dir(g))
    only = req.q("only") or None
    ctx = req.ctx

    def work(job):
        dump_iso(dest, only, progress=job.set_progress, game=g)
        with ctx.write_lock:
            ctx.load_store()
        return {"dest": dest}

    job = ctx.jobs.start("dump", work, dest=dest)
    req.json({"job": job.id})


@router.get(r"/api/fs")
def get_fs(req: Request):
    req.json(list_dir(req.q("path") or None))


@router.get(r"/api/job/(?P<job_id>[0-9a-f]+)")
def get_job(req: Request, job_id: str):
    job = req.ctx.jobs.get(job_id)
    if not job:
        raise HttpError(404, "no such job")
    req.json(job.to_dict())


@router.get(r"/api/thumbs")
def get_thumbs(req: Request):
    req.json(req.ctx.thumbs.state())
