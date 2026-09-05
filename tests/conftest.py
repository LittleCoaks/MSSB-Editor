"""Test fixtures. Unit tests use synthetic data only; tests marked `game`
need a configured copy of the game and are skipped otherwise."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    config.addinivalue_line("markers", "game: needs a configured game (skipped when none)")


@pytest.fixture(scope="session")
def store():
    from zzzzdat.disc import current_game
    g = current_game()
    if not g.ok or os.environ.get("MSSB_TESTS_NO_GAME"):
        pytest.skip("no game configured")
    from zzzzdat.store import Store
    return Store()
