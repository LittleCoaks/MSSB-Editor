"""Work out what the files nobody references are.

About 40% of ZZZZ.dat is never named by a descriptor in the executables. It
falls into a few blocks, each recognisable from its contents:

* 0x0F12C800-0x186A1800 (157 MB): the **animation sources**. One bank per
  character and category, with the sequence names still in them
  (`b00_wa_000`: category letter, character id, action, take). The shipped
  per-slot banks (17 per character in the sub-file table) hold the same
  animations with the names stripped; a source bank is matched to its shipped
  twin by sequence count, track count and duration, which lets the viewer
  show real names on the shipped banks. The two-digit number is the base
  roster slot (colour variants folded onto their first slot, the same 32
  values as `chars.ID_BASE_SLOT`).
* 0x0CE16800-0x0E581000 (25 MB): a **prototype library** - the same five
  categories for a placeholder rig (`f_k_01`, `p_k_01`), test packs
  (`hitomi.gpc`, `s16.gpc`, `taiki.gpc`, `koopa_skintest00.tpl`), each stored
  twice.
* 0x19A6F800-0x1A15E800 (7 MB): an **earlier copy of the character data**
  chunk that the master table addresses at 0x1A15E800 - mostly byte-identical.
* Small leftovers next to those blocks.

`annotate` fills two Entry fields: `twin` (a referenced entry with identical
content, or for a source bank the shipped bank it names) and `tag`
(`animsrc:<base slot>:<category>`, `names:<source entry>`, `proto[:<category>]`,
`mirror`, `leftover`). The catalog turns those into names and groups.
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict

from . import anim, chars
from .descriptors import Entry

SOURCE_RUN = (0x0F12C800, 0x186A1800)
PROTO_RUN = (0x0CE16800, 0x0E581000)
MIRROR_RUN = (0x19A6F800, 0x1A15E800)

# category letter of a sequence name -> what the animations are for
CATEGORIES = {"b": "batting", "r": "running", "p": "pitching", "f": "fielding", "c": "catching",
              "e": "reactions", "o": "misc"}
SEQ_RE = re.compile(r"^([a-z])(\d\d)_")
PROTO_RE = re.compile(r"^([a-z])(?:_k)?_\d+$")   # b_05, f_k_01


def _in(run: tuple[int, int], e: Entry) -> bool:
    return run[0] <= e.offset < run[1]


def _sig(bank: anim.Bank) -> tuple:
    return tuple((len(s.tracks), round(s.duration)) for s in bank.sequences)


def _is_named(bank: anim.Bank) -> bool:
    return any(not s.name.startswith("sequence ") for s in bank.sequences)


def annotate(store, entries: list[Entry], log=lambda *a: None) -> None:
    """Fill `twin` and `tag` for every ZZZZ.dat entry (see the module doc)."""
    for e in entries:
        e.twin, e.tag = -1, ""
    zz = [e for e in entries if e.archive == "ZZZZ.dat"]
    referenced = [e for e in zz if e.refs and not e.refs[0].startswith("scan:")]
    loose = [e for e in zz if e not in referenced]

    # 1. identical content -> twin
    by_hash: dict[str, Entry] = {}
    for e in referenced:
        if e.kind in ("hvqm4", "musyx", "adgc", "dtk-adpcm") or e.disc_size > 0x400000:
            continue
        try:
            by_hash.setdefault(hashlib.md5(store.data(e)).hexdigest(), e)
        except Exception:
            pass
    dups = 0
    for e in loose:
        if e.kind in ("hvqm4", "musyx", "adgc") or e.disc_size > 0x400000:
            continue
        try:
            t = by_hash.get(hashlib.md5(store.data(e)).hexdigest())
        except Exception:
            continue
        if t is not None:
            e.twin = t.id
            dups += 1
    log(f"  twins: {dups} unreferenced files duplicate a referenced one")

    # 2. animation banks: shipped (referenced, unnamed) vs sources (named)
    shipped: dict[int | None, dict[tuple, Entry]] = defaultdict(dict)
    for e in referenced:
        if e.kind != "anim":
            continue
        c = chars.classify_entry(e.refs)
        try:
            b = anim.parse_bank(store.data(e), 0)
        except Exception:
            continue
        if b and b.sequences and not _is_named(b):
            shipped[c.get("slot") if c else None][_sig(b)] = e
    all_shipped = {k: v for d in shipped.values() for k, v in d.items()}
    named = 0
    for e in loose:
        if e.kind != "anim":
            continue
        try:
            b = anim.parse_bank(store.data(e), 0)
        except Exception:
            continue
        if not b or not b.sequences:
            continue
        ids = Counter()
        cats = Counter()
        proto = 0
        for s in b.sequences:
            m = SEQ_RE.match(s.name)
            if m:
                cats[m.group(1)] += 1
                ids[int(m.group(2))] += 1
            elif PROTO_RE.match(s.name):
                cats[s.name[0]] += 1
                proto += 1
        cat = cats.most_common(1)[0][0] if cats else "o"
        if cat not in CATEGORIES:
            cat = "o"
        if proto or _in(PROTO_RUN, e):
            e.tag = f"proto:{cat}" if cats else "proto"
            continue
        if not _is_named(b):
            continue   # a plain copy of a shipped bank; twin (step 1) or mirror (step 3) covers it
        slot = ids.most_common(1)[0][0] if ids else None
        if slot is not None and slot not in chars.ID_BASE_SLOT:
            slot = None
        e.tag = f"animsrc:{slot if slot is not None else '-'}:{cat}"
        t = shipped[slot].get(_sig(b)) if slot is not None else all_shipped.get(_sig(b))
        if t is not None and e.twin < 0:
            e.twin = t.id
            if not t.tag:
                t.tag = f"names:{e.id}"
                named += 1
    log(f"  animation sources name {named} shipped banks")

    # 3. the blocks
    for e in loose:
        if e.tag:
            continue
        if _in(MIRROR_RUN, e):
            e.tag = "mirror"
        elif _in(PROTO_RUN, e):
            e.tag = "proto"
        elif e.refs and e.refs[0].startswith("scan:") or not e.refs:
            e.tag = "leftover"


def sequence_names(store, e: Entry) -> list[str] | None:
    """Names for a shipped bank's sequences, read from its source twin."""
    if not e.tag.startswith("names:"):
        return None
    try:
        src = store.get(int(e.tag.split(":")[1]))
        b = anim.parse_bank(store.data(src), 0)
    except Exception:
        return None
    return [s.name for s in b.sequences] if b else None
