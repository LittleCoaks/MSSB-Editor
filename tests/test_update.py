"""Version comparison, asset choice and the pyproject/version.py agreement. No network."""
import re
import sys
from pathlib import Path

from zzzzdat import update, version


def test_parse_and_newer():
    assert version.parse("v1.2.3") == (1, 2, 3)
    assert version.parse("0.10.0-rc1") == (0, 10, 0)
    assert version.newer("v9.0.0")
    assert not version.newer(version.VERSION)
    assert not version.newer("0.0.1")
    assert version.parse("garbage") == (0,)


def test_pyproject_matches_version():
    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1) == version.VERSION


def test_asset_for_platform():
    assets = [{"name": "MSSB Editor Setup 0.2.0.exe", "browser_download_url": "w"},
              {"name": "MSSB Editor 0.2.0.dmg", "browser_download_url": "m"},
              {"name": "MSSB-Editor-linux.zip", "browser_download_url": "l"}]
    a = update._asset_for_platform(assets)
    expected = {"win32": "w", "darwin": "m"}.get(sys.platform, "l")
    assert a and a["browser_download_url"] == expected
    assert update._asset_for_platform([]) is None
