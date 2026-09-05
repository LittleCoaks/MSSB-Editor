"""Where the game is, and how to read ZZZZ.dat and the disc files from it.

The user picks ONE thing, saved as "game" in config.json next to the program:
either a GameCube image (.iso/.gcm) or an extracted game folder. Everything
else is derived from that by `Game.detect`:

    iso        the image (read-only source of every file)
    files_dir  the extracted files/ root (writable; holds snd/, aaaa.dat, ...)
    sys_dir    the folder with main.dol
    layout     "iso", "dolphin" (files/ + sys/), "gcr" (root with &&systemdata)

An ISO can be paired with an extracted folder ("files" in config.json, set by
the dump command) so viewing reads the image while editing writes the folder.

Resolution order for the game: config.json, the MSSB_GAME environment
variable, then the decomp repo's orig/GYQE01 (sibling "MSSB Decomp" folder,
MSSB_DECOMP or decomp_path.txt) for developers.
"""
from __future__ import annotations

import json
import os
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

from .paths import CONFIG_PATH, DATA_DIR, EXE_DIR, PACKAGE_DATA

VIEWER_ROOT = DATA_DIR  # kept for older imports: the per-user data folder
ARCHIVE_NAME = "ZZZZ.dat"
ISO_SUFFIXES = (".iso", ".gcm")


# ------------------------------------------------------------------ config --

def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=1), encoding="utf-8")


def _find_decomp_root() -> Path | None:
    env = os.environ.get("MSSB_DECOMP")
    if env:
        return Path(env)
    cfg = EXE_DIR / "decomp_path.txt"
    if cfg.exists():
        return (EXE_DIR / cfg.read_text(encoding="utf-8").strip()).resolve()
    for parent in [EXE_DIR] + list(EXE_DIR.parents):
        cand = parent / "MSSB Decomp"
        if (cand / "orig").is_dir():
            return cand.resolve()
    return None


REPO_ROOT = _find_decomp_root()  # only used for symbol names when re-indexing


# -------------------------------------------------------------------- game --

@dataclass
class Game:
    setting: Path | None
    layout: str = "none"
    iso: Path | None = None
    files_dir: Path | None = None
    sys_dir: Path | None = None
    problem: str = ""

    @staticmethod
    def detect(path: str | Path | None, files: str | Path | None = None) -> "Game":
        """Work out the layout of what the user pointed at."""
        if not path:
            return Game(None, problem="no game selected")
        p = Path(path).expanduser()
        if not p.exists():
            return Game(p, problem=f"{p} does not exist")
        g = Game(p)
        if p.is_file():
            if p.suffix.lower() not in ISO_SUFFIXES:
                return Game(p, problem="not a .iso/.gcm image or a game folder")
            g.layout, g.iso = "iso", p
            pair = Path(files) if files else None
            for cand in [pair, p.with_suffix(""), p.parent / (p.stem + " (extracted)")]:
                if cand and (cand / "files").is_dir():
                    g.files_dir, g.sys_dir = cand / "files", cand / "sys"
                    break
            return g
        # folders
        if (p / "files").is_dir() or (p / "sys").is_dir():
            g.layout, g.files_dir, g.sys_dir = "dolphin", p / "files", p / "sys"
        elif p.name == "files" and (p.parent / "sys").is_dir():
            g.layout, g.files_dir, g.sys_dir = "dolphin", p, p.parent / "sys"
        elif (p / "&&systemdata").is_dir():
            g.layout, g.files_dir, g.sys_dir = "gcr", p, p / "&&systemdata"
        elif (p / ARCHIVE_NAME).exists() or (p / "snd").is_dir() or (p / "aaaa.dat").exists():
            g.layout, g.files_dir, g.sys_dir = "gcr", p, p
        else:
            return Game(p, problem="folder has neither files/+sys/ nor the game's files")
        isos = sorted(p.glob("*.iso")) + sorted(p.glob("*.gcm"))
        if isos:
            g.iso = isos[0]
        if not g.archive_path():
            g.problem = f"no {ARCHIVE_NAME} in the folder and no ISO beside it"
        return g

    # what is available -------------------------------------------------
    @property
    def ok(self) -> bool:
        return not self.problem and self.archive_path() is not None

    @property
    def writable(self) -> bool:
        return self.files_dir is not None and self.files_dir.is_dir()

    def archive_path(self) -> tuple[Path, str] | None:
        if self.files_dir and (self.files_dir / ARCHIVE_NAME).exists():
            return self.files_dir / ARCHIVE_NAME, "file"
        if self.iso:
            return self.iso, "iso"
        return None

    def dol_path(self) -> Path | None:
        if self.sys_dir:
            for name in ("main.dol", "Start.dol"):
                if (self.sys_dir / name).exists():
                    return self.sys_dir / name
        return None

    def file(self, rel: str) -> tuple[Path, int, int] | None:
        """(path, offset, size) for a disc file, from the folder or the ISO."""
        if self.files_dir and (self.files_dir / rel).exists():
            p = self.files_dir / rel
            return p, 0, p.stat().st_size
        if self.iso:
            with open(self.iso, "rb") as f:
                files = read_fst(f)
            if rel in files:
                off, size = files[rel]
                return self.iso, off, size
        return None

    def read_file(self, rel: str) -> bytes | None:
        loc = self.file(rel)
        if not loc:
            return None
        p, off, size = loc
        with open(p, "rb") as f:
            f.seek(off)
            return f.read(size)

    def list_files(self, prefix: str = "") -> dict[str, int]:
        """{relative path: size} of disc files, preferring the folder."""
        out: dict[str, int] = {}
        if self.iso:
            with open(self.iso, "rb") as f:
                out.update({k: v[1] for k, v in read_fst(f).items() if k.startswith(prefix)})
        if self.files_dir and self.files_dir.is_dir():
            base = self.files_dir / prefix if prefix else self.files_dir
            if base.exists():
                for p in base.rglob("*"):
                    if p.is_file():
                        out[p.relative_to(self.files_dir).as_posix()] = p.stat().st_size
        return out

    def describe(self) -> dict:
        arc = self.archive_path()
        return {"setting": str(self.setting) if self.setting else None, "layout": self.layout,
                "iso": str(self.iso) if self.iso else None,
                "files_dir": str(self.files_dir) if self.files_dir else None,
                "sys_dir": str(self.sys_dir) if self.sys_dir else None,
                "dol": str(self.dol_path()) if self.dol_path() else None,
                "archive": str(arc[0]) if arc else None, "archive_source": arc[1] if arc else None,
                "writable": self.writable, "ok": self.ok, "problem": self.problem}


def current_game() -> Game:
    cfg = load_config()
    if cfg.get("game"):
        return Game.detect(cfg["game"], cfg.get("files"))
    if os.environ.get("MSSB_GAME"):
        return Game.detect(os.environ["MSSB_GAME"])
    if REPO_ROOT and (REPO_ROOT / "orig" / "GYQE01").is_dir():
        return Game.detect(REPO_ROOT / "orig" / "GYQE01")
    return Game(None, problem="no game selected")


def set_game(path: str | Path, files: str | Path | None = None) -> Game:
    g = Game.detect(path, files)
    if g.problem:
        raise FileNotFoundError(g.problem)
    cfg = load_config()
    cfg["game"] = str(Path(path).expanduser().resolve())
    if files:
        cfg["files"] = str(Path(files).expanduser().resolve())
    else:
        cfg.pop("files", None)
    save_config(cfg)
    return g


# --------------------------------------------------------------------- iso --

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
        if offset + length > self.size and self.source == "file":
            self.size = self.path.stat().st_size  # the editor may have appended
        if offset < 0 or offset + length > self.size:
            raise ValueError(f"read outside archive: {offset:#x}+{length:#x}")
        with open(self.path, "rb") as f:
            f.seek(self.base + offset)
            return f.read(length)


def find_archive(game: Game | None = None) -> Archive:
    game = game or current_game()
    loc = game.archive_path()
    if not loc:
        raise FileNotFoundError(game.problem or f"could not find {ARCHIVE_NAME}")
    path, source = loc
    if source == "file":
        return Archive(path, 0, path.stat().st_size, "file")
    with open(path, "rb") as f:
        files = read_fst(f)
    if ARCHIVE_NAME not in files:
        raise FileNotFoundError(f"{path} has no {ARCHIVE_NAME}; is it a Mario Superstar Baseball image?")
    off, size = files[ARCHIVE_NAME]
    return Archive(path, off, size, "iso")


def default_dump_dir(game: Game) -> Path:
    if game.files_dir and game.layout != "iso":
        return game.files_dir.parent if game.layout == "dolphin" else game.files_dir
    assert game.iso
    return game.iso.parent / (game.iso.stem + " (extracted)")


def dump_iso(dest: Path | str | None = None, only: str | None = None, log=lambda *a: None,
             progress=None, game: Game | None = None) -> Path:
    """Extract the game's files out of the ISO into a Dolphin-style dump:
    <dest>/files/... and <dest>/sys/{main.dol,boot.bin,bi2.bin,apploader.img,fst.bin}.
    Existing files of the right size are left alone. `only` is a comma list of
    path prefixes (e.g. "snd/" or "ZZZZ.dat,aaaa.dat"); sys/ is always written. The dump is then
    paired with the ISO in config.json so editing writes there."""
    game = game or current_game()
    if not game.iso:
        raise FileNotFoundError("no ISO to dump from")
    prefixes = [x.strip() for x in only.split(",") if x.strip()] if only else []
    dest = Path(dest) if dest else default_dump_dir(game)
    files_dir = dest / "files"
    sys_dir = dest / "sys"
    with open(game.iso, "rb") as iso:
        files = read_fst(iso)
        todo = [(p, o, s) for p, (o, s) in sorted(files.items()) if not prefixes or any(p.startswith(x) for x in prefixes)]
        total = sum(s for _, _, s in todo)
        done = 0
        iso.seek(0x420)
        dol_off, fst_off, fst_size = struct.unpack(">III", iso.read(12))

        def copy(off: int, size: int, out: Path) -> None:
            nonlocal done
            if out.exists() and out.stat().st_size == size:
                done += size
                return
            out.parent.mkdir(parents=True, exist_ok=True)
            iso.seek(off)
            tmp = out.with_suffix(out.suffix + ".part")
            with open(tmp, "wb") as f:
                left = size
                while left:
                    chunk = iso.read(min(left, 8 << 20))
                    f.write(chunk)
                    left -= len(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
            os.replace(tmp, out)
            log(f"  {out.relative_to(dest)} ({size:,} bytes)")

        copy(0, 0x440, sys_dir / "boot.bin")
        copy(0x440, 0x2000, sys_dir / "bi2.bin")
        copy(fst_off, fst_size, sys_dir / "fst.bin")
        iso.seek(0x2440 + 0x14)
        apl_len = struct.unpack(">I", iso.read(4))[0]
        iso.seek(0x2440 + 0x18)
        apl_trailer = struct.unpack(">I", iso.read(4))[0]
        copy(0x2440, 0x20 + apl_len + apl_trailer, sys_dir / "apploader.img")
        iso.seek(dol_off)
        hdr = iso.read(0x100)
        offs = struct.unpack(">18I", hdr[0:0x48])
        sizes = struct.unpack(">18I", hdr[0x90:0xD8])
        copy(dol_off, max((o + s for o, s in zip(offs, sizes) if s), default=0x100), sys_dir / "main.dol")
        for path, off, size in todo:
            copy(off, size, files_dir / path)
    if game.layout == "iso":
        set_game(game.iso, dest)
    return dest


# ------------------------------------------------------------ file browser --

def list_dir(path: str | None) -> dict:
    """Directory listing for the in-page file browser."""
    if not path:
        if sys.platform == "win32":
            drives = [f"{c}:\\" for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if Path(f"{c}:\\").exists()]
            return {"path": "", "parent": None, "dirs": drives, "files": [], "layout": ""}
        path = "/"
    p = Path(path)
    if not p.is_dir():
        raise FileNotFoundError(f"{p} is not a folder")
    dirs, files = [], []
    try:
        for c in sorted(p.iterdir(), key=lambda c: c.name.lower()):
            try:
                if c.is_dir():
                    dirs.append(c.name)
                elif c.suffix.lower() in ISO_SUFFIXES:
                    files.append({"name": c.name, "size": c.stat().st_size})
            except OSError:
                continue
    except PermissionError:
        pass
    parent = "" if p.parent == p else str(p.parent)
    hint = Game.detect(p).layout if any(n in ("files", "sys", "&&systemdata", "snd") for n in dirs) else ""
    return {"path": str(p), "parent": parent, "dirs": dirs, "files": files, "layout": hint}
