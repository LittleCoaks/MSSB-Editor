"""Character cloning: make one playable slot use another character's files.

After DrSeil's recipe (mssb-dtk, feat/character-cloning-texture-decoupling),
which was verified in-game with no code patches. A slot is defined by five
tables in main.dol (see chars.py):

* the 19 sub-file descriptors (model, equipment, 17 animation banks), streamed
  from ZZZZ.dat on demand;
* the master descriptors, offsets inside the 4.4 MB chunk that is copied to
  ARAM at boot: the standalone body model, 7 sub-items (hands, bats, grips)
  and the skeleton rig;
* the glove attachment index (u16 per slot, selects the wrist bones).

Cloning source S onto target T rewrites T's descriptors to describe S's data.
Two flavours:

* **share** - T's descriptors simply point at S's bytes; nothing is written to
  the archive. Both slots are then one set of files, so editing a texture on
  one changes the other.
* **copy** (default) - the 19 sub-files are duplicated at the end of ZZZZ.dat
  so T can be retextured independently. The ARAM chunk is packed tightly and
  is loaded as a whole, so the body model and rig are copied *in place* over
  T's old ones only when the compressed source fits T's span; otherwise they
  are shared. The 7 sub-items are always shared (as in DrSeil's tool).

Everything touched is backed up in the editor journal under "_clones" so
`restore_character` puts the DOL, the glove table and any in-place ARAM
bytes back exactly. Appended copies stay behind (harmless, like appended
replacements). Bat-swing style lives in RAM the game fills at runtime and is
not part of the tables, so it is left alone.
"""
from __future__ import annotations

import struct

from . import chars
from .edit import SECTOR, EditError, Editor

REC = struct.Struct(">IIII")


def _ref(va: int) -> str:
    """The index's reference string for a descriptor in one of the two tables."""
    if chars.SUBFILES_VA <= va < chars.SUBFILES_VA + chars.SLOTS * chars.TRACKS * 16:
        base, sym = chars.SUBFILES_VA, "lbl_800F1D78"
    else:
        base, sym = chars.MASTER_VA, "lbl_800EFD38"
    off = va - base
    return f"dol:.data:{va:#x} {sym}" + (f"+{off:#x}" if off else "")


def slot_vas(slot: int) -> dict:
    """Descriptor addresses that define a slot."""
    return {"subfiles": [chars.SUBFILES_VA + (slot * chars.TRACKS + t) * 16 for t in range(chars.TRACKS)],
            "body": chars.MASTER_VA + slot * 16,
            "items": [chars.MASTER_VA + (54 + slot * 7 + k) * 16 for k in range(7)],
            "rig": chars.MASTER_VA + (432 + slot) * 16,
            "glove": chars.GLOVE_VA + slot * 2}


class Cloner:
    def __init__(self, editor: Editor):
        self.ed = editor
        self.dol = bytearray(editor.dol.read_bytes())

    # -------------------------------------------------------------- helpers --
    def _rec(self, va: int) -> tuple[int, int, int, int]:
        return REC.unpack_from(self.dol, self.ed._dol_offset(va))

    def _put(self, va: int, rec: bytes) -> None:
        o = self.ed._dol_offset(va)
        self.dol[o:o + 16] = rec

    def _u16(self, va: int) -> int:
        return struct.unpack_from(">H", self.dol, self.ed._dol_offset(va))[0]

    def _aram_span(self, va: int) -> int:
        """Bytes available to a master entry before the next one starts."""
        _p, _fs, off, cs = self._rec(va)
        starts = sorted({self._rec(chars.MASTER_VA + i * 16)[2] for i in range(chars.MASTER_ENTRIES)})
        nxt = next((s for s in starts if s > off), None)
        return (nxt - off) if nxt is not None else cs

    def _append(self, blob: bytes) -> int:
        with open(self.ed.archive, "r+b") as f:
            f.seek(0, 2)
            end = f.tell()
            off = -(-end // SECTOR) * SECTOR
            f.seek(off)
            f.write(blob + bytes(-(-len(blob) // SECTOR) * SECTOR - len(blob)))
        return off

    def _read(self, off: int, size: int) -> bytes:
        with open(self.ed.archive, "rb") as f:
            f.seek(off)
            return f.read(size)

    def clones(self) -> dict:
        return self.ed.journal.get("_clones", {})

    # ---------------------------------------------------------------- clone --
    def clone(self, source: int, target: int, copy: bool = True) -> dict:
        if not (0 <= source < chars.SLOTS and 0 <= target < chars.SLOTS):
            raise EditError("slots are 0..53")
        if source == target:
            raise EditError("source and target are the same slot")
        if str(target) in self.clones():
            raise EditError(f"slot {target} ({chars.SLOT_NAMES[target]}) is already a clone; restore it first")
        s, t = slot_vas(source), slot_vas(target)
        rec = {"source": source, "copy": copy, "backup": {}, "glove": f"{self._u16(t['glove']):04x}",
               "copied": [], "shared": [], "inplace": []}
        for va in t["subfiles"] + [t["body"], t["rig"]] + t["items"]:
            rec["backup"][f"{va:#x}"] = REC.pack(*self._rec(va)).hex()
        # 19 sub-files
        for sva, tva in zip(s["subfiles"], t["subfiles"]):
            p, fs, off, cs = self._rec(sva)
            if copy:
                new_off = self._append(self._read(off, cs))
                self._put(tva, REC.pack(p, fs, new_off, cs))
                rec["copied"].append({"va": f"{tva:#x}", "src": off, "offset": new_off, "disc_size": cs, "size": fs & 0x0FFFFFFF})
            else:
                self._put(tva, REC.pack(p, fs, off, cs))
                rec["shared"].append({"va": f"{tva:#x}", "src": off})
        # body model and rig in the ARAM chunk
        aram = chars.ARAM_CHUNK
        for key in ("body", "rig"):
            sva, tva = s[key], t[key]
            p, fs, off, cs = self._rec(sva)
            _tp, _tfs, toff, tcs = self._rec(tva)
            if copy and cs <= self._aram_span(tva):
                old = self._read(aram + toff, self._aram_span(tva))
                bak = self.ed.backup_dir / f"clone_{target}_{key}.bin"
                bak.write_bytes(old)
                blob = self._read(aram + off, cs)
                with open(self.ed.archive, "r+b") as f:
                    f.seek(aram + toff)
                    f.write(blob + bytes(len(old) - len(blob)))
                self._put(tva, REC.pack(p, fs, toff, cs))
                rec["inplace"].append({"va": f"{tva:#x}", "src": aram + off, "offset": aram + toff, "disc_size": cs,
                                       "size": fs & 0x0FFFFFFF, "backup": bak.name, "span": len(old)})
            else:
                self._put(tva, REC.pack(p, fs, off, cs))
                rec["shared"].append({"va": f"{tva:#x}", "src": aram + off})
        for sva, tva in zip(s["items"], t["items"]):
            p, fs, off, cs = self._rec(sva)
            self._put(tva, REC.pack(p, fs, off, cs))
            rec["shared"].append({"va": f"{tva:#x}", "src": aram + off})
        # glove attachment
        g = self._u16(s["glove"])
        struct.pack_into(">H", self.dol, self.ed._dol_offset(t["glove"]), g)
        self.ed.dol.write_bytes(bytes(self.dol))
        self.ed.journal.setdefault("_clones", {})[str(target)] = rec
        self.ed._save()
        return {"source": source, "target": target, "copy": copy, "copied": len(rec["copied"]),
                "inplace": [x["va"] for x in rec["inplace"]], "shared": len(rec["shared"]),
                "appended_bytes": sum(-(-c["disc_size"] // SECTOR) * SECTOR for c in rec["copied"])}

    def restore(self, target: int) -> None:
        rec = self.clones().get(str(target))
        if not rec:
            raise EditError(f"slot {target} is not a clone")
        for va, hx in rec["backup"].items():
            self._put(int(va, 16), bytes.fromhex(hx))
        struct.pack_into(">H", self.dol, self.ed._dol_offset(chars.GLOVE_VA + target * 2), int(rec["glove"], 16))
        for x in rec["inplace"]:
            bak = self.ed.backup_dir / x["backup"]
            with open(self.ed.archive, "r+b") as f:
                f.seek(x["offset"])
                f.write(bak.read_bytes())
            bak.unlink(missing_ok=True)
        self.ed.dol.write_bytes(bytes(self.dol))
        del self.ed.journal["_clones"][str(target)]
        self.ed._save()


def slot_table(editor: Editor | None) -> list[dict]:
    """One row per slot for the UI: name and clone state."""
    clones = editor.journal.get("_clones", {}) if editor else {}
    out = []
    for i, name in enumerate(chars.SLOT_NAMES):
        c = clones.get(str(i))
        out.append({"slot": i, "name": name, "clone_of": c["source"] if c else None,
                    "clone_of_name": chars.SLOT_NAMES[c["source"]] if c else None,
                    "copy": c["copy"] if c else None,
                    "inplace": len(c["inplace"]) if c else 0})
    return out
