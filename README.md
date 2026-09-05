# MSSB Asset Viewer

Browse, view and extract the assets packed inside `ZZZZ.dat`, the 450 MB
archive that holds nearly all of Mario Superstar Baseball's (GYQE01) data.
Pure Python 3.10+, no third-party packages.

The archive has **no table of contents**. Every asset is described by a
16-byte descriptor baked into `main.dol` or one of the RELs, and this tool
finds those descriptors, verifies them against the archive, and builds the
index the game never shipped. See [Format notes](#format-notes) below.

## Setup

The viewer reads the disc files and symbol tables from the decomp repo. By
default it expects that repo to be a sibling folder named `MSSB Decomp`:

```
E:\Project Rio\
  MSSB Decomp\        orig/GYQE01/{sys/main.dol, files/*.rel, Mario Superstar Baseball.iso}
  MSSB Asset Viewer\  this repo
```

To point somewhere else, set `MSSB_DECOMP=<path>` or create `decomp_path.txt`
in this folder containing the path (absolute, or relative to this folder).

`ZZZZ.dat` itself is read either from `orig/GYQE01/files/ZZZZ.dat` if you have
extracted it, or straight out of the ISO in `orig/GYQE01/` (the FST is parsed
to find it, so no extraction is needed).

## Usage

```bash
cd "MSSB Asset Viewer"
python -m zzzzdat serve            # web UI at http://127.0.0.1:8420/
python -m zzzzdat list             # all entries
python -m zzzzdat list --kind textures --module menus
python -m zzzzdat info 8           # sections, textures, references
python -m zzzzdat hexdump 8 --offset 0x48f40 --length 0x80
python -m zzzzdat extract 8 --png  # -> extracted/0008_06cfd000_dol_StadiumFiles.bin (+ PNGs)
python -m zzzzdat extract-all --png
python -m zzzzdat textures 8       # only the PNGs
python -m zzzzdat layout           # coverage map of the archive
python -m zzzzdat index            # rebuild index/GYQE01.json (~40 s)
```

Extracted files land in `extracted/` (git-ignored). Names are
`<id>_<archive offset>_<embedded name>_<module>_<symbol>.<ext>` so an entry can
always be traced back to the code that loads it. The embedded name (e.g.
`stadium0`, `packun`, `taru_clash`) comes from `.gpc`/`.tpl` strings the game
left inside the files; about half the entries carry one.

The web UI lists every entry with filters and sorting, and shows per entry:
the descriptor, which executables reference it, the container's sections,
every decoded texture (click for full size), a paged hex viewer, and buttons
to download or extract (with PNGs) into `extracted/`.

## What is indexed

`index/GYQE01.json` currently holds 1226 entries covering 255 MB of the
450 MB archive. What the rest is:

| Region | Size | Contents |
| --- | --- | --- |
| 0xF12C01C-0x186A1800 | 157 MB | High-entropy data with 32-bit structure; not referenced by any static descriptor. Probably loaded through descriptors computed at run time (not yet traced). |
| 0xCE16124-0xE581000 | 25 MB | Same as above. |
| 0x19A6F5BC-0x1A15E800 | 7 MB | Same as above. |
| 0x8F2E570-0x9438800 | 5 MB | Raw DSP-ADPCM audio (every 8th byte is a frame header). |

Index entries are classified by content:

| kind | count | notes |
| --- | --- | --- |
| `container` | 571 | Table of u32 section offsets; sections hold textures, animation banks, models, etc. |
| `anim` | 544 | Files starting with `00 7B 79 60`: large record tables pointed at by the per-character tables, probably animation sets (unverified) |
| `textures` | 19 | A bare texture table |
| `hvqm4` | 3 | Nintendo HVQM4 1.3 movies (intro 82 MB, 23 MB, 3 MB) |
| `dsp-adpcm` | 14 | Raw DSP-ADPCM sample data |
| `rel` | 3 | `menus.rel`, `game.rel`, `debug.rel` in `aaaa.dat` (listed for completeness) |
| `unknown` | 72 | |

About 9,300 textures are decodable across all entries.

## Format notes

### Entry descriptor (in main.dol / *.rel)

```
u16 pad            always 0
u8  repeat_bits    LZSS length field width   (0 when stored)
u8  lookback_bits  LZSS distance field width (0 when stored)
u32 flags_size     bits 28..31: 4 = compressed, 0 = stored;  bits 0..27: decompressed size
u32 offset         byte offset in ZZZZ.dat, always 0x800-aligned
u32 disc_size      bytes to read from the archive
```

Descriptors are passed to `ARAMTransfer` (`0x800A70DC`). The three entries at
`0x800E8AA8` describe the RELs inside `aaaa.dat`; every other one is ZZZZ.dat.
Movies are streamed through `MovStreamThread` with the same descriptor shape.

### LZSS

Big-endian 32-bit words, fields pulled from the low end of a bit buffer.
`1` + 8 bits = literal; `0` + `lookback_bits` distance + `repeat_bits` length
= copy `length + 2` bytes from `out[-1 - distance]`. When a field straddles a
word boundary the leftover bits form the *high* part of the value. This is the
same scheme as `decompress.py` in the decomp repo; `zzzzdat/lzss.py` is a
faster, behaviour-identical rewrite. Two parameter sets occur: `0x040B`
(R=4, L=11) and `0x050E` (R=5, L=14).

### Section container

Header of u32 offsets; the first is the header size (0x20/0x40/0x60/...), unused
slots are 0. Each section starts with a 32-bit type word; observed values include
`0x007B7960` (record table; as a small section it ends with the object's `name.gpc`), `0x005BBC61` and
`0x00184300` (geometry chunks, end with the `name.tpl` they texture from plus
`GroupNN` strings), and texture tables whose first halfword is the texture
count.

### Texture table

0x20-byte records, data offsets relative to the table start:

```
u16 count (record 0 only)   u16 pad
u32 data offset             u32 TLUT offset
u16 width  u16 height       u8 flags[4] (wrap S/T, filter, ?)
f32 LOD bias                u16 pad  u8 mip levels  u8 GX format
u16 TLUT entries            u8 TLUT format  u8 pad
```

All GX formats (I4, I8, IA4, IA8, RGB565, RGB5A3, RGBA8, C4, C8, C14X2, CMPR)
are decoded by `zzzzdat/gx.py`.

## Layout

```
zzzzdat/
  disc.py         find ZZZZ.dat (file or inside the ISO), FST parsing, decomp-repo path
  lzss.py         decompressor
  descriptors.py  scan executables for descriptors, verify, build/load the index
  formats.py      identify contents: container / textures / HVQM4 / ADPCM / anim bank
  gx.py           GX texture decoding + PNG writer
  store.py        index + archive + cache + extraction
  cli.py          command line
  server.py       local HTTP API
  ui/index.html   the browser UI
index/GYQE01.json the generated index (checked in; rebuild with `index`)
extracted/        output folder (ignored)
```
