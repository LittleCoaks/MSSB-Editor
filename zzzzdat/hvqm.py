"""HVQM4 movies: decoding through the native helper and the per-movie cache.

HVQM4 is Hudson's proprietary codec; the decoder is Tilka's bit-accurate
reverse engineering (LGPL, vendored under native/hvqm4/ with the changes
listed in its header). It is built into a small command-line helper,
`hvqm4dec`, that writes a movie into a folder:

    frames.mjpg   every frame as a baseline JPEG, back to back
    frames.idx    u32 little-endian (offset, size) per frame in display order
    audio.wav     the decoded audio (IMA-style ADPCM -> PCM16)
    info.json     width, height, frames, fps, sample rate

The helper is looked for next to the package (native/bin/), in the frozen
bundle, or on PATH. Without it movies can still be identified and their raw
.h4m exported, just not played.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

from .paths import CACHE_DIR, FROZEN, PACKAGE_DATA

HELPER = "hvqm4dec.exe" if sys.platform == "win32" else "hvqm4dec"


def helper_path() -> Path | None:
    candidates = [PACKAGE_DATA / "native" / "bin" / HELPER, Path(__file__).resolve().parents[1] / "native" / "bin" / HELPER]
    if FROZEN:
        exe_dir = Path(sys.executable).resolve().parent
        # Windows one-folder build: next to the exe. macOS .app (PyInstaller 6): the
        # executable is in Contents/MacOS and added binaries in Contents/Frameworks
        # (sys._MEIPASS), older layouts in Contents/Resources.
        candidates = [exe_dir / HELPER, PACKAGE_DATA / HELPER, exe_dir.parent / "Frameworks" / HELPER,
                      exe_dir.parent / "Resources" / HELPER] + candidates
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which(HELPER)
    return Path(found) if found else None


class Movie:
    """A decoded movie in the cache."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.info = json.loads((folder / "info.json").read_text(encoding="utf-8"))
        raw = (folder / "frames.idx").read_bytes()
        self.index = [struct.unpack_from("<II", raw, i * 8) for i in range(len(raw) // 8)]

    @property
    def ready(self) -> bool:
        return bool(self.index) and (self.folder / "audio.wav").exists()

    def frame(self, n: int) -> bytes:
        off, size = self.index[n]
        with open(self.folder / "frames.mjpg", "rb") as f:
            f.seek(off)
            return f.read(size)

    def audio(self) -> Path:
        return self.folder / "audio.wav"

    def export(self, dest: Path) -> list[Path]:
        """Numbered JPEGs and the WAV, for ffmpeg or an editor."""
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        with open(self.folder / "frames.mjpg", "rb") as f:
            for n, (off, size) in enumerate(self.index):
                f.seek(off)
                p = dest / f"frame_{n:05d}.jpg"
                p.write_bytes(f.read(size))
                out.append(p)
        wav = dest / "audio.wav"
        shutil.copyfile(self.folder / "audio.wav", wav)
        out.append(wav)
        return out


def movie_dir(game_key: str, entry_id: int) -> Path:
    return CACHE_DIR / game_key / "v2" / "movies" / str(entry_id)


def load(game_key: str, entry_id: int) -> Movie | None:
    d = movie_dir(game_key, entry_id)
    if (d / "info.json").exists() and (d / "frames.idx").exists():
        try:
            m = Movie(d)
            return m if m.ready else None
        except (OSError, ValueError):
            return None
    return None


def decode(game_key: str, entry_id: int, h4m: bytes, progress=None) -> Movie:
    """Run the helper on the movie bytes; returns the cached Movie."""
    exe = helper_path()
    if exe is None:
        raise RuntimeError("the HVQM4 helper (native/bin/hvqm4dec) is not built; see README 'Movies'")
    d = movie_dir(game_key, entry_id)
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    src = d / "movie.h4m"
    src.write_bytes(h4m)
    try:
        proc = subprocess.Popen([str(exe), str(src), str(d)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        total = None
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("frames "):
                total = int(line.split()[1])
            elif line.startswith("frame ") and progress and total:
                progress(int(line.split()[1]), total)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"hvqm4dec failed (exit {rc})")
    finally:
        src.unlink(missing_ok=True)
    return Movie(d)
