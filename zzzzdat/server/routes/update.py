"""Version and updates: check GitHub Releases, download and run the installer."""
from __future__ import annotations

from ... import update
from ...disc import load_config, save_config
from ...version import REPO, RELEASES_URL, VERSION
from .. import HttpError, Request, router


def _settings() -> dict:
    cfg = load_config()
    return {"check_updates": cfg.get("check_updates", True), "repo": cfg.get("update_repo", REPO)}


@router.get(r"/api/update")
def get_update(req: Request):
    """Current version, the setting, and the last check (a fresh one with ?check=1)."""
    s = _settings()
    out = {"version": VERSION, "releases": RELEASES_URL, **s, "status": None}
    if req.flag("check") or req.flag("force"):
        out["status"] = update.check(s["repo"], force=req.flag("force"))
    req.json(out)


@router.post(r"/api/update/settings")
def post_settings(req: Request):
    cfg = load_config()
    v = req.q("check_updates")
    if v is not None:
        cfg["check_updates"] = v not in ("0", "false")
    save_config(cfg)
    req.json(_settings())


@router.post(r"/api/update/install")
def post_install(req: Request):
    """Download the release asset for this platform on a job, then launch it."""
    s = _settings()
    st = update.check(s["repo"])
    if not st.get("available") or not st.get("asset"):
        raise HttpError(400, st.get("error") or "no update available for this platform")
    asset = st["asset"]

    def work(job):
        path = update.download(asset, job.set_progress)
        return {"path": str(path), "message": update.launch(path)}

    job = req.ctx.jobs.start("update", work, asset=asset["name"])
    req.json({"job": job.id})
