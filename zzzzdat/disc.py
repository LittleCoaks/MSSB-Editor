"""Locate ZZZZ.dat, either as an extracted file or inside the game ISO."""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

VIEWER_ROOT = Path(__file__).resolve().parents[1]


def _find_decomp_root() -> Path:
    """The decomp repo supplies the disc files and the symbol tables.

    Resolution order: MSSB_DECOMP env var, a `decomp_path.txt` next to this
    package (one line, absolute or relative to the viewer root), then the
    sibling folder "MSSB Decomp".
    """
    env = os.environ.get("MSSB_DECOMP")
    if env:
        return Path(env)
    cfg = VIEWER_ROOT / "decomp_path.txt"
    if cfg.exists():
        return (VIEWER_ROOT / cfg.read_text(encoding="utf-8").strip()).resolve()
    return (VIEWER_ROOT.parent / "MSSB Decomp").resolve()


REPO_ROOT = _find_decomp_root()
ORIG_DIR = REPO_ROOT / "orig" / "GYQE01"

ARCHIVE_NAME = "ZZZZ.dat"


def read_fst(iso) -> dict[str, tuple[int, int]]:
    """Return {path: (offset, size)} for every file in a GameCube ISO."""
    iso.seek(0x424)
    fst_off, fst_size = struct.unpack(">II", iso.read(8))
    iso.seek(fst_off)
    fst = iso.read(fst_size)
    count = struct.unpack(">I", fst[8:12])[0]
    strings = count * 12

    def name_at(off: int) -> str:
        end = fst.index(b"\0", strings + off)
        return fst[strings + off:end].decode("ascii", "replace")

    files: dict[str, tuple[int, int]] = {}
    dirs: list[tuple[int, str]] = []  # (end index, prefix)
    for i in range(1, count):
        flag = fst[i * 12]
        name_off = struct.unpack(">I", b"\0" + fst[i * 12 + 1:i * 12 + 4])[0]
        a, b = struct.unpack(">II", fst[i * 12 + 4:i * 12 + 12])
        while dirs and i >= dirs[-1][0]:
            dirs.pop()
        prefix = dirs[-1][1] if dirs else ""
        name = name_at(name_off)
        if flag:
            dirs.append((b, prefix + name + "/"))
        else:
            files[prefix + name] = (a, b)
    return files


@dataclass
class Archive:
    """Random-access view of ZZZZ.dat's bytes, wherever they live."""

    path: Path
    base: int
    size: int
    source: str  # "file" or "iso"

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or offset + length > self.size:
            raise ValueError(f"read outside archive: {offset:#x}+{length:#x}")
        with open(self.path, "rb") as f:
            f.seek(self.base + offset)
            return f.read(length)


def find_archive(orig_dir: Path | str = ORIG_DIR) -> Archive:
    orig_dir = Path(orig_dir)
    direct = orig_dir / "files" / ARCHIVE_NAME
    if direct.exists():
        return Archive(direct, 0, direct.stat().st_size, "file")
    for iso in sorted(orig_dir.glob("*.iso")) + sorted(orig_dir.glob("*.gcm")):
        with open(iso, "rb") as f:
            files = read_fst(f)
        if ARCHIVE_NAME in files:
            off, size = files[ARCHIVE_NAME]
            return Archive(iso, off, size, "iso")
    raise FileNotFoundError(
        f"could not find {ARCHIVE_NAME}: put it at {direct} or drop the game ISO in {orig_dir}"
    )


def extract_archive(dest: Path | None = None) -> Path:
    """Copy ZZZZ.dat out of the ISO into orig/GYQE01/files (skips if present)."""
    arc = find_archive()
    dest = dest or ORIG_DIR / "files" / ARCHIVE_NAME
    if arc.source == "file":
        return arc.path
    with open(arc.path, "rb") as src, open(dest, "wb") as out:
        src.seek(arc.base)
        left = arc.size
        while left:
            chunk = src.read(min(left, 8 << 20))
            out.write(chunk)
            left -= len(chunk)
    return dest
