"""Writing assets back: replace an entry's data and repoint its descriptors.

Needs an extracted game folder holding ZZZZ.dat, aaaa.dat and sys/main.dol
(`python -m zzzzdat dump --only ZZZZ.dat,aaaa.dat` is enough).

How a replacement works:
1. The new bytes are LZSS-compressed with the entry's original parameters
   (or stored raw if the original was stored).
2. If the result fits the entry's original 0x800-aligned span it is written
   in place; otherwise it is appended to the end of ZZZZ.dat.
3. Every descriptor that references the entry is rewritten with the new size,
   offset and disc size: in main.dol directly; in a REL by decompressing it
   out of aaaa.dat, patching, recompressing and writing it back (it must still
   fit its slot).
4. Before the first change to an entry its descriptors and data are saved
   under <files>/_mssb_editor_backup/ so `restore` can undo it, and an
   overrides file records the entry's new location for the index.
"""
from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path

from . import chars, lzss
from .descriptors import AAAA_ENTRIES, FLAG_COMPRESSED, RELATIVE_TABLES, REL_MODULES, Entry
from .disc import Game

BACKUP_DIRNAME = "_mssb_editor_backup"
SECTOR = 0x800
REL_SIZES = {"menus.rel": 0x1027E4, "game.rel": 0x2220F8, "debug.rel": 0x5912C}
REL_SECTION_INDEX = {".text": 1, ".ctors": 2, ".dtors": 3, ".rodata": 4, ".data": 5, ".bss": 6}


class EditError(Exception):
    pass


@dataclass
class Ref:
    module: str
    section: str
    addr: int

    @staticmethod
    def parse(r: str) -> "Ref | None":
        head = r.split(" ")[0]
        parts = head.split(":")
        if len(parts) != 3 or parts[0] in ("scan", "disc"):
            return None
        return Ref(parts[0], parts[1], int(parts[2], 16))


def overrides_path(game: Game) -> Path:
    return game.files_dir / BACKUP_DIRNAME / "overrides.json"


def load_journal(game: Game) -> dict:
    p = (game.files_dir / BACKUP_DIRNAME / "journal.json") if game.files_dir else None
    if p and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def load_overrides(game: Game) -> dict:
    p = overrides_path(game) if game.files_dir else None
    if p and p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


class Editor:
    def __init__(self, game: Game):
        self.game = game
        if not game.writable:
            raise EditError("the game is view-only; extract it to a folder first")
        self.archive = game.files_dir / "ZZZZ.dat"
        self.aaaa = game.files_dir / "aaaa.dat"
        self.dol = game.dol_path()
        missing = [str(p.name) for p in (self.archive, self.aaaa) if not p.exists()]
        if not self.dol:
            missing.append("sys/main.dol")
        if missing:
            raise EditError("editing needs " + ", ".join(missing) + " in the game folder "
                            "(run `python -m zzzzdat dump --only ZZZZ.dat,aaaa.dat` or use Prepare for editing)")
        self.backup_dir = game.files_dir / BACKUP_DIRNAME
        self.backup_dir.mkdir(exist_ok=True)
        self.journal_path = self.backup_dir / "journal.json"
        self.journal = json.loads(self.journal_path.read_text(encoding="utf-8")) if self.journal_path.exists() else {}

    # ------------------------------------------------------------ helpers --
    def _save(self) -> None:
        self.journal_path.write_text(json.dumps(self.journal, indent=1), encoding="utf-8")
        ov = {k: v["current"] for k, v in self.journal.items() if not k.startswith("_") and v.get("current")}
        overrides_path(self.game).write_text(json.dumps(ov, indent=1), encoding="utf-8")

    def _dol_offset(self, va: int) -> int:
        d = self.dol.read_bytes()
        offs = struct.unpack(">18I", d[0:0x48])
        addrs = struct.unpack(">18I", d[0x48:0x90])
        sizes = struct.unpack(">18I", d[0x90:0xD8])
        for o, a, s in zip(offs, addrs, sizes):
            if s and a <= va < a + s:
                return o + (va - a)
        raise EditError(f"address {va:#x} is not in main.dol")

    def _rel_bytes(self, module: str) -> tuple[bytes, tuple[int, int]]:
        fname = REL_MODULES[module]
        off, stock_cs = next(((off, cs) for (off, cs), n in AAAA_ENTRIES.items() if n == fname))
        # the current compressed size is in the DOL (it changes when we repack)
        d = self.dol.read_bytes()
        o = self._dol_offset(0x800E8AA8 + ["menus", "game", "debug"].index(module) * 16)
        cs = struct.unpack_from(">I", d, o + 12)[0] or stock_cs
        with open(self.aaaa, "rb") as f:
            f.seek(off)
            comp = f.read(min(max(cs, stock_cs), self._rel_capacity(off)))
        return bytes(lzss.decompress(comp, 0xB, 4, REL_SIZES[fname])), (off, cs)

    def _rel_section_offset(self, rel: bytes, section: str, addr: int) -> int:
        num, sec_off = struct.unpack(">II", rel[12:20])
        i = REL_SECTION_INDEX[section]
        o, s = struct.unpack(">II", rel[sec_off + i * 8:sec_off + i * 8 + 8])
        o &= ~3
        if addr + 16 > s:
            raise EditError(f"{section}+{addr:#x} is outside {REL_MODULES[section]}")
        return o + addr

    def read_descriptor(self, ref: Ref) -> bytes:
        if ref.module == "dol":
            d = self.dol.read_bytes()
            o = self._dol_offset(ref.addr)
            return d[o:o + 16]
        rel, _ = self._rel_bytes(ref.module)
        o = self._rel_section_offset(rel, ref.section, ref.addr)
        return rel[o:o + 16]

    def write_descriptor(self, ref: Ref, record: bytes) -> None:
        if ref.module == "dol":
            d = bytearray(self.dol.read_bytes())
            o = self._dol_offset(ref.addr)
            d[o:o + 16] = record
            self.dol.write_bytes(bytes(d))
            return
        self._backup_rel(ref.module)
        rel, (off, _cs) = self._rel_bytes(ref.module)
        rel = bytearray(rel)
        o = self._rel_section_offset(rel, ref.section, ref.addr)
        rel[o:o + 16] = record
        comp = lzss.compress(bytes(rel), 0xB, 4)
        capacity = self._rel_capacity(off)
        if len(comp) > capacity:
            raise EditError(f"{REL_MODULES[ref.module]} no longer fits its slot in aaaa.dat after patching "
                            f"({len(comp)} > {capacity} bytes)")
        with open(self.aaaa, "r+b") as f:
            f.seek(off)
            f.write(comp + bytes(capacity - len(comp)))
        self._update_aaaa_descriptor(ref.module, off, len(comp))

    def write_descriptors(self, writes: list[tuple["Ref", bytes]]) -> None:
        """Like write_descriptor for many records, repacking each REL once."""
        by_mod: dict[str, list] = {}
        for ref, rec in writes:
            by_mod.setdefault(ref.module, []).append((ref, rec))
        for module, items in by_mod.items():
            if module == "dol":
                d = bytearray(self.dol.read_bytes())
                for ref, rec in items:
                    o = self._dol_offset(ref.addr)
                    d[o:o + 16] = rec
                self.dol.write_bytes(bytes(d))
                continue
            self._backup_rel(module)
            rel, (off, _cs) = self._rel_bytes(module)
            rel = bytearray(rel)
            for ref, rec in items:
                o = self._rel_section_offset(rel, ref.section, ref.addr)
                rel[o:o + 16] = rec
            comp = lzss.compress(bytes(rel), 0xB, 4)
            capacity = self._rel_capacity(off)
            if len(comp) > capacity:
                raise EditError(f"{REL_MODULES[module]} no longer fits its slot in aaaa.dat after patching "
                                f"({len(comp)} > {capacity} bytes)")
            with open(self.aaaa, "r+b") as f:
                f.seek(off)
                f.write(comp + bytes(capacity - len(comp)))
            self._update_aaaa_descriptor(module, off, len(comp))

    def _backup_rel(self, module: str) -> None:
        """Keep the untouched aaaa.dat slot and DOL descriptor of a REL the first
        time it is repacked, so restoring the last edit makes both files exact."""
        rb = self.journal.setdefault("_rels", {})
        if module in rb:
            return
        off, _ = next(((off, cs) for (off, cs), n in AAAA_ENTRIES.items() if n == REL_MODULES[module]))
        cap = self._rel_capacity(off)
        with open(self.aaaa, "rb") as f:
            f.seek(off)
            (self.backup_dir / f"{module}.rel.slot").write_bytes(f.read(cap))
        va = 0x800E8AA8 + ["menus", "game", "debug"].index(module) * 16
        d = self.dol.read_bytes()
        o = self._dol_offset(va)
        rb[module] = {"offset": off, "descriptor": d[o:o + 16].hex()}

    def _maybe_unbackup_rel(self, module: str) -> None:
        """No modified entry references this REL any more: put the stock slot back."""
        rb = self.journal.get("_rels", {})
        if module not in rb:
            return
        still = any(any(r["module"] == module for r in v.get("refs", []))
                    for k, v in self.journal.items() if not k.startswith("_"))
        still = still or any(x.get("module") == module
                             for c in self.journal.get("_clones", {}).values() for x in c["copied"] + c["shared"])
        if still:
            return
        info = rb.pop(module)
        slot = self.backup_dir / f"{module}.rel.slot"
        with open(self.aaaa, "r+b") as f:
            f.seek(info["offset"])
            f.write(slot.read_bytes())
        va = 0x800E8AA8 + ["menus", "game", "debug"].index(module) * 16
        d = bytearray(self.dol.read_bytes())
        o = self._dol_offset(va)
        d[o:o + 16] = bytes.fromhex(info["descriptor"])
        self.dol.write_bytes(bytes(d))
        slot.unlink(missing_ok=True)

    def _rel_capacity(self, off: int) -> int:
        """A REL may grow into the padding up to the next entry in aaaa.dat."""
        starts = sorted(o2 for (o2, _c) in AAAA_ENTRIES)
        nxt = next((o2 for o2 in starts if o2 > off), self.aaaa.stat().st_size)
        return nxt - off

    def _update_aaaa_descriptor(self, module: str, off: int, new_cs: int) -> None:
        """The DOL table at 0x800E8AA8 holds the RELs' descriptors (menus, game, debug)."""
        va = 0x800E8AA8 + ["menus", "game", "debug"].index(module) * 16
        d = bytearray(self.dol.read_bytes())
        o = self._dol_offset(va)
        params, fs, doff, _cs = struct.unpack_from(">IIII", d, o)
        if doff != off:
            raise EditError(f"unexpected aaaa.dat descriptor for {module}.rel at {va:#x}")
        struct.pack_into(">IIII", d, o, params, fs, doff, new_cs)
        self.dol.write_bytes(bytes(d))

    def _record(self, e: Entry, ref: Ref, offset: int, disc_size: int, size: int) -> bytes:
        rel_base = 0
        if ref.module == "dol":
            for tva, (count, base) in RELATIVE_TABLES.items():
                if tva <= ref.addr < tva + count * 16:
                    rel_base = base
        params = (e.repeat_bits << 8) | e.lookback_bits if e.compressed else 0
        fs = (FLAG_COMPRESSED << 28 | size) if e.compressed else size
        return struct.pack(">IIII", params, fs, offset - rel_base, disc_size)

    # -------------------------------------------------------------- edits --
    def replace(self, e: Entry, new_data: bytes) -> dict:
        if e.archive != "ZZZZ.dat":
            raise EditError("only ZZZZ.dat entries can be replaced")
        refs = [r for r in (Ref.parse(x) for x in e.refs) if r]
        if not refs:
            raise EditError("this entry is not referenced by any descriptor, so it cannot be repointed; "
                            "a replacement must be the same size to be written in place")
        blob = lzss.compress(new_data, e.lookback_bits, e.repeat_bits) if e.compressed else bytes(new_data)
        key = str(e.id)
        entry = self.journal.get(key)
        if entry is None:
            # first edit: back up descriptors and the original bytes
            with open(self.archive, "rb") as f:
                f.seek(e.offset)
                orig = f.read(e.disc_size)
            (self.backup_dir / f"{e.id}.bin").write_bytes(orig)
            entry = {"original": {"offset": e.offset, "disc_size": e.disc_size, "size": e.size},
                     "descriptors": {str(r.__dict__): self.read_descriptor(r).hex() for r in refs},
                     "refs": [r.__dict__ for r in refs], "current": None}
            self.journal[key] = entry
        orig = entry["original"]
        span = -(-orig["disc_size"] // SECTOR) * SECTOR
        if len(blob) > span and any(r.module == "dol" and any(tva <= r.addr < tva + count * 16 for tva, (count, _b) in RELATIVE_TABLES.items()) for r in refs):
            raise EditError(f"this file lives in the ARAM chunk the game loads whole, so it cannot grow: "
                            f"the replacement is {len(blob)} bytes, the slot holds {span}")
        if len(blob) <= span:
            offset = orig["offset"]
            payload = blob + bytes(span - len(blob))
        else:
            with open(self.archive, "rb") as f:
                f.seek(0, 2)
                end = f.tell()
            offset = -(-end // SECTOR) * SECTOR
            payload = blob + bytes(-(-len(blob) // SECTOR) * SECTOR - len(blob))
        with open(self.archive, "r+b") as f:
            f.seek(offset)
            f.write(payload)
        for r in refs:
            self.write_descriptor(r, self._record(e, r, offset, len(blob), len(new_data)))
        entry["current"] = {"offset": offset, "disc_size": len(blob), "size": len(new_data)}
        self._save()
        e.offset, e.disc_size, e.size = offset, len(blob), len(new_data)
        return {"offset": offset, "disc_size": len(blob), "size": len(new_data), "in_place": offset == orig["offset"],
                "compressed": e.compressed, "descriptors": len(refs)}

    def restore(self, e: Entry) -> None:
        key = str(e.id)
        entry = self.journal.get(key)
        if not entry:
            raise EditError("nothing to restore for this entry")
        orig = entry["original"]
        data = (self.backup_dir / f"{e.id}.bin").read_bytes()
        with open(self.archive, "r+b") as f:
            f.seek(orig["offset"])
            f.write(data)
        for r in entry["refs"]:
            ref = Ref(**r)
            self.write_descriptor(ref, bytes.fromhex(entry["descriptors"][str(ref.__dict__)]))
        del self.journal[key]
        for r in entry["refs"]:
            if r["module"] != "dol":
                self._maybe_unbackup_rel(r["module"])
        self._save()
        e.offset, e.disc_size, e.size = orig["offset"], orig["disc_size"], orig["size"]

    def modified_ids(self) -> list[int]:
        return [int(k) for k in self.journal if not k.startswith("_")]
