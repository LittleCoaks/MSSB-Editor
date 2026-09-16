"""Test fixtures. Unit tests use synthetic data only; tests marked `game`
need the American retail build (GYQE01: their entry ids and sizes are that
disc's) and are skipped otherwise.

The build is found without touching the user's config.json, which may point
at another version: MSSB_TEST_GAME first, then the decomp repo's orig/GYQE01
(the extracted copy the edit tests need), then MSSB_GAME or the configured
game when that happens to be GYQE01. MSSB_TESTS_NO_GAME=1 skips them all (CI)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "game: needs a configured game (skipped when none)")


TEST_BUILD = "GYQE01"


def _test_game():
    from zzzzdat.disc import REPO_ROOT, Game, current_game
    tried = []
    cands = []
    if os.environ.get("MSSB_TEST_GAME"):
        cands.append(("MSSB_TEST_GAME", Game.detect(os.environ["MSSB_TEST_GAME"])))
    if REPO_ROOT and (REPO_ROOT / "orig" / TEST_BUILD).is_dir():
        cands.append(("decomp orig/" + TEST_BUILD, Game.detect(REPO_ROOT / "orig" / TEST_BUILD)))
    cands.append(("configured game", current_game()))
    for label, g in cands:
        if g.ok and g.version and g.version.key == TEST_BUILD:
            return g
        tried.append(f"{label}: {g.problem or (g.version.key if g.version else 'unknown build')}")
    return "; ".join(tried)


@pytest.fixture(scope="session")
def store():
    if os.environ.get("MSSB_TESTS_NO_GAME"):
        pytest.skip("MSSB_TESTS_NO_GAME is set")
    g = _test_game()
    if isinstance(g, str):
        pytest.skip(f"no {TEST_BUILD} (US retail) build found for the game tests: {g}")
    from zzzzdat.store import Store
    return Store(game=g)
