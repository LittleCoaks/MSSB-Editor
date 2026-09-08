"""Game selection, extraction, file browser, jobs."""
from __future__ import annotations

from ...disc import current_game, default_dump_dir, dump_iso, list_dir, set_game
from .. import HttpError, Request, router


def game_state(req: Request) -> dict:
    g = current_game()
    st = req.ctx.store
    edit_ready = bool(g.files_dir and (g.files_dir / "ZZZZ.dat").exists() and (g.files_dir / "aaaa.dat").exists()
                      and g.dol_path())
    return {**g.describe(), "entries": len(st.entries) if st else 0, "edit_ready": edit_ready,
            "error": req.ctx.store_error or None,
            "default_dump": str(default_dump_dir(g)) if g.iso else None,
            "indexed": bool(st and st.indexed), "index_stale": bool(st and st.index_stale),
            "index_built": (st.meta.get("built") if st else None),
            "index_path": str(st.index_path) if st else None}


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


@router.post(r"/api/game/index")
def post_index(req: Request):
    """Scan this build's executables and work out what is in its ZZZZ.dat.
    Only the US build ships with an index ready-made; every other one is
    indexed here, once, and the result is kept in the data folder."""
    ctx = req.ctx
    store = ctx.require_store()
    lines: list[str] = []

    def work(job):
        def log(*a):
            lines.append(" ".join(str(x) for x in a))
            job.set_note(lines[-1])
        with ctx.write_lock:
            store.rebuild_index(log=log)
            ctx.load_store()
        return {"entries": len(store.entries), "path": str(store.index_path)}

    job = ctx.jobs.start("index", work)
    req.json({"job": job.id})


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

