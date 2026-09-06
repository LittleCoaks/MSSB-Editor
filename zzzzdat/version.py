"""The program's version and where its releases live.

VERSION is the single source of truth: build.py stamps it into the
executables and installers, the updater compares it with the newest GitHub
release, and tests check that pyproject.toml agrees.
"""
VERSION = "0.1.0"
REPO = "LittleCoaks/MSSB-Editor"          # GitHub owner/name whose Releases carry the installers
RELEASES_URL = f"https://github.com/{REPO}/releases"


def parse(v: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3); anything unparseable sorts lowest."""
    v = v.strip().lstrip("vV")
    out = []
    for part in v.split("."):
        digits = ""
        for ch in part:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out) if out else (0,)


def newer(candidate: str, current: str = VERSION) -> bool:
    return parse(candidate) > parse(current)
