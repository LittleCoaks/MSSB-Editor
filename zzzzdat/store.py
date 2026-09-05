"""High-level access: index + archive + decompression + extraction."""
from __future__ import annotations

import re
import time
from collections import OrderedDict
from pathlib import Path

from . import dsp, formats
from .descriptors import (INDEX_PATH, Entry, build_index, coverage, load_index, load_known_names, save_index,
                          scan_adgc, scan_unreferenced, verify_entries)
from .disc import ORIG_DIR, VIEWER_ROOT, Archive, find_archive, read_fst
from .lzss import decompress

EXTRACT_DIR = VIEWER_ROOT / "extracted"
KNOWN_NAMES_PATH = VIEWER_ROOT / "index" / "known_names.json"

EXT_BY_KIND = {"hvqm4": "h4m", "dsp-adpcm": "adpcm", "textures": "tex", "container": "bin",
               "anim": "anm", "adgc": "adgc", "geopalette": "geo", "dtk-adpcm": "adp", "unknown": "bin", "": "bin"}
DISC_ID_BASE = 10000


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]+", "_", s).strip("_")[:60]


class Store:
    def __init__(self, index_path: Path = INDEX_PATH, archive: Archive | None = None):
        self.index_path = index_path
        self.archive = archive or find_archive()
        self.entries: list[Entry] = load_index(index_path) if index_path.exists() else []
        self.entries += self.disc_entries()
        self.by_id = {e.id: e for e in self.entries}
        self._data: OrderedDict[int, bytes] = OrderedDict()
        self._info: dict[int, formats.FileInfo] = {}
        self._wav: OrderedDict[tuple, bytes] = OrderedDict()

    def disc_entries(self) -> list[Entry]:
        """The streamed .adp music files on the disc, as synthetic entries
        (archive 'disc'). Read from the ISO or from orig/GYQE01/files/."""
        out = []
        files: dict[str, tuple[int, int]] = {}
        if self.archive.source == "iso":
            with open(self.archive.path, "rb") as f:
                files = read_fst(f)
        else:
            root = ORIG_DIR / "files"
            for p in sorted(root.rglob("*.adp")):
                files[p.relative_to(root).as_posix()] = (0, p.stat().st_size)
        for i, (path, (off, size)) in enumerate(sorted(files.items())):
            if not path.endswith(".adp"):
                continue
            e = Entry(DISC_ID_BASE + i, off, size, size, 0, 0, 0, name=path, refs=[f"disc:{path}"],
                      archive="disc", kind="dtk-adpcm", label=path.rsplit("/", 1)[-1], naud=1)
            out.append(e)
        return out

    # ------------------------------------------------------------ lookup --
    def get(self, id_or_name) -> Entry:
        if isinstance(id_or_name, int) or str(id_or_name).isdigit():
            e = self.by_id.get(int(id_or_name))
            if e:
                return e
        for e in self.entries:
            if e.name == id_or_name or e.name == str(id_or_name).lower().lstrip("0x").zfill(8):
                return e
        raise KeyError(f"no entry {id_or_name!r}")

    def zzzz_entries(self) -> list[Entry]:
        return [e for e in self.entries if e.archive == "ZZZZ.dat"]

    # -------------------------------------------------------------- bytes --
    def raw(self, e: Entry) -> bytes:
        if e.archive == "disc":
            if self.archive.source == "iso":
                with open(self.archive.path, "rb") as f:
                    f.seek(e.offset)
                    return f.read(e.disc_size)
            return (ORIG_DIR / "files" / e.name).read_bytes()
        if e.archive != "ZZZZ.dat":
            from .disc import ORIG_DIR
            with open(ORIG_DIR / "files" / e.archive, "rb") as f:
                f.seek(e.offset)
                return f.read(e.disc_size)
        return self.archive.read(e.offset, e.disc_size)

    def data(self, e: Entry) -> bytes:
        """Decompressed contents (cached for the last few files)."""
        if e.id in self._data:
            self._data.move_to_end(e.id)
            return self._data[e.id]
        raw = self.raw(e)
        out = bytes(decompress(raw, e.lookback_bits, e.repeat_bits, e.size)) if e.compressed else raw[:e.size]
        if len(out) <= 32 << 20:
            self._data[e.id] = out
            while len(self._data) > 24:
                self._data.popitem(last=False)
        return out

    def info(self, e: Entry) -> formats.FileInfo:
        fi = self._info.get(e.id)
        if fi is None:
            fi = formats.dtk_info(e.size) if e.archive == "disc" else formats.identify(self.data(e))
            self._info[e.id] = fi
        return fi

    # -------------------------------------------------------------- audio --
    def wav(self, e: Entry, n: int = 0, max_seconds: float | None = None) -> bytes:
        """Decode audio stream `n` of an entry to a WAV file (cached)."""
        key = (e.id, n, max_seconds)
        if key in self._wav:
            self._wav.move_to_end(key)
            return self._wav[key]
        streams = self.info(e).audio
        if n >= len(streams):
            raise KeyError(f"entry {e.id} has no audio stream {n}")
        st = streams[n]
        data = self.data(e)
        if st["kind"] == "dtk-adpcm":
            w = dsp.dtk_wav(data, max_seconds)
        else:
            _, w = dsp.decode_stream(data, st["pos"], max_seconds)
        self._wav[key] = w
        while len(self._wav) > 8:
            self._wav.popitem(last=False)
        return w

    def extract_audio(self, e: Entry, dest: Path, max_seconds: float | None = None) -> list[Path]:
        streams = self.info(e).audio
        if not streams:
            return []
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for n, st in enumerate(streams):
            p = dest / f"{n:02d}_{st['kind']}_{st['rate']}Hz_{st['seconds']}s.wav"
            p.write_bytes(self.wav(e, n, max_seconds))
            out.append(p)
        return out

    # ------------------------------------------------------------- naming --
    def file_name(self, e: Entry, ext: str | None = None) -> str:
        ext = ext or EXT_BY_KIND.get(e.kind, "bin")
        sym = safe_name(e.symbol.replace(" ", "_"))
        lab = safe_name((e.known or e.label).rsplit(".", 1)[0]) if (e.known or e.label) else ""
        return f"{e.id:04d}_{e.offset:08x}" + (f"_{lab}" if lab else "") + (f"_{sym}" if sym else "") + f".{ext}"

    # ---------------------------------------------------------- extraction --
    def extract(self, e: Entry, dest: Path = EXTRACT_DIR, raw: bool = False, png: bool = False,
                wav: bool = False) -> list[Path]:
        dest.mkdir(parents=True, exist_ok=True)
        written = []
        if raw:
            p = dest / self.file_name(e, "lz" if e.compressed else EXT_BY_KIND.get(e.kind, "bin"))
            p.write_bytes(self.raw(e))
            written.append(p)
        else:
            p = dest / self.file_name(e)
            p.write_bytes(self.data(e))
            written.append(p)
        if png:
            written += self.extract_textures(e, dest / (self.file_name(e).rsplit(".", 1)[0] + "_tex"))
        if wav:
            written += self.extract_audio(e, dest / (self.file_name(e).rsplit(".", 1)[0] + "_wav"))
        return written

    def extract_textures(self, e: Entry, dest: Path) -> list[Path]:
        data = self.data(e)
        texs = self.info(e).all_textures()
        if not texs:
            return []
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for n, (sec, t) in enumerate(texs):
            tag = f"s{sec.index}_" if sec else ""
            p = dest / f"{n:03d}_{tag}t{t.index}_{t.width}x{t.height}_{t.fmt_name}.png"
            p.write_bytes(t.decode_png(data))
            out.append(p)
        return out

    # ---------------------------------------------------------- indexing --
    def rebuild_index(self, verify: bool = True, classify: bool = True, scan: bool = True, log=print) -> None:
        t0 = time.time()
        ents = build_index(self.archive.size)
        log(f"scanned executables: {len(ents)} candidate descriptors")
        if verify:
            ents = verify_entries(ents, self.archive)
            log(f"verified: {len(ents)} entries ({time.time() - t0:.0f}s)")
        if scan:
            adgc = scan_adgc(self.archive, log)
            log(f"AdGCForm scan: {len(adgc)} sound files ({time.time() - t0:.0f}s)")
            ents += adgc
            extra = scan_unreferenced(self.archive, ents, log)
            log(f"unreferenced scan: {len(extra)} streams ({time.time() - t0:.0f}s)")
            ents += extra
            ents.sort(key=lambda e: (e.archive != "ZZZZ.dat", e.offset, e.disc_size))
            for i, e in enumerate(ents):
                e.id = i
        known = load_known_names(KNOWN_NAMES_PATH)
        for e in ents:
            e.known = known.get(e.offset, "") if e.archive == "ZZZZ.dat" else ""
        if classify:
            for i, e in enumerate(ents):
                if e.archive != "ZZZZ.dat":
                    e.kind = "rel"
                    continue
                try:
                    data = self.archive.read(e.offset, e.disc_size)
                    data = bytes(decompress(data, e.lookback_bits, e.repeat_bits, e.size)) if e.compressed else data
                    fi = formats.identify(data)
                except Exception as ex:  # keep going; the entry is still listed
                    log(f"  entry {e.id}: {ex}")
                    e.kind = "error"
                    continue
                e.kind = fi.kind
                e.ntex = len(fi.all_textures())
                e.naud = len(fi.audio)
                e.nsec = len(fi.sections)
                e.label = fi.label
                e.names = fi.names[:16]
                if i % 100 == 0:
                    log(f"  classified {i}/{len(ents)} ({time.time() - t0:.0f}s)")
        cov = coverage(ents, self.archive.size)
        meta = {"archive": self.archive.path.name, "archive_size": self.archive.size,
                "source": self.archive.source, "covered_bytes": cov["covered"],
                "built": time.strftime("%Y-%m-%d %H:%M:%S")}
        save_index(ents, self.index_path, meta)
        self.entries = ents + self.disc_entries()
        self.by_id = {e.id: e for e in self.entries}
        self._data.clear()
        self._info.clear()
        log(f"wrote {self.index_path} ({len(ents)} entries, {cov['covered'] / 1e6:.1f} of "
            f"{self.archive.size / 1e6:.1f} MB accounted for)")
