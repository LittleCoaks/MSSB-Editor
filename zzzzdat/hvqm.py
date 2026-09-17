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

`Movie.make_mp4` turns a decoded movie into one file. With ffmpeg on PATH that
is H.264 and AAC, which plays anywhere; without it the frames are muxed as they
are by mp4.py - lossless and quick, but Motion JPEG, so it is as large as the
frames and a browser will not play it.
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
FFMPEG = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"


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


def ffmpeg_path() -> Path | None:
    """ffmpeg, if it is bundled beside the helper or anywhere on PATH."""
    for c in (PACKAGE_DATA / "native" / "bin" / FFMPEG,
              Path(__file__).resolve().parents[1] / "native" / "bin" / FFMPEG):
        if c.is_file():
            return c
    if FROZEN:
        beside = Path(sys.executable).resolve().parent / FFMPEG
        if beside.is_file():
            return beside
    found = shutil.which(FFMPEG)
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

    def mp4_path(self) -> Path:
        return self.folder / "movie.mp4"

    def has_mp4(self) -> bool:
        p = self.mp4_path()
        return p.exists() and p.stat().st_size > 0

    def make_mp4(self, progress=None) -> Path:
        """The movie as one file, cached beside the frames. H.264/AAC when
        ffmpeg is available, otherwise the frames muxed as Motion JPEG."""
        dest = self.mp4_path()
        if self.has_mp4():
            return dest
        tmp = dest.with_suffix(".part")
        tmp.unlink(missing_ok=True)
        exe = ffmpeg_path()
        if exe is not None:
            self._ffmpeg(exe, tmp, progress)
        else:
            from . import mp4
            mp4.write(tmp, self.folder / "frames.mjpg", self.index,
                      int(self.info["usec_per_frame"]), int(self.info["width"]),
                      int(self.info["height"]), self.audio(), progress=progress)
        tmp.replace(dest)
        return dest

    def ffmpeg_cmd(self, exe: Path, dest: Path) -> list[str]:
        """Re-encode to H.264/AAC. The frame rate goes in as the exact ratio the
        movie was decoded at - 1000000/33333, not a rounded 30.0 - so the video
        does not drift away from the audio over a five-minute intro."""
        usec = int(self.info["usec_per_frame"])
        return [str(exe), "-y", "-nostdin",
               "-f", "mjpeg", "-framerate", f"1000000/{usec}", "-i", str(self.folder / "frames.mjpg"),
               "-i", str(self.audio()),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
               # AAC has a fixed list of rates and the game's 32028 Hz is not on
               # it, so say what to resample to rather than letting it guess
               "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
               "-shortest", "-movflags", "+faststart",
               "-progress", "pipe:1", "-nostats", "-loglevel", "error", str(dest)]

    def _ffmpeg(self, exe: Path, dest: Path, progress=None) -> None:
        total = len(self.index)
        proc = subprocess.Popen(self.ffmpeg_cmd(exe, dest), stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        tail = []
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("frame=") and progress and total:
                try:
                    progress(min(int(line[6:]), total), total)
                except ValueError:
                    pass
            elif line and not line.startswith(("out_time", "total_size", "bitrate", "speed",
                                               "fps=", "stream_", "dup_frames", "drop_frames",
                                               "progress=")):
                tail.append(line)
        if proc.wait() != 0:
            dest.unlink(missing_ok=True)
            raise RuntimeError("ffmpeg failed: " + (" / ".join(tail[-3:]) or "no output"))

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
    return CACHE_DIR / game_key / "v3" / "movies" / str(entry_id)   # v3: video-range colours, spec-correct JPEG padding


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
