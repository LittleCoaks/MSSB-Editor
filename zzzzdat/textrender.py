"""Draw text strings the way the game draws them.

What the text engine needs, and where the editor finds it:

* **Font pages** -- the four textures of the pack right before bank 0 in the
  DOL's screen table (entry 78 in the US index, once labelled "Title screen
  text"): style 0 and 3 are the large font, 1024 x 132 = six rows of 22-px
  cells; styles 1 and 2 the small one, six rows of 18-px cells. Row 0 of
  each page is the fixed-grid ASCII font at 11 px (9 small) per code; the
  proportional font's cells are 22 px (18) wide, 46 to a row.
* **Controller icons** -- the nine-texture pack right after bank 0.
* **Metrics** -- `lbl_800E8F60` in main.dol (src/text/text_draw.c's
  FontMetricsTables): per-glyph widths and y offsets for both fonts in four
  styles, then the ten colours the colour words select. Found in any build
  by the colour table's bytes.
* **Remap and digits** -- bank 0's string 7 maps a grid-font word to a cell
  of the proportional font; string 1 gives the digit cells; string 5 the
  first cell the width table covers.

`render` walks a string exactly as DrawText does (spacing, colours, font
switches, icons, inserted values drawn as 0) and composes the glyph sprites
into an RGBA image, tinted by the colour in force, on a transparent ground.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from . import gx

ALT_COUNT = 0x65      # grid-font metric rows
PROP_COUNT = 0xCB     # proportional-font metric rows
COLOURS_OFF = 0x980   # inside the metrics object
COLOUR_SIG = bytes.fromhex("ff15b100b8900000ff00000000990000")  # colours 1..4, the same in every build
ICON_W, ICON_H = 28, 20
LARGE, SMALL = 22, 18


@dataclass
class Image:
    w: int
    h: int
    rgba: bytearray = field(default_factory=bytearray)

    def png(self) -> bytes:
        return gx.to_png(self.w, self.h, bytes(self.rgba))


@dataclass
class Metrics:
    alt_widths: list[list[int]]   # [code][style]
    widths: list[list[int]]       # [cell - base - 1][style]
    alt_yoffs: list[list[int]]
    yoffs: list[list[int]]
    colours: list[int]            # RGBA words, [0] unused

    @staticmethod
    def parse(blob: bytes) -> "Metrics":
        def table(off: int, n: int, signed: bool = False) -> list[list[int]]:
            rows = []
            for i in range(n):
                r = list(blob[off + i * 4:off + i * 4 + 4])
                if signed:
                    r = [v - 256 if v > 127 else v for v in r]
                rows.append(r)
            return rows
        aw = table(0, ALT_COUNT)
        w = table(0x194, PROP_COUNT)
        ay = table(0x4C0, ALT_COUNT, signed=True)
        y = table(0x654, PROP_COUNT, signed=True)
        cols = list(struct.unpack_from(">10I", blob, COLOURS_OFF))
        return Metrics(aw, w, ay, y, cols)

    @staticmethod
    def find(dol: bytes) -> "Metrics | None":
        i = dol.find(COLOUR_SIG)
        if i < 0:
            return None
        start = i - 4 - COLOURS_OFF   # colour 0 precedes the signature
        if start < 0:
            return None
        return Metrics.parse(dol[start:start + COLOURS_OFF + 40])

    def colour_css(self) -> list[str]:
        return [f"#{c >> 8:06x}" for c in self.colours]


@dataclass
class Font:
    pages: list[Image]        # by style 0..3
    icons: list[Image]        # 9 controller icons
    metrics: Metrics
    remap: list[int]          # grid-font word -> cell, from bank 0 string 7
    digits: list[int]         # cell numbers for '0'..'9' and the minus sign
    base: int                 # first cell covered by the proportional metrics

    def style_size(self, style: int) -> tuple[int, int]:
        """(cell width, space width) for a style, as DrawText sets them."""
        return (SMALL, 9) if style in (1, 2) else (LARGE, 11)

    def prop_glyph(self, cell: int, style: int) -> tuple[int, int, int, int]:
        """(page x, page y, width, y offset) of a proportional-font cell."""
        w, _ = self.style_size(style)
        cell %= 0x844
        row2 = cell - self.base - 1
        gw = self.metrics.widths[row2][style] if 0 <= row2 < PROP_COUNT else w
        yo = self.metrics.yoffs[row2][style] if 0 <= row2 < PROP_COUNT else 0
        return (cell % 46) * w, (cell // 46) * w, gw, yo

    def grid_glyph(self, code: int, style: int) -> tuple[int, int, int, int]:
        w, sp = self.style_size(style)
        gw = self.metrics.alt_widths[code][style] if code < ALT_COUNT else sp
        yo = self.metrics.alt_yoffs[code][style] if code < ALT_COUNT else 0
        return (code % 0x5C) * sp, (code // 0x5C) * w, gw, yo


def _blit(dst: Image, src: Image, sx: int, sy: int, w: int, h: int, dx: int, dy: int, tint: tuple[int, int, int]) -> None:
    """Copy a w x h sprite from src (sx, sy) to dst (dx, dy), multiplying its
    colour by the tint and alpha-compositing over what is there."""
    tr, tg, tb = tint
    for yy in range(h):
        y0 = sy + yy
        y1 = dy + yy
        if not (0 <= y0 < src.h and 0 <= y1 < dst.h):
            continue
        for xx in range(w):
            x0 = sx + xx
            x1 = dx + xx
            if not (0 <= x0 < src.w and 0 <= x1 < dst.w):
                continue
            si = (y0 * src.w + x0) * 4
            a = src.rgba[si + 3]
            if not a:
                continue
            r = src.rgba[si] * tr // 255
            g = src.rgba[si + 1] * tg // 255
            b = src.rgba[si + 2] * tb // 255
            di = (y1 * dst.w + x1) * 4
            da = dst.rgba[di + 3]
            if da == 0 or a == 255:
                dst.rgba[di:di + 4] = bytes((r, g, b, a))
            else:
                k = da * (255 - a) // 255
                oa = a + k
                dst.rgba[di] = (r * a + dst.rgba[di] * k) // oa
                dst.rgba[di + 1] = (g * a + dst.rgba[di + 1] * k) // oa
                dst.rgba[di + 2] = (b * a + dst.rgba[di + 2] * k) // oa
                dst.rgba[di + 3] = oa


def layout(font: Font, codes: list[int], style: int = 0, colour: int = 0xFFFFFFFF) -> tuple[list[tuple], int, int]:
    """Walk a string as DrawText does. Returns the draw list [(kind, x, y, ...)]
    and the image size. kind "g": (page style, sx, sy, w, h, tint);
    "i": (icon index)."""
    w, sp = font.style_size(style)
    h = w
    cur_style = style
    grid = False
    x = y = 0
    ops: list[tuple] = []
    tint = ((colour >> 24) & 255, (colour >> 16) & 255, (colour >> 8) & 255)
    maxx = 0
    lines = 1
    for c in codes:
        if c & 0x4000:
            code = c & 0x3FFF
            if code == 0:
                break
            if code == 1:
                y += h
                x = 0
                lines += 1
            elif code == 2:
                x += sp
            elif code == 3:
                x += w
            elif 5 <= code <= 0xE:
                n = code - 5
                cw = colour if n == 0 else font.metrics.colours[n] | (colour & 0xFF)
                tint = ((cw >> 24) & 255, (cw >> 16) & 255, (cw >> 8) & 255)
            elif 0xF <= code <= 0x12:
                # an inserted value; the block would supply it, draw a 0
                sx, sy, gw, yo = font.prop_glyph(font.digits[0], cur_style)
                ops.append(("g", x, y + yo, cur_style, sx, sy, w, h, tint))
                x += w
            elif 0x2D <= code <= 0x35:
                ops.append(("i", x, y - 1, code - 0x2D))
                x += ICON_W
            elif code == 0x37:
                cur_style = 3
                w = h = LARGE
                sp = 11
            elif code == 0x38:
                cur_style = style
                w, sp = font.style_size(style)
                h = w
            elif code == 0x39:
                grid = True
            elif code == 0x3A:
                grid = False
        else:
            if grid:
                sx, sy, gw, yo = font.grid_glyph(c & 0x7FFF, cur_style)
            else:
                cell = c & 0x7FFF if c & 0x8000 else (font.remap[c] & 0x7FFF if c < len(font.remap) else 0)
                sx, sy, gw, yo = font.prop_glyph(cell, cur_style)
            ops.append(("g", x, y + yo, cur_style, sx, sy, gw, h, tint))
            x += gw
        maxx = max(maxx, x)
    return ops, maxx, lines * (LARGE if style in (0, 3) else SMALL)


def render(font: Font, codes: list[int], style: int = 0, colour: int = 0xFFFFFFFF, pad: int = 2) -> Image:
    ops, w, h = layout(font, codes, style, colour)
    img = Image(max(1, w + pad * 2), max(1, h + pad * 2 + 2))
    img.rgba = bytearray(img.w * img.h * 4)
    for op in ops:
        if op[0] == "g":
            _, x, y, st, sx, sy, gw, gh, tint = op
            _blit(img, font.pages[st], sx, sy, gw, gh, x + pad, y + pad, tint)
        else:
            _, x, y, n = op
            ic = font.icons[n]
            _blit(img, ic, 0, 0, ic.w, ic.h, x + pad, y + pad + 1, (255, 255, 255))
    return img
