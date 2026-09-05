"""Locate ZZZZ.dat, either as an extracted file or inside the game ISO."""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path

import sys

# Where user-facing files live (index/, extracted/, decomp_path.txt). In a
# PyInstaller bundle that is the folder next to the executable; bundled
# read-only data (the shipped index) is found through PACKAGE_DATA.
if getattr(sys, "frozen", False):
    VIEWER_ROOT = Path(sys.executable).resolve().parent
    PACKAGE_DATA = Path(getattr(sys, "_MEIPASS", VIEWER_ROOT))
else:
    VIEWER_ROOT = Path(__file__).resolve().parents[1]
    PACKAGE_DATA = VIEWER_ROOT


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
    # sibling "MSSB Decomp" of this folder or of any parent (so a build under
    # dist/ still finds it during development)
    for parent in [VIEWER_ROOT] + list(VIEWER_ROOT.parents):
        cand = parent / "MSSB Decomp"
        if (cand / "orig").is_dir():
            return cand.resolve()
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


def dump_iso(dest: Path | str | None = None, only: str | None = None, log=lambda *a: None) -> Path:
    """Extract the game's files out of the ISO into a Dolphin-style dump:
    <dest>/files/... and <dest>/sys/{main.dol,boot.bin,bi2.bin,apploader.img,fst.bin}.
    Existing files are left alone. `only` limits to paths starting with it
    (e.g. "snd/"). Default destination is orig/GYQE01 in the decomp folder,
    which is also where the viewer looks for a writable game root."""
    arc = find_archive()
    if arc.source != "iso":
        raise FileNotFoundError("no ISO found to dump from")
    dest = Path(dest) if dest else ORIG_DIR
    files_dir = dest / "files"
    sys_dir = dest / "sys"
    with open(arc.path, "rb") as iso:
        files = read_fst(iso)
        iso.seek(0x420)
        dol_off, fst_off, fst_size = struct.unpack(">III", iso.read(12))
        iso.seek(0x400)
        apl_size = struct.unpack(">I", iso.read(4))[0]

        def copy(off: int, size: int, out: Path) -> None:
            if out.exists() and out.stat().st_size == size:
                return
            out.parent.mkdir(parents=True, exist_ok=True)
            iso.seek(off)
            with open(out, "wb") as f:
                left = size
                while left:
                    chunk = iso.read(min(left, 8 << 20))
                    f.write(chunk)
                    left -= len(chunk)
            log(f"  {out.relative_to(dest)} ({size:,} bytes)")

        if not only or only.startswith("sys") or only.startswith("snd"):  # sys/ is tiny and needed for editing
            copy(0, 0x440, sys_dir / "boot.bin")
            copy(0x440, 0x2000, sys_dir / "bi2.bin")
            copy(fst_off, fst_size, sys_dir / "fst.bin")
            iso.seek(0x2440 + 0x14)
            apl_len = struct.unpack(">I", iso.read(4))[0]
            iso.seek(0x2440 + 0x18)
            apl_trailer = struct.unpack(">I", iso.read(4))[0]
            copy(0x2440, 0x20 + apl_len + apl_trailer, sys_dir / "apploader.img")
            # main.dol: header gives section offsets/sizes -> total length
            iso.seek(dol_off)
            hdr = iso.read(0x100)
            offs = struct.unpack(">18I", hdr[0:0x48])
            sizes = struct.unpack(">18I", hdr[0x90:0xD8])
            dol_size = max((o + s for o, s in zip(offs, sizes) if s), default=0x100)
            copy(dol_off, dol_size, sys_dir / "main.dol")
        for path, (off, size) in sorted(files.items()):
            if only and not path.startswith(only):
                continue
            copy(off, size, files_dir / path)
    return dest


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
