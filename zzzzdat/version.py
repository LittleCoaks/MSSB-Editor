"""The program's version and where its releases live.

VERSION is the single source of truth: build.py stamps it into the
executables and installers, the updater compares it with the newest GitHub
release, and tests check that pyproject.toml agrees. Releases are tagged
`vX.Y` (or `vX.Y.Z`), and the tag has to say the same thing as this: `parse`
pads to three parts, so `v0.2` and `0.2.0` are the same version, but `v0.2`
against a VERSION of `0.1.0` is the mistake the release workflow stops.
"""
VERSION = "0.2"
REPO = "LittleCoaks/MSSB-Editor"          # GitHub owner/name whose Releases carry the installers
RELEASES_URL = f"https://github.com/{REPO}/releases"


def parse(v: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3), padded to three parts so 'v0.1' equals '0.1.0';
    anything unparseable sorts lowest."""
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
    out = (out or [0]) + [0] * (3 - len(out))
    return tuple(out[:max(3, len(out))])


def newer(candidate: str, current: str = VERSION) -> bool:
    return parse(candidate) > parse(current)
