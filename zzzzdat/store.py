"""High-level access: index + archive + decompression + extraction."""
from __future__ import annotations

import re
import time
from collections import OrderedDict
from pathlib import Path

from . import c3, dsp, formats
from .descriptors import (INDEX_PATH, Entry, build_index, coverage, load_index, load_known_names, save_index,
                          scan_adgc, scan_unreferenced, verify_entries)
from .disc import VIEWER_ROOT, Archive, Game, current_game, find_archive
from .lzss import decompress

EXTRACT_DIR = VIEWER_ROOT / "extracted"
KNOWN_NAMES_PATH = VIEWER_ROOT / "index" / "known_names.json"
if not KNOWN_NAMES_PATH.exists():
    from .disc import PACKAGE_DATA
    KNOWN_NAMES_PATH = PACKAGE_DATA / "index" / "known_names.json"

EXT_BY_KIND = {"hvqm4": "h4m", "dsp-adpcm": "adpcm", "textures": "tex", "container": "bin",
               "anim": "anm", "adgc": "adgc", "geopalette": "geo", "dtk-adpcm": "adp", "unknown": "bin", "": "bin"}
DISC_ID_BASE = 10000


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]+", "_", s).strip("_")[:60]


class Store:
    def __init__(self, index_path: Path = INDEX_PATH, archive: Archive | None = None, game: Game | None = None):
        self.index_path = index_path
        self.game = game or current_game()
        self.archive = archive or find_archive(self.game)
        self.entries: list[Entry] = load_index(index_path) if index_path.exists() else []
        self.entries += self.disc_entries()
        self.by_id = {e.id: e for e in self.entries}
        self._data: OrderedDict[int, bytes] = OrderedDict()
        self._info: dict[int, formats.FileInfo] = {}
        self._wav: OrderedDict[tuple, bytes] = OrderedDict()
        self._glb: OrderedDict[tuple, bytes] = OrderedDict()

    def refresh_disc_entries(self) -> None:
        """Re-read the dump's .adp files (after a music install/restore)."""
        self.entries = [e for e in self.entries if e.archive != "disc"] + self.disc_entries()
        self.by_id = {e.id: e for e in self.entries}
        for k in [k for k in self._data if k >= DISC_ID_BASE]:
            del self._data[k]
        for k in [k for k in self._info if k >= DISC_ID_BASE]:
            del self._info[k]
        for k in [k for k in self._wav if k[0] >= DISC_ID_BASE]:
            del self._wav[k]

    def disc_entries(self) -> list[Entry]:
        """The streamed .adp music files on the disc, as synthetic entries
        (archive 'disc'). Read from the ISO or from orig/GYQE01/files/."""
        out = []
        # Extracted folder first (it holds installed custom music), else the ISO.
        files = self.game.list_files("snd/")
        for i, (path, size) in enumerate(sorted(files.items())):
            if not path.endswith(".adp"):
                continue
            e = Entry(DISC_ID_BASE + i, 0, size, size, 0, 0, 0, name=path, refs=[f"disc:{path}"],
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
            data = self.game.read_file(e.name)
            if data is None:
                raise KeyError(f"{e.name} is not in the game")
            return data
        if e.archive != "ZZZZ.dat":
            loc = self.game.file(e.archive)
            if not loc:
                raise KeyError(f"{e.archive} is not in the game")
            p, off, _ = loc
            with open(p, "rb") as f:
                f.seek(off + e.offset)
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

    # -------------------------------------------------------------- models --
    def models(self, e: Entry) -> list[dict]:
        """Summaries of every parseable GeoPalette section in an entry."""
        out = []
        fi = self.info(e)
        data = self.data(e)
        for s in fi.sections:
            if s.kind != "geopalette":
                continue
            m = c3.parse_geopalette(data, s.offset)
            if not m or not m.triangle_count:
                continue
            out.append({"section": s.index, "offset": s.offset, "meshes": [mm.name for mm in m.meshes],
                        "triangles": m.triangle_count,
                        "textures": sorted({d.texture for mm in m.meshes for d in mm.draws if d.texture is not None})})
        return out

    def model(self, e: Entry, section: int) -> c3.Model:
        data = self.data(e)
        s = self.info(e).sections[section]
        m = c3.parse_geopalette(data, s.offset)
        if not m:
            raise KeyError(f"section {section} of entry {e.id} is not a GeoPalette")
        return m

    def glb(self, e: Entry, section: int) -> bytes:
        key = (e.id, section)
        if key in self._glb:
            return self._glb[key]
        m = self.model(e, section)
        data = self.data(e)
        texs = self.info(e).all_textures()
        used = {d.texture for mm in m.meshes for d in mm.draws if d.texture is not None}
        pngs = {i: t.decode_png(data) for i, (_sec, t) in enumerate(texs) if i in used}
        g = c3.to_glb(m, pngs)
        self._glb[key] = g
        while len(self._glb) > 8:
            self._glb.popitem(last=False)
        return g

    def extract_models(self, e: Entry, dest: Path, fmt: str = "glb") -> list[Path]:
        out = []
        for md in self.models(e):
            dest.mkdir(parents=True, exist_ok=True)
            stem = f"s{md['section']}_{safe_name(md['meshes'][0])}"
            if fmt in ("glb", "both"):
                p = dest / f"{stem}.glb"
                p.write_bytes(self.glb(e, md["section"]))
                out.append(p)
            if fmt in ("obj", "both"):
                m = self.model(e, md["section"])
                p = dest / f"{stem}.obj"
                p.write_text(c3.to_obj(m, f"{stem}.mtl"), encoding="utf-8")
                out.append(p)
                data = self.data(e)
                texs = self.info(e).all_textures()
                mtl = []
                for i in md["textures"]:
                    if i < len(texs):
                        png = dest / f"{stem}_tex{i}.png"
                        png.write_bytes(texs[i][1].decode_png(data))
                        mtl.append(f"newmtl tex{i}\nKd 1 1 1\nmap_Kd {png.name}\n")
                (dest / f"{stem}.mtl").write_text("".join(mtl), encoding="utf-8")
        return out

    def wav_size(self, e: Entry, n: int = 0, max_seconds: float | None = None) -> int:
        st = self.info(e).audio[n]
        if st["kind"] == "dtk-adpcm":
            return dsp.dtk_wav_size(e.size, max_seconds)
        return dsp.dsp_wav_size(self.data(e), st["pos"], max_seconds)

    def wav_stream(self, e: Entry, n: int = 0, max_seconds: float | None = None):
        """Generator of WAV bytes; the complete file is cached when it finishes."""
        key = (e.id, n, max_seconds)
        if key in self._wav:
            yield self._wav[key]
            return
        st = self.info(e).audio[n]
        data = self.data(e)
        gen = dsp.dtk_wav_stream(data, max_seconds) if st["kind"] == "dtk-adpcm" else dsp.dsp_wav_stream(data, st["pos"], max_seconds)
        parts = []
        for chunk in gen:
            parts.append(chunk)
            yield chunk
        self._wav[key] = b"".join(parts)
        while len(self._wav) > 8:
            self._wav.popitem(last=False)

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
                wav: bool = False, model: str | None = None) -> list[Path]:
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
        if model:
            written += self.extract_models(e, dest / (self.file_name(e).rsplit(".", 1)[0] + "_model"), model)
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
        ents = build_index(self.archive.size, self.game)
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
                texs = fi.all_textures()
                e.thumb = max(range(len(texs)), key=lambda i: texs[i][1].width * texs[i][1].height) if texs else 0
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
