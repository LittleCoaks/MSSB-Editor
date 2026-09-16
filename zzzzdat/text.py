"""The game's text string tables.

menus.rel, game.rel and main.dol point at six ZZZZ.dat files of this shape:

    u16 count, u16 version (0x131), u32 offset[count], then the strings

Each string is a run of big-endian u16 words ended by 0x4000. The decomp's
text engine (src/text/text_draw.c, DrawText) reads them like this:

* a word with bit 14 set is a control word, `code = word & 0x3FFF`:

      0     end of string              1     line break
      2     space (11 px, 9 small)     3     wide space (22 px, 18 small)
      5     colour back to the block's own
      6-E   colour 1..9 from the DOL's table (pink, gold, red, green, blue,
            dark red, teal, indigo, black)
      F-12  splice in the block's inserted value 1..4 as decimal digits
      19-1C, 23-26  splice in a bank-0 string chosen by the block
      2D-35 a controller icon (stick, A, B, X, Y, R, L, Z, note), 28 px
      37    switch to the large font (style 3)   38  back to the block's style
      39    fixed-grid font on                   3A  proportional font
      42-4A typewriter speed 10..90 frames per letter
      4B-72 challenge-mode sound cue (fn_80062890(code - 0x39))

* any other word is a glyph. With the grid font on (which nearly every
  string switches on first) the word indexes an 11-px grid of ASCII order,
  so `code = ASCII - 0x21`: '!' is 0, digits start at 0x0F, 'A' at 0x20 and
  'a' at 0x3E ('_' and '`' have no glyph). With the proportional font on, a
  word below 0x8000 goes through the remap table (bank 0's string 7) and a
  word at 0x8000 and above is a cell number on the 22-px page directly:
  `row = cell // 46, col = cell % 46`.

`textrender.py` draws strings with the real font pages and metrics; this
module only decodes them to readable text.
"""
from __future__ import annotations

import struct

VERSIONS = (0x131, 0x132)   # the second header word on the US disc; other builds differ (see is_table)

COLOURS = ["", "pink", "gold", "red", "green", "blue", "dark red", "teal", "indigo", "black"]
ICONS = ["stick", "A", "B", "X", "Y", "R", "L", "Z", "note"]

_CONTROL = {0x00: "end", 0x01: "\n", 0x02: " ", 0x03: "  ", 0x05: "/colour",
            0x37: "large", 0x38: "/large", 0x39: "grid font", 0x3A: "prop font"}
for _i, _c in enumerate(COLOURS[1:], 1):
    _CONTROL[5 + _i] = _c
for _i in range(4):
    _CONTROL[0x0F + _i] = f"value {_i + 1}"
    _CONTROL[0x19 + _i] = f"string {_i + 1}"
    _CONTROL[0x23 + _i] = f"string {_i + 5}"
for _i, _c in enumerate(ICONS):
    _CONTROL[0x2D + _i] = _c
for _i in range(9):
    _CONTROL[0x42 + _i] = f"speed {(_i + 1) * 10}"
for _i in range(0x4B, 0x73):
    _CONTROL[_i] = f"cue {_i - 0x39:#x}"


def control_name(word: int) -> str | None:
    """The name of a control word (bit 14 set), or None for a glyph."""
    if not word & 0x4000:
        return None
    return _CONTROL.get(word & 0x3FFF, f"{word:04x}")


def glyph(code: int) -> str | None:
    """The character a grid-font code stands for, or None for control words
    and codes outside the ASCII range."""
    if code & 0x4000:
        return None
    if code <= 0x3D:
        return chr(0x21 + code)
    if 0x3E <= code <= 0x57:
        return chr(0x61 + code - 0x3E)
    return None


def is_table(data: bytes) -> bool:
    if len(data) < 16:
        return False
    # the second word is not a version: it differs per build and per table
    # (0x131/0x132 US, 0x10d/0x10e EU, 0x1c4 JP, 0x1d8 and 0x2ed.. demos), so
    # the table is recognised by its shape: an offset table that starts right
    # after itself, ascends, and whose strings each end in the end word
    n, _word = struct.unpack_from(">HH", data, 0)
    if n == 0 or n > 4096 or 4 + n * 4 + 2 > len(data):
        return False
    offs = struct.unpack_from(f">{n}I", data, 4)
    if offs[0] != 4 + n * 4 or not all(a < b <= len(data) - 2 for a, b in zip(offs, offs[1:])):
        return False
    return all((b - a) % 2 == 0 for a, b in zip(offs, offs[1:])) and len(data) - offs[-1] >= 2


def codes_of(data: bytes) -> list[list[int]]:
    """Every string of the table as its list of u16 words (end word dropped)."""
    n = struct.unpack_from(">H", data, 0)[0]
    offs = struct.unpack_from(f">{n}I", data, 4)
    out = []
    for i, o in enumerate(offs):
        end = offs[i + 1] if i + 1 < n else len(data)
        codes = list(struct.unpack_from(f">{(end - o) // 2}H", data, o))
        if 0x4000 in codes:
            codes = codes[:codes.index(0x4000)]
        out.append(codes)
    return out


def is_bank0(strings: list[list[int]]) -> bool:
    """Bank 0 is the table the text engine reads its own data from: string 1
    holds the digit glyphs, string 5 the first metrics cell and string 7 the
    glyph remap table (all cell numbers, 0x8000 and above)."""
    if len(strings) < 8:
        return False
    return (len(strings[5]) == 1 and strings[5][0] >= 0x8000 and len(strings[7]) > 60
            and all(c >= 0x8000 or c == 0x4001 for c in strings[7]) and len(strings[1]) == 11)


def remap_table(strings: list[list[int]]) -> list[int]:
    """Bank 0's glyph remap table: string 7 up to its first line-break word,
    which is where initTextRendering stops copying."""
    s = strings[7]
    return s[:s.index(0x4001)] if 0x4001 in s else s


def tokens(codes: list[int]) -> list[tuple[str, str]]:
    """(kind, text) pairs: "t" text, "c" a control word by name, "g" a glyph
    given as a font cell (0x80xx), "?" a code nothing explains."""
    out: list[tuple[str, str]] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            out.append(("t", buf))
            buf = ""

    for c in codes:
        ch = glyph(c)
        if c & 0x4000:
            name = control_name(c)
            if name in ("\n", " ", "  "):
                buf += name
            else:
                flush()
                out.append(("c", name))
        elif ch is not None:
            buf += ch
        elif c & 0x8000:
            flush()
            out.append(("g", f"cell {c & 0x7FFF:#x}"))
        else:
            flush()
            out.append(("?", f"{c:04x}"))
    flush()
    return out


def plain(codes: list[int]) -> str:
    """The readable text alone: glyphs, spaces and line breaks; control words
    in angle brackets so nothing is silently lost."""
    return "".join(t if k == "t" else f"<{t}>" for k, t in tokens(codes))


def strings(data: bytes) -> list[dict]:
    return [{"n": i, "text": plain(c), "tokens": [list(t) for t in tokens(c)], "codes": len(c)}
            for i, c in enumerate(codes_of(data))]


def as_text(data: bytes) -> str:
    """The table as numbered lines for a .txt export (line breaks shown as |)."""
    return "".join(f"{i}\t{plain(c).replace(chr(10), '|')}\n" for i, c in enumerate(codes_of(data)))
