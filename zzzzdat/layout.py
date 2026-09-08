"""Where each build of the game keeps its tables.

Every version of Mario Superstar Baseball has the same data laid out in the
same order in main.dol -- the character sub-file table, the master character
descriptors, the stadium files, the MusyX groups, the streamed-music table --
but at different addresses, because the code around them is a different size
in each region. Rather than keep a hand-written address list per version, this
module *finds* the tables in whatever DOL it is given and reports where they
are. The US addresses are the defaults, so nothing changes for GYQE01 even if
the search is skipped.

How each table is found (all of it from the DOL alone, so it works before
anything has been read out of ZZZZ.dat):

* **RELs in aaaa.dat** -- three consecutive compressed descriptors, the first
  at archive offset 0x800, whose contents are menus.rel, game.rel, debug.rel.
  This is the table entries 0-2 of which `descriptors.py` documents at
  0x800E8AA8 in the US build.
* **The ARAM chunk and the sub-file table** -- one *stored* descriptor for a
  multi-megabyte block, immediately followed by the long run of per-slot
  sub-file descriptors. Its offset is the base the master table's own offsets
  are relative to (0x1A15E800 in the US build), and the run starts 16 bytes
  after it.
* **The master character table** -- the longest run of records that only make
  sense as offsets *inside* that chunk (32-byte aligned, not 0x800), starting
  at the record for offset zero, which is the chunk's first body model.
* **The stadium table** -- the run of ordinary descriptors that ends exactly
  where the master table begins; its length divided by three is the number of
  stadiums.
* **The MusyX groups** -- the run of descriptors before the stadium table,
  confirmed by decoding the first one and checking it is a group file.
* **The hand, hand-pose, slot, glove and event-set tables** -- derived from
  the sub-file table's address, and confirmed against the tables' contents,
  which are identical in every build; if the derivation disagrees, those
  contents are searched for instead. (The slot table works the other way
  round: finding it by content is what pins down how many entries the master
  table ends with.)
* **The streamed-music table** -- the run of 16-byte records whose first word
  points at an `snd/my_snd_h/...` path.

`use()` points the modules that read these tables at one layout. There is one
game open at a time, so they hold it as module state rather than threading it
through every call; `Store` sets it when it opens a game, and the resolved
addresses are cached in the index so the search runs once per version.
"""
from __future__ import annotations

import struct
from dataclasses import asdict, dataclass, field

from .descriptors import FLAG_COMPRESSED, load_dol_sections, looks_like_descriptor

# The tables' shapes, which no version changes (54 slots of 19 animation tracks,
# six hand descriptors each, three file slots per stadium).
SLOTS = 54
TRACKS = 19
HANDS_PER_SLOT = 6
SLOTS_PER_STADIUM = 3
# master table: bodies, texture sets, seven sub-items per slot, a rig per slot,
# then the shared hand-pose event sets
MASTER_SHARED_BASE = 486


@dataclass
class Layout:
    """One build's addresses. The defaults are the US build (GYQE01)."""

    key: str = "GYQE01"
    aram_chunk: int = 0x1A15E800
    subfiles_va: int = 0x800F1D78
    hand_table_va: int = 0x800F5D98
    event_copy_va: int = 0x800F71D8      # hand-pose event sets held outside ARAM
    slot_table_va: int = 0x800F73B8
    glove_va: int = 0x800EEAAC
    event_set_va: int = 0x800EEB18
    master_va: int = 0x800EFD38
    master_entries: int = 516
    stadium_va: int = 0x800EFBE8
    stadiums: int = 7
    musyx_va: int = 0x800EF508
    musyx_count: int = 48
    rel_table_va: int = 0x800E8AA8
    rel_table_count: int = 68            # the RELs, then the screens the DOL itself loads
    # module -> (archive offset, bytes on disc, decompressed size)
    rels: dict[str, tuple[int, int, int]] = field(default_factory=lambda: {
        "menus": (0x800, 0x5A818, 0x1027E4), "game": (0x5B800, 0xF4450, 0x2220F8),
        "debug": (0x150000, 0x271C0, 0x5912C)})
    music_table_va: int = 0x800E87B4
    music_tracks: int = 15
    resolved: bool = False               # False when these are the defaults, not a search result

    # what the scanner needs to know ------------------------------------
    @property
    def aaaa_entries(self) -> dict[tuple[int, int], str]:
        """{(offset, disc size): file name} for the RELs, which live in aaaa.dat."""
        return {(o, c): f"{m}.rel" for m, (o, c, _s) in self.rels.items()}

    @property
    def relative_tables(self) -> dict[int, tuple[int, int]]:
        """{table address: (entry count, base offset)} for tables whose offsets
        are relative to a chunk of the archive rather than to its start."""
        return {self.master_va: (self.master_entries, self.aram_chunk)}

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rels"] = {m: list(v) for m, v in self.rels.items()}
        return d

    @staticmethod
    def from_dict(d: dict) -> "Layout":
        d = dict(d)
        known = {f for f in Layout.__dataclass_fields__}
        d = {k: v for k, v in d.items() if k in known}
        if "rels" in d:
            d["rels"] = {m: tuple(v) for m, v in d["rels"].items()}
        return Layout(**d)


US = Layout()


# ------------------------------------------------------------------- DOL --

class Dol:
    """A DOL's data sections, addressable both ways."""

    def __init__(self, data: bytes):
        self.data = data
        self.sections = load_dol_sections(data)

    @property
    def data_sections(self) -> list[tuple[int, int, int]]:
        """(file offset, length, address) of the sections descriptors can be in."""
        return [(o, s, a) for o, s, name, a in self.sections if name == ".data"]

    def offset_of(self, va: int) -> int | None:
        for o, s, _name, a in self.sections:
            if a <= va < a + s:
                return o + (va - a)
        return None

    def va_of(self, off: int) -> int | None:
        for o, s, _name, a in self.sections:
            if o <= off < o + s:
                return a + (off - o)
        return None

    def u32(self, va: int) -> int | None:
        o = self.offset_of(va)
        return None if o is None or o + 4 > len(self.data) else struct.unpack_from(">I", self.data, o)[0]

    def cstr(self, va: int, limit: int = 128) -> str | None:
        o = self.offset_of(va)
        if o is None:
            return None
        end = self.data.find(b"\0", o, o + limit)
        return None if end < 0 else self.data[o:end].decode("ascii", "replace")

    def record(self, va: int) -> tuple[int, int, int, int] | None:
        o = self.offset_of(va)
        if o is None or o + 16 > len(self.data):
            return None
        return struct.unpack_from(">4I", self.data, o)

    def find(self, pattern: bytes) -> list[int]:
        """Addresses at which these exact bytes appear in a data section."""
        out = []
        i = self.data.find(pattern)
        while i != -1:
            va = self.va_of(i)
            if va is not None:
                out.append(va)
            i = self.data.find(pattern, i + 1)
        return out


def _runs(dol: Dol, archive_size: int, base: int = 0, align: int = 0x7FF,
          minimum: int = 3) -> list[tuple[int, int]]:
    """[(address, record count)] of every run of back-to-back descriptors.
    With `base` set, the records are read as offsets inside that chunk."""
    limit = archive_size - base
    out = []
    for fo, ln, addr in dol.data_sections:
        i = fo
        end = fo + ln - 16
        start = None
        count = 0
        while i <= end:
            p, fs, off, cs = struct.unpack_from(">4I", dol.data, i)
            if looks_like_descriptor(p, fs, off, cs, limit, align=align):
                if start is None:
                    start = addr + (i - fo)
                count += 1
                i += 16
            else:
                if start is not None and count >= minimum:
                    out.append((start, count))
                start, count = None, 0
                i += 4
        if start is not None and count >= minimum:
            out.append((start, count))
    return out


# -------------------------------------------------------------- searching --

AAAA_MAX = 4 << 20  # aaaa.dat is about 1.5 MB; the RELs are the only things in it


def _find_rel_table(dol: Dol) -> tuple[int, dict[str, tuple[int, int, int]]] | None:
    """The three RELs' descriptors: compressed, ascending, the first at 0x800."""
    for fo, ln, addr in dol.data_sections:
        for i in range(fo, fo + ln - 48, 4):
            recs = [struct.unpack_from(">4I", dol.data, i + k * 16) for k in range(3)]
            if recs[0][2] != 0x800:
                continue
            if any(fs >> 28 != FLAG_COMPRESSED or cs == 0 or off & 0x7FF or off + cs > AAAA_MAX
                   for _p, fs, off, cs in recs):
                continue
            if not (recs[0][2] < recs[1][2] < recs[2][2]):
                continue
            if any(recs[k][2] + recs[k][3] > recs[k + 1][2] for k in range(2)):
                continue
            rels = {m: (r[2], r[3], r[1] & 0x0FFFFFFF)
                    for m, r in zip(("menus", "game", "debug"), recs)}
            return addr + (i - fo), rels
    return None


def _find_chunk(dol: Dol, archive_size: int) -> tuple[int, int] | None:
    """(ARAM chunk offset, sub-file table address): a stored descriptor for a
    multi-megabyte block with the sub-file table right behind it."""
    best = None
    for fo, ln, addr in dol.data_sections:
        for i in range(fo, fo + ln - 16, 4):
            p, fs, off, cs = struct.unpack_from(">4I", dol.data, i)
            if p or fs >> 28 or cs != (fs & 0x0FFFFFFF) or cs < (1 << 20):
                continue
            if off & 0x7FF or off + cs > archive_size:
                continue
            following = 0
            j = i + 16
            while j + 16 <= fo + ln and following < 4:
                q, qfs, qoff, qcs = struct.unpack_from(">4I", dol.data, j)
                if not looks_like_descriptor(q, qfs, qoff, qcs, archive_size):
                    break
                following += 1
                j += 16
            if following >= 4 and (best is None or cs > best[2]):
                best = (off, addr + (i - fo) + 16, cs)
    return (best[0], best[1]) if best else None


def _find_master(dol: Dol, archive_size: int, chunk: int) -> tuple[int, int] | None:
    """The master character table: a long run of chunk-relative descriptors
    whose first record is the one at offset zero inside the chunk -- entry 0 is
    the first body model, which is what the chunk starts with. Ordinary
    descriptors with small offsets also read as chunk-relative, so that first
    record is what tells the real table from them."""
    best = None
    for start, count in _runs(dol, archive_size, base=chunk, align=0x1F, minimum=100):
        # the stadium table sits directly in front of the master one and its
        # offsets read as chunk-relative too, so the run can begin early
        for i in range(count):
            rec = dol.record(start + i * 16)
            if rec and rec[2] == 0 and rec[1] >> 28 == FLAG_COMPRESSED and rec[3]:
                left = count - i
                if left >= 100 and (best is None or left > best[1]):
                    best = (start + i * 16, left)
                break
    return best


def _find_stadiums(runs: list[tuple[int, int]], master_va: int) -> tuple[int, int] | None:
    """The descriptor run that ends where the master table starts."""
    for va, count in runs:
        if va < master_va <= va + count * 16 and (master_va - va) % 16 == 0:
            slots = (master_va - va) // 16
            if slots >= SLOTS_PER_STADIUM and slots % SLOTS_PER_STADIUM == 0:
                return va, slots // SLOTS_PER_STADIUM
    return None


def _find_musyx(dol: Dol, runs: list[tuple[int, int]], stadium_va: int, archive) -> tuple[int, int] | None:
    """The descriptor run before the stadium table, confirmed by decoding its
    first file and finding a MusyX group header."""
    from . import musyx
    from .lzss import decompress
    for va, count in sorted((r for r in runs if r[0] < stadium_va), key=lambda r: -r[0]):
        if archive is None:
            return va, count
        rec = dol.record(va)
        if not rec:
            continue
        p, fs, off, cs = rec
        size = fs & 0x0FFFFFFF
        if size > (8 << 20):
            continue
        try:
            head = archive.read(off, cs)
            if fs >> 28 == FLAG_COMPRESSED:
                head = bytes(decompress(head, p & 0xFF, (p >> 8) & 0xFF, size))
        except (ValueError, OSError):
            continue
        if musyx.is_group(head):
            return va, count
    return None


def _find_music(dol: Dol) -> tuple[int, int] | None:
    """(table address, track count) of the streamed-music table: 16-byte records
    starting with a pointer to an snd/my_snd_h path."""
    hits = []
    for fo, ln, addr in dol.data_sections:
        for i in range(fo, fo + ln - 16, 4):
            ptr = struct.unpack_from(">I", dol.data, i)[0]
            if not 0x80000000 < ptr < 0x80400000:
                continue
            s = dol.cstr(ptr, 48)
            if s and s.startswith("snd/my_snd_h/"):
                hits.append((addr + (i - fo), ptr))
    if not hits:
        return None
    first = hits[0][0]
    run = [h for n, h in enumerate(hits) if h[0] == first + n * 16]
    return first, len(run)


def _u16_table(values) -> bytes:
    return struct.pack(f">{len(values)}H", *values)


def _find_named_tables(dol: Dol, l: Layout) -> None:
    """Confirm (or, if the derivation is wrong, locate) the small tables whose
    contents are the same in every build."""
    from . import chars
    for name, pattern, derived in (
            ("slot_table_va", _u16_table(chars.SLOT_TABLE), l.slot_table_va),
            ("glove_va", _u16_table([s * HANDS_PER_SLOT for s in range(SLOTS)]), None),
            ("event_set_va", _u16_table([v & 0xFFFF for v in chars.EVENT_SETS]), None)):
        hits = dol.find(pattern)
        if derived is not None and derived in hits:
            continue
        if len(hits) == 1:
            setattr(l, name, hits[0])


# ---------------------------------------------------------------- resolve --

def resolve(dol_data: bytes, archive_size: int, archive=None, key: str = "") -> Layout:
    """Find one build's tables in its main.dol. Anything the search cannot
    place keeps the US address, so a partly recognised DOL still works as far
    as it goes."""
    dol = Dol(dol_data)
    l = Layout(key=key or US.key)
    found = _find_rel_table(dol)
    if found:
        l.rel_table_va, l.rels = found
    chunk = _find_chunk(dol, archive_size)
    if chunk:
        l.aram_chunk, l.subfiles_va = chunk
        l.hand_table_va = l.subfiles_va + SLOTS * TRACKS * 16
        l.event_copy_va = l.hand_table_va + SLOTS * HANDS_PER_SLOT * 16
        master = _find_master(dol, archive_size, l.aram_chunk)
        if master:
            l.master_va, l.master_entries = master
            l.slot_table_va = l.event_copy_va + (l.master_entries - MASTER_SHARED_BASE) * 16
            runs = _runs(dol, archive_size)
            here = [n for va, n in runs if va == l.rel_table_va]
            if here:
                l.rel_table_count = here[0]
            stad = _find_stadiums(runs, l.master_va)
            if stad:
                l.stadium_va, l.stadiums = stad
                mus = _find_musyx(dol, runs, l.stadium_va, archive)
                if mus:
                    l.musyx_va, l.musyx_count = mus
    _find_named_tables(dol, l)
    # the slot table's contents pin down where it is, and so how many shared
    # entries the master table ends with -- a surer count than the run's length,
    # which stops one short when the last record does not read as a descriptor
    shared = (l.slot_table_va - l.event_copy_va) // 16
    if 0 < shared <= 64 and l.slot_table_va > l.event_copy_va:
        l.master_entries = MASTER_SHARED_BASE + shared
    music = _find_music(dol)
    if music:
        l.music_table_va, l.music_tracks = music
    l.resolved = True
    return l


def check(l: Layout) -> list[str]:
    """What about a resolved layout does not add up. Empty means it all does."""
    bad = []
    if l.slot_table_va != l.event_copy_va + (l.master_entries - MASTER_SHARED_BASE) * 16:
        bad.append("the slot table is not where the character tables' sizes say it should be")
    if l.hand_table_va != l.subfiles_va + SLOTS * TRACKS * 16:
        bad.append("the hand table is not right after the sub-file table")
    if l.master_entries < MASTER_SHARED_BASE:
        bad.append(f"the master table has only {l.master_entries} entries")
    if not 1 <= l.stadiums <= 32:
        bad.append(f"{l.stadiums} stadiums")
    if len(l.rels) != 3:
        bad.append("the RELs' descriptors were not found in the DOL")
    return bad


# ------------------------------------------------------------------- use --

CURRENT = US


def current() -> Layout:
    return CURRENT


def use(l: Layout) -> None:
    """Point every module that reads a DOL table at this build's addresses.
    One game is open at a time, so the addresses live as module state; this is
    the only place that writes them."""
    global CURRENT
    from . import chars, stadiums
    from .music import dolinfo
    CURRENT = l
    chars.ARAM_CHUNK = l.aram_chunk
    chars.SUBFILES_VA = l.subfiles_va
    chars.HAND_TABLE_VA = l.hand_table_va
    chars.EVENT_COPY_VA = l.event_copy_va
    chars.SLOT_TABLE_VA = l.slot_table_va
    chars.GLOVE_VA = l.glove_va
    chars.EVENT_SET_VA = l.event_set_va
    chars.MASTER_VA = l.master_va
    chars.MASTER_ENTRIES = l.master_entries
    stadiums.STADIUM_VA = l.stadium_va
    dolinfo.TABLE_VA = l.music_table_va
