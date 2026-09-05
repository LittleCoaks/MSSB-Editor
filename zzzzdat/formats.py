"""Recognise and parse the file formats found inside ZZZZ.dat entries.

Everything here was worked out from the data itself (there is no format
documentation in the decomp repo). Known shapes:

* **Section container** - header of big-endian u32 section offsets, the first
  of which is the header size (0x20, 0x40, 0x60 ...). Unused slots are zero.
  Sections are individually typed; the most useful is the texture table.
* **Texture table** - 0x20-byte records:

      u16 count (first record only, else 0)
      u16 pad
      u32 data offset (relative to the table start)
      u32 tlut offset (palette formats)
      u16 width, u16 height
      u8  flags[4]   (wrap s, wrap t, filter, ?)
      f32 LOD bias
      u16 pad, u8 mip levels, u8 GX texture format
      u16 tlut entries, u8 tlut format, u8 pad

* **HVQM4** - Nintendo's HVQM4 1.3 movie container ("HVQM4 1.3" magic).
* **DSP-ADPCM** - raw 8-byte DSP frames (header nibble byte < 0x80 on every
  8th byte); this is how the un-indexed audio region looks.
* **0x007B7960 block** - `u32 magic, u32 a, u32 count, u32 b` then `count`
  fixed-stride records. As a small container section it holds an object's
  transform floats and ends with its source file name (e.g. `stadium0.gpc`).
  The 544 standalone files of this kind (kind "anim") are large, carry no
  names, hold s16 keyframe-looking data, and are pointed at by the DOL's
  per-character tables, so they are most likely animation sets. Unverified.
* **0x005BBC61 / 0x00184300** - geometry chunks that end with the name of the
  `.tpl` texture set they use plus group names (`Group01`...).

Asset names embedded this way are collected into `FileInfo.names`; the first
`.gpc` name is the best human label for an entry.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from . import dsp, gx


@dataclass
class Texture:
    index: int
    base: int          # absolute offset of the table this texture belongs to
    data_offset: int   # relative to base
    tlut_offset: int
    width: int
    height: int
    flags: bytes
    fmt: int
    tlut_count: int
    tlut_fmt: int
    mips: int = 0
    lod_bias: float = 0.0

    @property
    def fmt_name(self) -> str:
        return gx.FORMAT_NAMES.get(self.fmt, f"fmt{self.fmt}")

    @property
    def data_size(self) -> int:
        return gx.encoded_size(self.fmt, self.width, self.height)

    @property
    def abs_data_offset(self) -> int:
        return self.base + self.data_offset

    def decode_rgba(self, data: bytes) -> bytearray:
        tlut = None
        if self.fmt in (gx.GX_TF_C4, gx.GX_TF_C8, gx.GX_TF_C14X2) and self.tlut_count:
            tlut = gx.decode_tlut(data[self.base + self.tlut_offset:], self.tlut_fmt, self.tlut_count)
        start = self.abs_data_offset
        return gx.decode(self.fmt, self.width, self.height, data[start:start + self.data_size], tlut)

    def decode_png(self, data: bytes) -> bytes:
        return gx.to_png(self.width, self.height, self.decode_rgba(data))


@dataclass
class Section:
    index: int
    offset: int
    size: int
    kind: str = "unknown"
    textures: list[Texture] = field(default_factory=list)
    magic: int = 0


def _valid_dim(v: int) -> bool:
    return 1 <= v <= 1024


def _texture_record(data: bytes, base: int, index: int) -> Texture | None:
    pos = base + index * 0x20
    if pos + 0x20 > len(data):
        return None
    count, pad, doff, toff, w, h, flags, lod, pad2, mips, fmt, tlut_n, tlut_fmt, pad3 = struct.unpack_from(">HHIIHH4sfHBBHBB", data, pos)
    if fmt not in gx.FORMAT_NAMES or not _valid_dim(w) or not _valid_dim(h) or pad or pad2 or pad3 or mips > 11:
        return None
    if base + doff + gx.encoded_size(fmt, w, h) > len(data):
        return None
    if index and count:
        return None
    return Texture(index, base, doff, toff, w, h, flags, fmt, tlut_n, tlut_fmt, mips, lod)


def parse_texture_table(data: bytes, pos: int = 0) -> list[Texture]:
    """Parse a texture table starting at `pos`; [] if it does not look like one."""
    first = _texture_record(data, pos, 0)
    if first is None:
        return []
    count = struct.unpack_from(">H", data, pos)[0]
    if count == 0 or count > 4096:
        return []
    texs = [first]
    for i in range(1, count):
        t = _texture_record(data, pos, i)
        if t is None:
            return []
        texs.append(t)
    return texs


def parse_container(data: bytes) -> list[Section] | None:
    if len(data) < 0x20:
        return None
    hdr = struct.unpack_from(">I", data, 0)[0]
    if hdr < 0x20 or hdr > 0x400 or hdr & 3 or hdr >= len(data):
        return None
    n = hdr // 4
    offs = list(struct.unpack_from(f">{n}I", data, 0))
    if offs[0] != hdr:
        return None
    used = []
    for o in offs:
        if o == 0:
            continue
        if o >= len(data) or o & 3:
            return None
        used.append(o)
    if used != sorted(used) or len(set(used)) != len(used):
        return None
    secs = []
    for i, o in enumerate(used):
        end = used[i + 1] if i + 1 < len(used) else len(data)
        s = Section(i, o, end - o)
        s.magic = struct.unpack_from(">I", data, o)[0] if o + 4 <= len(data) else 0
        s.textures = parse_texture_table(data, o)
        s.kind = "textures" if s.textures else classify_blob(data[o:end])
        secs.append(s)
    return secs


def is_hvqm4(data: bytes) -> bool:
    return data[:6] == b"HVQM4 "


def hvqm4_info(data: bytes) -> dict:
    hs, bs, blocks, vframes, aframes = struct.unpack_from(">IIIII", data, 0x10)
    usec, _, _, w, h = struct.unpack_from(">IIIHH", data, 0x24)
    audio_hz = struct.unpack_from(">I", data, 0x40)[0] if len(data) >= 0x44 else 0
    return {"version": data[:16].rstrip(b"\0").decode("ascii", "replace"), "width": w, "height": h,
            "video_frames": vframes, "audio_frames": aframes, "usec_per_frame": usec,
            "fps": round(1e6 / usec, 3) if usec else 0, "audio_hz": audio_hz, "body_size": bs}


def looks_like_dsp_adpcm(data: bytes) -> bool:
    n = min(len(data), 0x4000) // 8
    if len(data) < 0x2000 or n < 64:
        return False
    return all(data[i * 8] < 0x80 for i in range(n)) and sum(data[i * 8 + 1] for i in range(n)) > 0


# Section/file type words. 0x005BBC61 is the version word of a Nintendo
# CharPipeline (C3) GeoPalette (see roeming/MSSB-Export-Models, helper_c3.py);
# the others sit in the same containers and are presumably the matching
# actor/animation/texture palettes.
SECTION_KINDS = {0x005BBC61: "geopalette", 0x007B7960: "c3-7b7960", 0x00184300: "c3-184300",
                 0x00014300: "c3-014300"}


def classify_blob(data: bytes) -> str:
    if is_hvqm4(data):
        return "hvqm4"
    if data[:8] == b"AdGCForm":
        return "adgc"
    magic = struct.unpack_from(">I", data, 0)[0] if len(data) >= 4 else 0
    if magic in SECTION_KINDS and magic != 0x007B7960:
        return SECTION_KINDS[magic]
    if data[:4] == b"\x00\x7b\x79\x60":
        return "anim"
    if parse_texture_table(data):
        return "textures"
    if looks_like_dsp_adpcm(data):
        return "dsp-adpcm"
    return "unknown"


_NAME_RE = re.compile(rb"(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9_\-]{0,39}\.(?:gpc|tpl)(?![A-Za-z0-9_])")


def find_names(data: bytes, limit: int = 64) -> list[str]:
    """Distinct embedded asset names (*.gpc models, *.tpl texture sets), in order."""
    seen: dict[str, None] = {}
    for m in _NAME_RE.finditer(data):
        seen.setdefault(m.group().decode("ascii"), None)
        if len(seen) >= limit:
            break
    return list(seen)


@dataclass
class FileInfo:
    kind: str
    sections: list[Section] = field(default_factory=list)
    textures: list[Texture] = field(default_factory=list)
    hvqm4: dict | None = None
    names: list[str] = field(default_factory=list)
    audio: list[dict] = field(default_factory=list)  # {pos, kind, rate, channels, seconds, samples}

    @property
    def label(self) -> str:
        gpc = [n for n in self.names if n.endswith(".gpc")]
        return gpc[0] if gpc else (self.names[0] if self.names else "")

    def all_textures(self) -> list[tuple[Section | None, Texture]]:
        out = [(None, t) for t in self.textures]
        for s in self.sections:
            out += [(s, t) for t in s.textures]
        return out


def identify(data: bytes) -> FileInfo:
    if is_hvqm4(data):
        return FileInfo("hvqm4", hvqm4=hvqm4_info(data))
    texs = parse_texture_table(data)
    if texs:
        fi = FileInfo("textures", textures=texs)
    else:
        secs = parse_container(data)
        fi = FileInfo("container", sections=secs) if secs else FileInfo(classify_blob(data))
    if fi.kind != "dsp-adpcm":
        fi.names = find_names(data)
    for pos, h in dsp.find_dsp_streams(data):
        fi.audio.append({"pos": pos, "kind": "dsp-adpcm", "rate": h.sample_rate, "channels": 1,
                         "seconds": round(h.seconds, 2), "samples": h.sample_count, "loop": bool(h.loop_flag)})
    return fi


def dtk_info(size: int) -> FileInfo:
    """FileInfo for a disc .adp (DTK) stream, which has no header to parse."""
    fi = FileInfo("dtk-adpcm")
    fi.audio.append({"pos": 0, "kind": "dtk-adpcm", "rate": dsp.DTK_RATE, "channels": 2,
                     "seconds": round(dsp.dtk_seconds(size), 2), "samples": size // dsp.DTK_FRAME * 28, "loop": False})
    return fi
