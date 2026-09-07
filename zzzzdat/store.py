"""High-level access: index + archive + decompression + extraction."""
from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from pathlib import Path

from . import anim, c3, chars, collision, dolphin, dsp, formats, handpose, musyx, song
from .paths import EXTRACT_DIR as _EXTRACT_DIR  # noqa: F401
from .descriptors import (INDEX_PATH, Entry, build_index, coverage, load_index, load_known_names, save_index,
                          scan_adgc, scan_unreferenced, verify_entries)
from .disc import Archive, Game, current_game, find_archive
from .paths import EXTRACT_DIR, INDEX_DIR
from .lzss import decompress

KNOWN_NAMES_PATH = INDEX_DIR / "known_names.json"

EXT_BY_KIND = {"hvqm4": "h4m", "dsp-adpcm": "adpcm", "textures": "tex", "container": "bin", "musyx": "grp", "songs": "arr", "text": "txt",
               "anim": "anm", "adgc": "adgc", "geopalette": "geo", "dtk-adpcm": "adp", "unknown": "bin", "": "bin"}
DISC_ID_BASE = 10000
CLONE_ID_BASE = 20000


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]+", "_", s).strip("_")[:60]


class Store:
    def __init__(self, index_path: Path = INDEX_PATH, archive: Archive | None = None, game: Game | None = None):
        self.index_path = index_path
        self.game = game or current_game()
        self.archive = archive or find_archive(self.game)
        self.entries: list[Entry] = load_index(index_path) if index_path.exists() else []
        self.apply_overrides()
        self.entries += self.disc_entries()
        self.by_id = {e.id: e for e in self.entries}
        self._data: OrderedDict[int, bytes] = OrderedDict()
        self._info: dict[int, formats.FileInfo] = {}
        self._wav: OrderedDict[tuple, bytes] = OrderedDict()
        self._glb: OrderedDict[tuple, bytes] = OrderedDict()
        # one lock per entry so concurrent requests never decode the same
        # entry twice, without serialising unrelated work behind one lock
        self._locks: dict[int, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._cache_lock = threading.Lock()

    def lock_for(self, e: Entry) -> threading.Lock:
        with self._locks_guard:
            lk = self._locks.get(e.id)
            if lk is None:
                lk = self._locks[e.id] = threading.Lock()
            return lk

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

    def apply_overrides(self) -> None:
        """Entries replaced by the editor live somewhere else in this game's
        ZZZZ.dat than the shipped index says; cloned character slots have
        descriptors pointing at other characters' files (see clone.py)."""
        from .edit import load_overrides
        ov = load_overrides(self.game)
        for e in self.entries:
            cur = ov.get(str(e.id))
            if cur:
                e.offset, e.disc_size, e.size = cur["offset"], cur["disc_size"], cur["size"]
        self._clone_ids: set[int] = set()
        self.apply_clones()

    def apply_clones(self) -> None:
        """Reflect cloned slots in the index: the slot's own files lose their
        references, shared files gain the slot's references, copied files
        become new entries (ids from CLONE_ID_BASE) and in-place copies take
        the source's description."""
        import copy as _copy
        from .clone import _ref
        from .edit import load_journal
        clones = load_journal(self.game).get("_clones", {})
        if not clones:
            return
        by_off = {e.offset: e for e in self.entries if e.archive == "ZZZZ.dat"}
        by_ref = {}
        for e in self.entries:
            for r in e.refs:
                by_ref[r.split(" ")[0]] = e
        new_entries = []
        for tgt, rec in clones.items():
            tgt = int(tgt)
            def ref_of(x):
                return x["ref"] if "ref" in x else _ref(int(x["va"], 16))
            for x in rec["copied"] + rec["shared"]:
                key = ref_of(x).split(" ")[0]
                e = by_ref.get(key)
                if e:
                    e.refs = [r for r in e.refs if not r.startswith(key)]
            for x in rec["shared"]:
                src = by_off.get(x["src"])
                if src:
                    src.refs.append(ref_of(x))
            for n, x in enumerate(rec["copied"]):
                src = by_off.get(x["src"])
                e = _copy.copy(src) if src else Entry(0, x["offset"], x["disc_size"], x["size"], 4, 11, 4)
                e.id = CLONE_ID_BASE + tgt * 64 + n
                e.offset, e.disc_size, e.size = x["offset"], x["disc_size"], x["size"]
                e.refs = [ref_of(x)]
                e.name = f"{e.offset:08x}"
                new_entries.append(e)
                self._clone_ids.add(e.id)
            for x in rec["inplace"]:
                e = by_ref.get(f"dol:.data:{int(x['va'], 16):#x}")
                src = by_off.get(x["src"])
                if e:
                    if src:
                        e.kind, e.ntex, e.nsec, e.naud, e.label, e.names, e.thumb = src.kind, src.ntex, src.nsec, src.naud, src.label, src.names, src.thumb
                    e.disc_size, e.size = x["disc_size"], x["size"]
                    self._clone_ids.add(e.id)
        self.entries += new_entries

    def modified_ids(self) -> list[int]:
        from .edit import load_overrides
        return [int(k) for k in load_overrides(self.game)] + sorted(getattr(self, "_clone_ids", ()))

    def forget(self, e: Entry) -> None:
        """Drop cached data/info for an entry after it changed on disk."""
        self._data.pop(e.id, None)
        self._info.pop(e.id, None)
        from .thumbs import cache_dir, thumb_dir
        for p in cache_dir(self.game).glob(f"{e.id}_*.png"):
            p.unlink(missing_ok=True)
        (thumb_dir(self.game) / f"{e.id}.png").unlink(missing_ok=True)
        for k in [k for k in self._wav if k[0] == e.id]:
            del self._wav[k]
        for k in [k for k in self._glb if k[0] == e.id]:
            del self._glb[k]

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
        with self._cache_lock:
            if e.id in self._data:
                self._data.move_to_end(e.id)
                return self._data[e.id]
        with self.lock_for(e):
            with self._cache_lock:
                if e.id in self._data:
                    return self._data[e.id]
            raw = self.raw(e)
            out = bytes(decompress(raw, e.lookback_bits, e.repeat_bits, e.size)) if e.compressed else raw[:e.size]
            if len(out) <= 32 << 20:
                with self._cache_lock:
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

    # ------------------------------------------------------------ images --
    def texture_png(self, e: Entry, n: int) -> bytes:
        """A texture as PNG, cached on disk per game."""
        from .thumbs import cache_dir
        p = cache_dir(self.game) / f"{e.id}_{n}.png"
        if p.exists() and e.id not in self.modified_ids():
            return p.read_bytes()
        sec, t = self.info(e).all_textures()[n]
        png = t.decode_png(self.data(e))
        try:
            p.write_bytes(png)
        except OSError:
            pass
        return png

    def thumb_png(self, e: Entry, build: bool = False) -> bytes | None:
        """Thumbnail from this game's cache; None until the background build
        has produced it (unless `build`, used when a single card is opened)."""
        from .thumbs import make_thumb_png, thumb_dir
        if not e.ntex:
            return None
        p = thumb_dir(self.game) / f"{e.id}.png"
        if p.exists():
            return p.read_bytes()
        if not build:
            return None
        texs = self.info(e).all_textures()
        png = make_thumb_png(self.data(e), texs[min(e.thumb, len(texs) - 1)][1])
        try:
            p.write_bytes(png)
        except OSError:
            pass
        return png

    def forget_memory(self, e: Entry) -> None:
        self._data.pop(e.id, None)
        self._info.pop(e.id, None)

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
        elif st["kind"] == "musyx":
            g = self.info(e).musyx
            w = musyx.wav(data, g, g.samples[st["pos"]], max_seconds)
        else:
            _, w = dsp.decode_stream(data, st["pos"], max_seconds)
        self._wav[key] = w
        while len(self._wav) > 8:
            self._wav.popitem(last=False)
        return w

    def stereo_wav(self, e: Entry, n: int) -> bytes:
        """Samples `n` and `n + 1` interleaved as one stereo WAV: the music the
        MusyX groups carry is stored as separate left and right samples."""
        streams = self.info(e).audio
        if n + 1 >= len(streams):
            raise KeyError(f"entry {e.id} has no sample {n + 2} to pair with {n + 1}")
        import struct as _struct
        left, right = self.wav(e, n), self.wav(e, n + 1)
        rate = streams[n]["rate"]
        lp, rp = left[44:], right[44:]
        m = min(len(lp), len(rp)) // 2
        out = bytearray(m * 4)
        out[0::4] = lp[0:m * 2:2]
        out[1::4] = lp[1:m * 2:2]
        out[2::4] = rp[0:m * 2:2]
        out[3::4] = rp[1:m * 2:2]
        return dsp.wav(bytes(out), rate, 2)

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

    def poses(self, e: Entry, section: int | None = None) -> handpose.Poses | None:
        """The hand-pose vertex sets of a hand container (its 0x40001 section)."""
        data = self.data(e)
        secs = self.info(e).sections
        geo = next((s for s in secs if s.kind == "geopalette" and (section is None or s.index == section)), None)
        ps = next((s for s in secs if s.magic == handpose.POSE_VERSION), None)
        if geo is None or ps is None:
            return None
        m = c3.parse_geopalette(data, geo.offset)
        rest = m.meshes[0].positions if m and m.meshes else None
        return handpose.parse_poses(data, ps.offset, rest)

    def model(self, e: Entry, section: int, posed: bool = True, pose: int | None = None) -> c3.Model:
        data = self.data(e)
        secs = self.info(e).sections
        s = secs[section]
        m = c3.parse_geopalette(data, s.offset)
        if not m:
            raise KeyError(f"section {section} of entry {e.id} is not a GeoPalette")
        if pose is not None and m.meshes:
            hp = self.poses(e, section)
            if hp and 0 <= pose < hp.count and hp.vertices == len(m.meshes[0].positions):
                m.meshes[0].positions = list(hp.blocks[pose])
        if posed:
            bones = self.actor_for(e, section)
            if bones:
                c3.apply_actor(m, bones)
        return m

    def actor_for(self, e: Entry, section: int) -> list[c3.Bone] | None:
        """The skeleton that poses GeoPalette `section`. A pack lists its actors
        in the same order as its GeoPalettes (a stadium: the park's, then the
        sky's), so the n-th actor goes with the n-th GeoPalette when the counts
        match; otherwise the nearest preceding actor, or any actor in the file
        (the prototype packs put it after the geometry)."""
        data = self.data(e)
        secs = self.info(e).sections
        acts = [s for s in secs if s.magic == c3.ACT_VERSION and c3.is_actor(data, s.offset)]
        geos = [s for s in secs if s.kind == "geopalette"]
        pick = None
        if acts and len(acts) == len(geos) and any(g.index == section for g in geos):
            pick = acts[[g.index for g in geos].index(section)]
        else:
            order = list(reversed(secs[:section])) + secs[section + 1:]
            pick = next((s for s in order if s.magic == c3.ACT_VERSION and c3.is_actor(data, s.offset)), None)
        return c3.parse_actor(data, pick.offset) if pick else None

    # -------------------------------------------------------------- songs --
    def midi(self, e: Entry, n: int) -> bytes:
        songs = song.parse_songs(self.data(e))
        if n >= len(songs):
            raise KeyError(f"entry {e.id} has no song {n}")
        return song.to_midi(songs[n], f"{self.file_name(e).rsplit('.', 1)[0]} song {n + 1}")

    def instrument_bank(self):
        """The MusyX song group (type 0) that sequenced songs play on, parsed once."""
        if getattr(self, "_bank", None) is None:
            from .render import Bank
            self._bank = False
            for x in self.zzzz_entries():
                if x.kind == "musyx" and x.label.startswith("Instrument bank"):
                    self._bank = Bank(self.data(x))
                    break
        return self._bank or None

    def song_wav(self, e: Entry, n: int) -> bytes:
        """A song rendered with the instrument bank's samples (cached)."""
        key = (e.id, "song", n)
        if key in self._wav:
            return self._wav[key]
        try:
            import numpy  # noqa: F401
        except ImportError:
            raise RuntimeError("rendering songs needs numpy (pip install numpy)")
        bank = self.instrument_bank()
        if bank is None:
            raise RuntimeError("the instrument bank (MusyX song group) was not found in this game")
        from .render import render
        songs = song.parse_songs(self.data(e))
        # the menus start the first two songs of the 19-song file as MusyX song
        # ids 19 and 20 (menus.rel lbl_2_data_128), which select their channel setup
        setup = {0: 19, 1: 20}.get(n) if len(songs) == 19 else None
        w = render(songs[n], bank, setup_id=setup)
        with self._cache_lock:
            self._wav[key] = w
            while len(self._wav) > 8:
                self._wav.popitem(last=False)
        return w

    def song_mix_wav(self, e: Entry, ns: tuple[int, ...], loops: int = 1) -> bytes:
        """Several of an entry's songs layered (and optionally looped)."""
        key = (e.id, "mix", ns, loops)
        if key in self._wav:
            return self._wav[key]
        bank = self.instrument_bank()
        if bank is None:
            raise RuntimeError("the instrument bank (MusyX song group) was not found in this game")
        from .render import render_layered
        songs = song.parse_songs(self.data(e))
        setup_of = {0: 19, 1: 20} if len(songs) == 19 else {}
        w = render_layered([(songs[n], setup_of.get(n)) for n in ns if n < len(songs)], bank, loops=loops)
        with self._cache_lock:
            self._wav[key] = w
            while len(self._wav) > 8:
                self._wav.popitem(last=False)
        return w

    def extract_midi(self, e: Entry, dest: Path) -> list[Path]:
        songs = song.parse_songs(self.data(e))
        if not songs:
            return []
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for n, s in enumerate(songs):
            p = dest / f"{n + 1:02d}_{s.bpm}bpm_{s.seconds:.0f}s.mid"
            p.write_bytes(song.to_midi(s, f"song {n + 1}"))
            out.append(p)
        return out

    # ---------------------------------------------------------- animation --
    def actor(self, e: Entry) -> list[c3.Bone] | None:
        """The skeleton of a container: bones of its first ACT section."""
        data = self.data(e)
        for s in self.info(e).sections:
            if s.magic == c3.ACT_VERSION and c3.is_actor(data, s.offset):
                return c3.parse_actor(data, s.offset)
        return None

    def skin(self, e: Entry) -> anim.Skin | None:
        data = self.data(e)
        for s in self.info(e).sections:
            if s.kind == "unknown" and anim.is_skin(data, s.offset):
                return anim.parse_skin(data, s.offset)
        return None

    def banks(self, e: Entry) -> list[dict]:
        """Animation banks usable with this entry's skeleton: ANIM sections in
        the file itself, then the character's standalone banks (same slot in
        the DOL sub-file table)."""
        if e.archive != "ZZZZ.dat" or self.actor(e) is None:
            return []
        out = []
        data = self.data(e)
        for s in self.info(e).sections:
            if s.magic == c3.ACT_VERSION and anim.is_bank(data, s.offset):
                b = anim.parse_bank(data, s.offset)
                if b and b.sequences:
                    out.append({"key": f"{e.id}:{s.index}", "entry": e.id, "section": s.index,
                                "label": f"in this file (section {s.index})", "sequences": len(b.sequences)})
        c = chars.classify_entry(e.refs)
        if c and c.get("slot") is not None:
            for x in self.entries:
                if x.kind != "anim" or x.archive != "ZZZZ.dat":
                    continue
                cx = chars.classify_entry(x.refs)
                if cx and cx.get("slot") == c["slot"]:
                    out.append({"key": f"{x.id}:0", "entry": x.id, "section": 0,
                                "label": f"{cx['character']} {cx['role']} (file {x.id})", "sequences": None})
        return out

    def bank(self, key: str) -> tuple[str, anim.Bank] | None:
        """(label, Bank) for a key from `banks`: '<entry>:<section>'."""
        eid, _, sec = key.partition(":")
        x = self.get(eid)
        data = self.data(x)
        base = 0
        if sec and int(sec) and x.kind == "container":
            base = self.info(x).sections[int(sec)].offset
        b = anim.parse_bank(data, base)
        if not b:
            return None
        if not base:
            from .twins import sequence_names
            names = sequence_names(self, x)
            if names and len(names) == len(b.sequences):
                for s, n in zip(b.sequences, names):
                    s.name = n
        c = chars.classify_entry(x.refs)
        label = f"{c['role']}" if (c and x.kind == "anim") else (f"section {sec}" if base else f"file {x.id}")
        return label, b

    def variants(self, e: Entry) -> list[dict]:
        """Colour variants of a character model: slots sharing its body model
        that have their own texture set, with the entry holding that set."""
        c = chars.classify_entry(e.refs)
        if not c or c.get("slot") is None or c["role"] not in ("model", "body model (ARAM)") and not c["role"].startswith("body model"):
            return []
        sets = {}
        for x in self.entries:
            cx = chars.classify_entry(x.refs)
            if cx and cx.get("role") == "textures (ARAM)":
                sets[cx["slot"]] = x.id
        out = []
        for s in chars.variants_of(c["slot"]):
            t = chars.SLOT_TEXTURE_SET.get(s)
            if t is None:
                continue
            if s in sets:
                out.append({"slot": s, "name": chars.SLOT_NAMES[s], "entry": sets[s]})
        return out

    # attached parts: mesh name -> wrist bone id (every character rig shares the
    # Biped-style ids: 16..20 right arm, 22..26 left arm; the hand meshes are
    # modelled from the wrist along +X)
    PART_BONES = {"L_hand": 25, "R_hand": 19, "L_glove": 25, "R_glove": 19,
                  "L_bat": 25, "R_bat": 19, "L_hand_bat": 25, "R_hand_bat": 19}
    # 'bat' = the hands in their bat pose (handless characters' hand slots hold the bat itself)
    PART_SETS = {"hands": ("L_hand", "R_hand"), "gloves": ("L_glove", "R_glove"),
                 "bat": ("L_hand", "R_hand", "L_bat", "R_bat", "L_hand_bat", "R_hand_bat")}

    def parts(self, e: Entry) -> list[dict]:
        """Attachable parts for a character model: hand/glove containers in the
        same file, else the slot's items from the master table."""
        if e.archive != "ZZZZ.dat" or self.actor(e) is None:
            return []
        out = []
        data = self.data(e)
        for s in self.info(e).sections:
            if s.kind == "geopalette":
                m = c3.parse_geopalette(data, s.offset)
                if m and all(mm.name in self.PART_BONES for mm in m.meshes) and m.meshes:
                    out.append({"entry": e.id, "section": s.index, "name": m.meshes[0].name})
        c = chars.classify_entry(e.refs)
        if not out and c and c.get("slot") is not None:
            base = chars.MASTER_VA + (chars.ITEMS_BASE + c["slot"] * 7) * 16
            for x in self.entries:
                for r in x.refs:
                    if r.startswith("dol:.data:"):
                        va = int(r.split(":")[2].split(" ")[0], 16)
                        if base <= va < base + 4 * 16 and x.label:
                            name = x.label.split(".")[0].rstrip("0123456789").rstrip("_")
                            if name in self.PART_BONES:
                                out.append({"entry": x.id, "section": None, "name": name})
        return out

    def _part_meshes(self, part: dict, bat: bool = False) -> tuple[list[c3.Mesh], list, bytes]:
        x = self.get(part["entry"])
        data = self.data(x)
        fi = self.info(x)
        if part["section"] is not None:
            sec = fi.sections[part["section"]]
        else:
            sec = next(s for s in fi.sections if s.kind == "geopalette")
        m = c3.parse_geopalette(data, sec.offset)
        if m and bat:
            hp = self.poses(x, sec.index)
            k = hp.bat_pose() if hp else None
            if k is not None and m.meshes and hp.vertices == len(m.meshes[0].positions):
                m.meshes[0].positions = list(hp.blocks[k])
        return (m.meshes if m else []), fi.all_textures(), data

    def glb(self, e: Entry, section: int, rig: bool = False, bank_keys: tuple[str, ...] = (),
            parts: str = "", variant: int | None = None, pose: int | None = None) -> bytes:
        key = (e.id, section, rig, bank_keys, parts, variant, pose)
        if key in self._glb:
            return self._glb[key]
        bones = self.actor(e) if rig else None
        m = self.model(e, section, posed=not bones, pose=pose)
        data = self.data(e)
        texs = self.info(e).all_textures()
        used = {d.texture for mm in m.meshes for d in mm.draws if d.texture is not None}
        pngs = {i: t.decode_png(data) for i, (_sec, t) in enumerate(texs) if i in used}
        if variant is not None:
            # a colour variant: the same model drawn with the slot's texture set
            v = next((x for x in self.variants(e) if x["slot"] == variant), None)
            if v:
                ve = self.get(v["entry"])
                vdata = self.data(ve)
                vtexs = self.info(ve).all_textures()
                for i, (_sec, t) in enumerate(vtexs):
                    if i in used:
                        pngs[i] = t.decode_png(vdata)
        if bones and parts:
            want = self.PART_SETS.get(parts, ())
            m = c3.Model(list(m.meshes))
            next_tex = len(texs)
            for p in self.parts(e):
                if p["name"] not in want:
                    continue
                meshes, ptexs, pdata = self._part_meshes(p, bat=(parts == "bat"))
                for mm in meshes:
                    mm = c3.Mesh(mm.name, mm.positions, mm.normals, mm.uvs,
                                 [c3.Draw(None if d.texture is None else d.texture + next_tex, d.tris, d.matrix) for d in mm.draws],
                                 mm.tpl_names, attach=self.PART_BONES.get(mm.name))
                    m.meshes.append(mm)
                for i, (_s, t) in enumerate(ptexs):
                    pngs[next_tex + i] = t.decode_png(pdata)
                next_tex += len(ptexs)
        if bones:
            sk = self.skin(e)
            banks = [b for b in (self.bank(k) for k in bank_keys) if b]
            g = c3.to_glb(m, pngs, bones=bones, skin_weights=sk.weights if sk else None, banks=banks)
        else:
            g = c3.to_glb(m, pngs)
        self._glb[key] = g
        while len(self._glb) > 8:
            self._glb.popitem(last=False)
        return g

    def scene_glb(self, e: Entry) -> bytes:
        """Every GeoPalette section of a pack in one glTF, each posed by its own
        actor: a stadium is its field, sky and extras together."""
        key = (e.id, "scene")
        if key in self._glb:
            return self._glb[key]
        data = self.data(e)
        texs = self.info(e).all_textures()
        meshes: list[c3.Mesh] = []
        posed = [(md, self.model(e, md["section"], posed=True)) for md in self.models(e)]
        # the sky dome is the section that spans far more than the park itself; name it so
        # the viewer can draw it inside-out
        def extent(m):
            ps = [p for mm in m.meshes for p in mm.positions]
            return max(max(p[i] for p in ps) - min(p[i] for p in ps) for i in range(3)) if ps else 0.0
        main_md, main = max(posed, key=lambda x: x[0]["triangles"]) if posed else (None, None)
        main_ext = extent(main) if main else 0.0
        for md, m in posed:
            # a dome: spans more than the park with a tiny fraction of its triangles
            sky = m is not main and main_ext and extent(m) > main_ext and md["triangles"] < main_md["triangles"] * 0.1
            for mm in m.meshes:
                # Japanese names arrive with replacement characters; the one in the sky
                # sections is 加算光, "additive light": a sun-glare billboard
                glare = sky and "�" in mm.name
                mm.name = f"s{md['section']} {'glare ' if glare else 'sky ' if sky else ''}{mm.name}"
                meshes.append(mm)
        m = c3.Model(meshes)
        used = {d.texture for mm in m.meshes for d in mm.draws if d.texture is not None}
        pngs = {i: t.decode_png(data) for i, (_sec, t) in enumerate(texs) if i in used}
        g = c3.to_glb(m, pngs)
        self._glb[key] = g
        while len(self._glb) > 8:
            self._glb.popitem(last=False)
        return g

    def collision_mesh(self, e: Entry) -> dict:
        """The collision triangles of a stadium pack in the viewer's space (the
        same 180-degree turn about X the static model export applies)."""
        data = self.data(e)
        for s in self.info(e).sections:
            if collision.is_table(s.magic):
                tris, tags, problems = collision.triangles(data[s.offset:s.offset + s.size])
                names = {t: collision.surface_name(t) for t in set(tags)}
                return {"triangles": [[[x, -y, -z] for x, y, z in t] for t in tris], "tags": tags, "names": names, "problems": problems}
        return {"triangles": [], "tags": [], "names": {}, "problems": []}

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
        if st["kind"] == "musyx":
            return len(self.wav(e, n, max_seconds))
        return dsp.dsp_wav_size(self.data(e), st["pos"], max_seconds)

    def wav_stream(self, e: Entry, n: int = 0, max_seconds: float | None = None):
        """Generator of WAV bytes; the complete file is cached when it finishes."""
        key = (e.id, n, max_seconds)
        if key in self._wav:
            yield self._wav[key]
            return
        st = self.info(e).audio[n]
        if st["kind"] == "musyx":
            yield self.wav(e, n, max_seconds)
            return
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
                wav: bool = False, model: str | None = None, dolphin_pack: bool = False) -> list[Path]:
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
        if dolphin_pack:
            written += self.extract_textures(e, dest / "dolphin" / "GYQE01", dolphin_names=True)
        if wav:
            written += self.extract_audio(e, dest / (self.file_name(e).rsplit(".", 1)[0] + "_wav"))
            written += self.extract_midi(e, dest / (self.file_name(e).rsplit(".", 1)[0] + "_midi"))
        if model:
            written += self.extract_models(e, dest / (self.file_name(e).rsplit(".", 1)[0] + "_model"), model)
        return written

    def extract_textures(self, e: Entry, dest: Path, dolphin_names: bool = False) -> list[Path]:
        """Every texture as PNG. With `dolphin_names` the files carry Dolphin's
        dump names (tex1_<w>x<h>_<hash>..._<fmt>.png), so `dest` can be a
        Dolphin custom-texture pack folder; identical textures collapse to one file."""
        data = self.data(e)
        texs = self.info(e).all_textures()
        if not texs:
            return []
        dest.mkdir(parents=True, exist_ok=True)
        out = []
        for n, (sec, t) in enumerate(texs):
            if dolphin_names:
                p = dest / (dolphin.texture_name(data, t) + ".png")
                if p.exists():
                    continue
            else:
                tag = f"s{sec.index}_" if sec else ""
                p = dest / f"{n:03d}_{tag}t{t.index}_{t.width}x{t.height}_{t.fmt_name}.png"
            p.write_bytes(t.decode_png(data))
            out.append(p)
        return out

    def dolphin_names(self, e: Entry) -> list[str]:
        data = self.data(e)
        return [dolphin.texture_name(data, t) for _sec, t in self.info(e).all_textures()]

    def textures_zip(self, e: Entry, dolphin_names: bool = True) -> bytes:
        """A zip of the entry's textures as PNG, Dolphin-named by default."""
        import io
        import zipfile
        data = self.data(e)
        buf = io.BytesIO()
        seen = set()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for n, (sec, t) in enumerate(self.info(e).all_textures()):
                name = (dolphin.texture_name(data, t) if dolphin_names
                        else f"{n:03d}_{'s%d_' % sec.index if sec else ''}t{t.index}_{t.width}x{t.height}_{t.fmt_name}") + ".png"
                if name in seen:
                    continue
                seen.add(name)
                z.writestr(name, t.decode_png(data))
        return buf.getvalue()

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
        if classify:
            from .twins import annotate
            self.entries = ents
            self.by_id = {e.id: e for e in ents}
            self._data.clear()
            self._info.clear()
            annotate(self, ents, log)
            log(f"annotated unreferenced files ({time.time() - t0:.0f}s)")
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
