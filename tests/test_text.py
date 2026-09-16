"""Text string tables: glyph codes, control words and the font renderer."""
import struct

from zzzzdat import formats, text, textrender


def _table(strings):
    body = b"".join(struct.pack(f">{len(s)}H", *s) for s in strings)
    offs, o = [], 4 + 4 * len(strings)
    for s in strings:
        offs.append(o)
        o += 2 * len(s)
    return struct.pack(">HH", len(strings), 0x131) + struct.pack(f">{len(strings)}I", *offs) + body


def enc(s):
    out = []
    for ch in s:
        if ch == " ":
            out.append(0x4002)
        elif ch == "\n":
            out.append(0x4001)
        elif "a" <= ch <= "z":
            out.append(ord(ch) - 0x61 + 0x3E)
        else:
            out.append(ord(ch) - 0x21)
    return out + [0x4000]


def test_roundtrip_and_controls():
    data = _table([enc("Hit 5 home runs!"), [0x4039, 0x4008] + enc("Mario")[:-1] + [0x4005, 0x80BD, 0x402E, 0x4043, 0x404C, 0x4000], [0x4000]])
    assert text.is_table(data)
    assert formats.identify(data).kind == "text"
    s = text.strings(data)
    assert s[0]["text"] == "Hit 5 home runs!"
    assert s[1]["text"] == "<grid font><red>Mario</colour><cell 0xbd><A><speed 20><cue 0x13>"
    assert s[1]["tokens"][0] == ["c", "grid font"]
    assert s[2]["text"] == ""
    assert text.as_text(data).splitlines()[0] == "0\tHit 5 home runs!"


def test_glyph_range():
    assert text.glyph(0x0F) == "0" and text.glyph(0x20) == "A" and text.glyph(0x3E) == "a" and text.glyph(0x57) == "z"
    assert text.glyph(0x1E) == "?" and text.glyph(0x58) is None and text.glyph(0x4002) is None


def test_not_a_table():
    assert not text.is_table(b"\x00\x05\x01\x31" + b"\x00" * 30)


def test_bank0():
    strings = [[], [0x80C1 + i for i in range(11)], [], [], [], [0x8033], [0x800F], [0x8040 + i for i in range(70)] + [0x4001, 0x8001]]
    assert text.is_bank0(strings)
    assert text.remap_table(strings) == [0x8040 + i for i in range(70)]
    assert not text.is_bank0(strings[:7])


def _font():
    # a DOL-shaped metrics blob: grid widths 11, proportional widths 20, y offsets 0/-1, the colour table
    blob = bytearray(textrender.COLOURS_OFF + 40)
    for i in range(textrender.ALT_COUNT):
        blob[i * 4:i * 4 + 4] = bytes([11, 9, 9, 11])
    for i in range(textrender.PROP_COUNT):
        blob[0x194 + i * 4:0x194 + i * 4 + 4] = bytes([20, 16, 16, 20])
        blob[0x654 + i * 4] = 0xFF   # -1 in style 0
    cols = [0, 0xFF15B100, 0xB8900000, 0xFF000000, 0x00990000, 0x0000FF00, 0x80000000, 0x33996600, 0x33339900, 0]
    blob[textrender.COLOURS_OFF:] = struct.pack(">10I", *cols)
    dol = b"\0" * 100 + bytes(blob) + b"\0" * 100
    m = textrender.Metrics.find(dol)
    assert m and m.colours[3] == 0xFF000000 and m.widths[0][0] == 20 and m.yoffs[0][0] == -1
    # pages: opaque white; icons: 28 x 20 blue
    def solid(w, h, rgba):
        return textrender.Image(w, h, bytearray(bytes(rgba) * (w * h)))
    pages = [solid(1024, 132, (255, 255, 255, 255)), solid(1024, 108, (255, 255, 255, 255))] * 2
    icons = [solid(28, 20, (0, 0, 255, 255))] * 9
    return textrender.Font(pages, icons, m, [0x8040 + i for i in range(0x60)], [0x8010 + i for i in range(11)], 0x33)


def test_render_layout_and_colour():
    font = _font()
    codes = [0x4039] + enc("Hi")[:-1] + [0x4002, 0x4008, 0x3E, 0x4001, 0x402E, 0x4003]
    ops, w, h = textrender.layout(font, codes)
    assert h == 44                        # two lines of 22 px
    assert w == 28 + 22                   # line two: the icon and a wide space; line one is 4 x 11
    assert ops[2][-1] == (255, 0, 0)      # 'a' drawn red
    assert ops[3][0] == "i" and ops[3][3] == 1   # the A button on line two
    img = textrender.render(font, codes)
    assert (img.w, img.h) == (50 + 4, 44 + 6)
    # the red 'a' landed at x = 33 + 2 (pad), y = 2 on the first line
    i = (2 * img.w + 35) * 4
    assert bytes(img.rgba[i:i + 4]) == b"\xff\x00\x00\xff"
    assert img.png()[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_proportional_and_style():
    font = _font()
    ops, w, h = textrender.layout(font, [0x3E, 0x8035], style=1)
    assert h == 18 and w == 32 and [o[6] for o in ops] == [16, 16]   # small-style proportional widths
    assert ops[1][4:6] == (0x35 % 46 * 18, 0x35 // 46 * 18)          # a direct cell number
