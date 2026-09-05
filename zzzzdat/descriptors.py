"""Find every ZZZZ.dat entry descriptor in the game's executables.

ZZZZ.dat has no table of contents. Each asset is described by a 16-byte
record baked into main.dol or one of the RELs, and passed to ARAMTransfer
(0x800A70DC) when the game wants it:

    u16 pad;            // always 0
    u8  repeat_bits;    // LZSS length field width  (0 = stored)
    u8  lookback_bits;  // LZSS distance field width (0 = stored)
    u32 flags_size;     // bits 28-31: 4 = compressed, 0 = stored; bits 0-27: decompressed size
    u32 offset;         // byte offset inside ZZZZ.dat (always 0x800 aligned)
    u32 disc_size;      // bytes to read from the archive

Entries 0-2 of the table at 0x800E8AA8 describe menus/game/debug.rel inside
aaaa.dat instead (the game picks the archive with s32ProgId / s32DataId), and
they are the only descriptors that do not point at ZZZZ.dat.

This module scans the binaries for records of that shape, names each one after
the nearest symbol in config/GYQE01/**/symbols.txt, and writes an index.
"""
from __future__ import annotations

import bisect
import json
import re
import struct
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .disc import ORIG_DIR, REPO_ROOT, VIEWER_ROOT

CONFIG_DIR = REPO_ROOT / "config" / "GYQE01"
INDEX_PATH = VIEWER_ROOT / "index" / "GYQE01.json"

FLAG_COMPRESSED = 4

# REL section numbering used by this game's RELs (see config/GYQE01/*/symbols.txt).
REL_SECTION_NAMES = {1: ".text", 2: ".ctors", 3: ".dtors", 4: ".rodata", 5: ".data", 6: ".bss"}
REL_MODULES = {"game": "game.rel", "menus": "menus.rel", "debug": "debug.rel"}

# aaaa.dat entries: (offset, disc_size) -> file name
AAAA_ENTRIES = {(0x800, 0x5A818): "menus.rel", (0x5B800, 0xF4450): "game.rel", (0x150000, 0x271C0): "debug.rel"}


@dataclass
class Entry:
    id: int
    offset: int
    disc_size: int
    size: int
    flags: int
    lookback_bits: int
    repeat_bits: int
    name: str = ""
    refs: list[str] = field(default_factory=list)  # "module:section:addr symbol+off"
    archive: str = "ZZZZ.dat"
    kind: str = ""        # filled in by classify (formats.identify)
    ntex: int = 0         # textures found inside
    nsec: int = 0         # container sections
    label: str = ""       # embedded asset name (e.g. stadium0.gpc)
    names: list[str] = field(default_factory=list)  # all embedded .gpc/.tpl names
    known: str = ""       # community name from index/known_names.json

    @property
    def symbol(self) -> str:
        """Best symbol hint: 'module symbol+off' of the first reference."""
        if not self.refs:
            return ""
        if self.refs[0].startswith("scan:"):
            return self.refs[0]
        mod = self.refs[0].split(":")[0]
        parts = self.refs[0].split(" ", 1)
        return f"{mod} {parts[1]}" if len(parts) > 1 else mod

    @property
    def module(self) -> str:
        return self.refs[0].split(":")[0] if self.refs else ""

    @property
    def compressed(self) -> bool:
        return self.flags == FLAG_COMPRESSED

    @property
    def end(self) -> int:
        return self.offset + self.disc_size


# ---------------------------------------------------------------- symbols --

_SYM_RE = re.compile(r"^(\S+) = (\.\w+):0x([0-9A-Fa-f]+);(?: // (.*))?")


def load_symbols(path: Path) -> dict[str, list[tuple[int, str, int]]]:
    """{section: sorted [(addr, name, size)]}."""
    out: dict[str, list[tuple[int, str, int]]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _SYM_RE.match(line)
        if not m:
            continue
        name, sec, addr, attrs = m.groups()
        size = 0
        if attrs:
            ms = re.search(r"size:0x([0-9A-Fa-f]+)", attrs)
            if ms:
                size = int(ms.group(1), 16)
        out.setdefault(sec, []).append((int(addr, 16), name, size))
    for lst in out.values():
        lst.sort()
    return out


def nearest_symbol(syms: list[tuple[int, str, int]], addr: int) -> tuple[str, int] | None:
    i = bisect.bisect_right(syms, (addr, "￿", 0)) - 1
    if i < 0:
        return None
    saddr, name, _size = syms[i]
    return name, addr - saddr


# ----------------------------------------------------------------- binaries --

@dataclass
class Binary:
    module: str
    path: Path
    data: bytes
    # (file offset, length, section name, section base addr)
    sections: list[tuple[int, int, str, int]]


def load_dol(path: Path) -> Binary:
    d = path.read_bytes()
    offs = struct.unpack(">18I", d[0:0x48])
    addrs = struct.unpack(">18I", d[0x48:0x90])
    sizes = struct.unpack(">18I", d[0x90:0xD8])
    secs = []
    data_idx = 0
    for i, (o, a, s) in enumerate(zip(offs, addrs, sizes)):
        if not s:
            continue
        if i < 7:
            name = ".text"
        else:
            # MetroWerks DOLs put extab/extabindex first among the data sections;
            # they hold exception tables, never descriptors.
            name = {0: "extab", 1: "extabindex"}.get(data_idx, ".data")
            data_idx += 1
        secs.append((o, s, name, a))
    return Binary("dol", path, d, secs)


def load_rel(module: str, path: Path) -> Binary:
    d = path.read_bytes()
    num, sec_off = struct.unpack(">II", d[12:20])
    secs = []
    for i in range(num):
        o, s = struct.unpack(">II", d[sec_off + i * 8:sec_off + i * 8 + 8])
        o &= ~3
        if s and o:
            secs.append((o, s, REL_SECTION_NAMES.get(i, f".sec{i}"), 0))
    return Binary(module, path, d, secs)


def load_binaries(orig_dir: Path = ORIG_DIR) -> list[Binary]:
    bins = []
    dol = orig_dir / "sys" / "main.dol"
    if dol.exists():
        bins.append(load_dol(dol))
    for module, fname in REL_MODULES.items():
        p = orig_dir / "files" / fname
        if p.exists():
            bins.append(load_rel(module, p))
    return bins


# --------------------------------------------------------------------- scan --

def looks_like_descriptor(p: int, fs: int, off: int, cs: int, archive_size: int) -> bool:
    if p >> 16:
        return False
    flag, size = fs >> 28, fs & 0x0FFFFFFF
    rb, lb = (p >> 8) & 0xFF, p & 0xFF
    if off & 0x7FF or off >= archive_size or cs == 0 or size == 0:
        return False
    if off + cs > archive_size:
        return False
    if flag == 0:
        # stored: tiny sizes and offset==size are number tables, not descriptors
        return p == 0 and cs >= size and cs - size < 32 and size >= 0x80 and off != cs
    if flag == FLAG_COMPRESSED:
        return 8 <= lb <= 16 and 2 <= rb <= 8 and cs <= size
    return False


def symbol_lookup_for(symtabs: dict, b: Binary, secname: str):
    """DOL symbols carry absolute addresses; REL symbols are section-relative."""
    if b.module == "dol":
        merged = []
        for lst in symtabs.get("dol", {}).values():
            merged.extend(lst)
        merged.sort()
        return merged
    return symtabs.get(b.module, {}).get(secname)


def scan_binary(b: Binary, archive_size: int, symtabs: dict) -> list[tuple[tuple, str]]:
    """Return [(descriptor tuple, ref string)] for each hit in the binary."""
    hits = []
    d = b.data
    cache = {}
    for fo, ln, secname, base in b.sections:
        if secname in (".text", "extab", "extabindex"):
            continue  # descriptors are data, never code or exception tables
        if secname not in cache:
            cache[secname] = symbol_lookup_for(symtabs, b, secname)
        syms = cache[secname]
        end = fo + ln - 16
        i = fo
        while i <= end:
            p, fs, off, cs = struct.unpack_from(">4I", d, i)
            if looks_like_descriptor(p, fs, off, cs, archive_size):
                addr = base + (i - fo)
                ref = f"{b.module}:{secname}:{addr:#x}"
                if syms:
                    ns = nearest_symbol(syms, addr)
                    if ns:
                        ref += f" {ns[0]}+{ns[1]:#x}" if ns[1] else f" {ns[0]}"
                hits.append(((p, fs, off, cs), ref))
                i += 16
            else:
                i += 4
    return hits


def _parse_ref(ref: str) -> tuple[str, str, int]:
    mod, sec, addr = ref.split(" ")[0].split(":")
    return mod, sec, int(addr, 16)


def verify_entries(entries: list[Entry], archive, probe: int = 0x2000) -> list[Entry]:
    """Keep the descriptors that are demonstrably real.

    Compressed entries are checked by decoding their first `probe` bytes.
    Stored entries cannot be checked that way, so they are judged by the table
    they sit in: descriptors are laid out as contiguous 16-byte records, and a
    table containing a record that fails to decode, or that collides with a
    verified entry, is not a descriptor table at all (e.g. the .adp streaming
    sizes in debug.rel happen to fit the shape). Stored records from healthy
    tables are accepted largest-table-first as long as they do not overlap
    anything already accepted.
    """
    from .lzss import decompress

    passthrough = [e for e in entries if e.archive != "ZZZZ.dat"]
    cands = [e for e in entries if e.archive == "ZZZZ.dat"]

    failed: set[int] = set()
    for e in cands:
        if not e.compressed:
            continue
        want = min(e.size, probe)
        need = min(e.disc_size, want * 2 + 64)
        try:
            out = decompress(archive.read(e.offset, need), e.lookback_bits, e.repeat_bits, want)
            if len(out) != want:
                failed.add(id(e))
        except ValueError:
            failed.add(id(e))
    verified = [e for e in cands if e.compressed and id(e) not in failed]

    # Group refs into contiguous tables: same module+section, 16 bytes apart.
    by_addr: dict[tuple[str, str, int], Entry] = {}
    for e in cands:
        for r in e.refs:
            by_addr[_parse_ref(r)] = e
    tables: list[list[Entry]] = []
    seen_addr: set = set()
    for key in sorted(by_addr):
        if key in seen_addr:
            continue
        mod, sec, addr = key
        table = []
        while (mod, sec, addr) in by_addr:
            seen_addr.add((mod, sec, addr))
            table.append(by_addr[(mod, sec, addr)])
            addr += 16
        tables.append(table)

    spans = sorted((e.offset, e.end) for e in verified)

    def collides(e: Entry, spans_sorted) -> bool:
        i = bisect.bisect_right(spans_sorted, (e.offset, 1 << 40))
        if i < len(spans_sorted) and spans_sorted[i][0] < e.end:
            return True
        return i > 0 and spans_sorted[i - 1][1] > e.offset

    healthy = []
    for t in tables:
        bad = any(id(e) in failed for e in t) or any(
            not e.compressed and collides(e, spans) for e in t)
        if not bad:
            healthy.append(t)
    healthy.sort(key=len, reverse=True)

    accepted: dict[int, Entry] = {id(e): e for e in verified}
    acc_spans = list(spans)
    for t in healthy:
        for e in t:
            if e.compressed or id(e) in accepted:
                continue
            if collides(e, acc_spans):
                continue
            accepted[id(e)] = e
            bisect.insort(acc_spans, (e.offset, e.end))

    keep = sorted(accepted.values(), key=lambda e: (e.offset, e.disc_size)) + passthrough
    for i, e in enumerate(keep):
        e.id = i
    return keep


def build_index(archive_size: int, orig_dir: Path = ORIG_DIR) -> list[Entry]:
    symtabs = {"dol": load_symbols(CONFIG_DIR / "symbols.txt")}
    for module in REL_MODULES:
        symtabs[module] = load_symbols(CONFIG_DIR / module / "symbols.txt")

    seen: dict[tuple, Entry] = {}
    for b in load_binaries(orig_dir):
        for (p, fs, off, cs), ref in scan_binary(b, archive_size, symtabs):
            key = (off, cs, fs, p)
            e = seen.get(key)
            if e is None:
                e = Entry(0, off, cs, fs & 0x0FFFFFFF, fs >> 28, p & 0xFF, (p >> 8) & 0xFF)
                if (off, cs) in AAAA_ENTRIES:
                    e.archive = "aaaa.dat"
                    e.name = AAAA_ENTRIES[(off, cs)]
                seen[key] = e
            if ref not in e.refs:
                e.refs.append(ref)

    entries = sorted(seen.values(), key=lambda e: (e.archive != "ZZZZ.dat", e.offset, e.disc_size))
    for i, e in enumerate(entries):
        e.id = i
        if not e.name:
            e.name = f"{e.offset:08x}"
    return entries


# --------------------------------------------------------- archive scans --
# Two techniques borrowed from roeming/MssbAssetDecompressor for the parts of
# the archive that no executable descriptor points at.

ADGC_MAGIC = b"AdGCForm"


def scan_adgc(archive, log=lambda *a: None) -> list[Entry]:
    """Sound-bank files: each starts with 'AdGCForm', preceded by an 8-byte
    little-endian fingerprint {flags|size, compression params}. They are packed
    back to back and are not 0x800-aligned, so they never match the descriptor
    scan; the compressed size is recovered by decoding the stream."""
    from .lzss import decompress_ex
    hits = []
    chunk = 16 << 20
    off = 0
    while off < archive.size:
        b = archive.read(off, min(chunk + 16, archive.size - off))
        i = b.find(ADGC_MAGIC)
        while i != -1:
            hits.append(off + i)
            i = b.find(ADGC_MAGIC, i + 1)
        off += chunk
    out = []
    for h in sorted(set(hits)):
        if h < 8:
            continue
        fs, ci = struct.unpack("<II", archive.read(h - 8, 8))
        flag, size = fs >> 28, fs & 0x0FFFFFFF
        lb, rb = ci & 0xFF, (ci >> 8) & 0xFF
        start = h + len(ADGC_MAGIC)  # the LZSS stream begins right after the magic
        if flag == 0 or size == 0:
            start = h
            e = Entry(0, start, size, size, 0, 0, 0, refs=["scan:AdGCForm"])
        else:
            raw = archive.read(start, min(size * 2 + 64, archive.size - start))
            try:
                _, used = decompress_ex(raw, lb, rb, size)
            except ValueError:
                log(f"  AdGCForm at {h:#x}: undecodable, skipped")
                continue
            e = Entry(0, start, used, size, FLAG_COMPRESSED, lb, rb, refs=["scan:AdGCForm"])
        out.append(e)
    return out


def scan_unreferenced(archive, known: list[Entry], log=lambda *a: None, probe: int = 0x200) -> list[Entry]:
    """Brute force: at every 0x800 boundary not covered by a known entry, try to
    decode `probe` bytes with each LZSS parameter set. A hit is assumed to run
    to the next hit or the next known entry; its decompressed size is whatever
    the stream yields before the input ends, so sizes here are approximate and
    may include some trailing junk decoded from padding."""
    from .lzss import decompress_ex
    spans = sorted((e.offset, e.end) for e in known if e.archive == "ZZZZ.dat")
    gaps = []
    cur = 0
    for s, e in spans:
        if s > cur + 0x800:
            gaps.append((cur, s))
        cur = max(cur, e)
    if cur < archive.size:
        gaps.append((cur, archive.size))
    hits = []
    for g0, g1 in gaps:
        g0 = (g0 + 0x7FF) & ~0x7FF
        for off in range(g0, g1, 0x800):
            b = archive.read(off, min(0x1000, archive.size - off))
            for lb, rb in ((0xB, 4), (0xE, 5)):
                try:
                    o, _ = decompress_ex(b, lb, rb, probe)
                except ValueError:
                    continue
                if len(o) == probe:
                    hits.append((off, lb, rb, g1))
                    break
    log(f"  probe: {len(hits)} unreferenced streams in {len(gaps)} gaps")
    out = []
    for i, (off, lb, rb, g1) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) and hits[i + 1][0] < g1 else g1
        raw = archive.read(off, end - off)
        o, used = decompress_ex(raw, lb, rb, None, tolerant=True)
        if len(o) < probe:
            continue
        out.append(Entry(0, off, used, len(o), FLAG_COMPRESSED, lb, rb, refs=["scan:lzss-probe"]))
    return out


def load_known_names(path: Path) -> dict[int, str]:
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {int(k, 16): v for k, v in doc.get("names", {}).items()}


# ----------------------------------------------------------------- persist --

def save_index(entries: list[Entry], path: Path = INDEX_PATH, meta: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"meta": meta or {}, "entries": [asdict(e) for e in entries]}
    path.write_text(json.dumps(doc, indent=1), encoding="utf-8")


def load_index(path: Path = INDEX_PATH) -> list[Entry]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [Entry(**e) for e in doc["entries"]]


def coverage(entries: list[Entry], archive_size: int) -> dict:
    """How much of ZZZZ.dat the found descriptors account for."""
    spans = sorted((e.offset, e.end) for e in entries if e.archive == "ZZZZ.dat")
    covered = 0
    overlaps = 0
    gaps = []
    cur = 0
    for s, e in spans:
        if s < cur:
            overlaps += 1
            s = cur
        elif s > cur:
            gaps.append((cur, s))
        if e > s:
            covered += e - s
            cur = e
    if cur < archive_size:
        gaps.append((cur, archive_size))
    # entries are 0x800-aligned so small tails between them are padding, not data
    real_gaps = [(a, b) for a, b in gaps if b - a > 0x800]
    return {"covered": covered, "archive_size": archive_size, "overlaps": overlaps,
            "gaps": len(real_gaps), "gap_bytes": sum(b - a for a, b in real_gaps),
            "largest_gaps": sorted(real_gaps, key=lambda g: g[0] - g[1])[:10]}
