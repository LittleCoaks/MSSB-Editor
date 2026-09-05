# MSSB Asset Viewer

Browse, view and extract the assets packed inside `ZZZZ.dat`, the 450 MB
archive that holds nearly all of Mario Superstar Baseball's (GYQE01) data.
Pure Python 3.10+, no third-party packages.

The archive has **no table of contents**. Most assets are described by a
16-byte descriptor baked into `main.dol` or one of the RELs; this tool finds
those descriptors, verifies them against the archive, then fills the remaining
gaps with two scans borrowed from roeming's
[MssbAssetDecompressor](https://github.com/roeming/MssbAssetDecompressor)
(`AdGCForm` sound banks and a brute-force LZSS probe) and builds the index the
game never shipped. Community file names come from that repo and from
[MSSB-Export-Models](https://github.com/roeming/MSSB-Export-Models), which
also documents the C3 model format and can export character models to OBJ.
See [Format notes](#format-notes) below.

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
python -m zzzzdat wav 10005        # decode audio to WAV (disc music, or DSP streams inside an entry)
python -m zzzzdat extract 89 --wav
python -m zzzzdat model 893 --format both   # glTF (.glb) and OBJ+MTL+PNG of "First Found Mario"
python -m zzzzdat extract-all --model glb
python -m zzzzdat layout           # coverage map of the archive
python -m zzzzdat index            # rebuild index/GYQE01.json (~3 min; --no-scan for ~40 s)
```

Extracted files land in `extracted/` (git-ignored). Names are
`<id>_<archive offset>_<embedded name>_<module>_<symbol>.<ext>` so an entry can
always be traced back to the code that loads it. The embedded name (e.g.
`stadium0`, `packun`, `taru_clash`) comes from `.gpc`/`.tpl` strings the game
left inside the files; about half the entries carry one.

The web UI lists every entry with filters and sorting, and shows per entry:
the descriptor, which executables reference it, the container's sections,
every decoded texture (click for full size), a model tab with a textured 3D
viewer (three.js, orbit/zoom/pan, wireframe), an audio tab with an in-page
player for each stream, a paged hex viewer, and buttons to download or extract
(with PNGs / WAVs / models) into `extracted/`.

## Models

`zzzzdat/c3.py` parses Nintendo CharPipeline (C3) **GeoPalette** sections
(the `0x005BBC61` sections of a container) following roeming's
MSSB-Export-Models: descriptors, display-object layouts, quantized
position/normal/UV arrays, display-state lists and GX display-list primitives
(quads, triangles, strips, fans). Every parseable section is exported as a
binary glTF with its textures embedded (texture indices in the display states
index the container's texture table), or as OBJ + MTL + PNGs. Skinning,
bones and animations are not handled yet: character models come out in their
bind pose, split into their named parts.

## Audio

Two ADPCM flavours are decoded to WAV on the fly (`zzzzdat/dsp.py`):

- **Disc music** - the 17 `snd/my_snd_h/*.adp` files are GameCube DTK
  streams (48 kHz stereo, 32-byte frames, XA coefficients, arithmetic as in
  vgmstream's `ngc_dtk_decoder.c`). They are listed as entries 10000+ with
  archive `disc`, read straight from the ISO.
- **DSP-ADPCM** - any standard 0x60-byte DSPADPCM header found inside an
  entry becomes an audio stream. So far exactly one exists: the 288 s, 32 kHz
  mono bank inside the `AdGCForm` file at 0x8F2E808 (entry 89), which is
  presumably every voice clip and sound effect back to back; the cue table that
  splits it has not been located yet. The remaining sound effects, if any,
  are probably in the still-unknown `lbl_800EF508` series.

## What is indexed

`index/GYQE01.json` holds 2212 entries covering 447.8 MB of the 450 MB
archive (the rest is 0x800 padding). Where they come from:

| source (`refs`) | count | how |
| --- | --- | --- |
| `dol`, `menus`, `game`, `debug` | 1226 | 16-byte descriptors in the executables, each test-decoded |
| `scan:AdGCForm` | 345 | files tagged with an `AdGCForm` fingerprint: one 5 MB stored DSP-ADPCM bank at 0x8F2E800, plus 344 compressed texture containers packed back to back at 0x19C86800-0x1A15E800 |
| `scan:lzss-probe` | 641 | every 0x800 boundary in the remaining gaps that decodes as LZSS; a stream is assumed to run to the next hit. Their decompressed sizes are approximate (a little trailing junk decoded from padding is possible). |

Index entries are classified by content:

| kind | count | notes |
| --- | --- | --- |
| `anim` | 1161 | Files starting with `00 7B 79 60`: large record tables pointed at by the per-character tables, probably animation sets (unverified) |
| `container` | 779 | Table of u32 section offsets; sections hold textures, C3 geometry palettes, etc. |
| `textures` | 40 | A bare texture table |
| `hvqm4` | 3 | Nintendo HVQM4 1.3 movies (intro 82 MB, 23 MB, 3 MB) |
| `rel` | 3 | `menus.rel`, `game.rel`, `debug.rel` in `aaaa.dat` (listed for completeness) |
| `adgc` | 1 | the DSP-ADPCM sound bank |
| `dsp-adpcm` | 2 | headerless ADPCM-looking data |
| `unknown` | 223 | includes the 52 large stored files of the `lbl_800EF508` table (24 MB, a different container layout, not decoded) |
| `dtk-adpcm` | 17 | disc `.adp` music (not in the archive; ids 10000+) |

About 9,300 textures are decodable across all entries. Sixty entries carry a
community name (`index/known_names.json`: the three movies, the stadiums, and
the "First Found <character>" model files); the web UI and `list` show it in
bold in the name column, and `list --grep` searches it.

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

### AdGCForm fingerprint

`u32 flags|size, u32 params` (both **little**-endian, same meaning as the
descriptor fields) immediately followed by the ASCII magic `AdGCForm`; for
compressed files the LZSS stream starts right after the magic. Found by
scanning the archive for the magic. Despite the name, most files tagged this
way are ordinary texture containers; the one stored file is a DSP-ADPCM bank
(magic, 0x20 bytes of zero form header, standard DSPADPCM header at 0x28,
frames from 0x88).

### Section container

Header of u32 offsets; the first is the header size (0x20/0x40/0x60/...), unused
slots are 0. Each section starts with a 32-bit type word:

| word | section |
| --- | --- |
| `0x005BBC61` | Nintendo CharPipeline (C3) **GeoPalette**: `version, userDataSize, pUserData, numGeoDescriptors, pGeoDescriptorArray`, descriptors `{pDisplayObject, pName}`; ends with the `name.tpl` it textures from and `GroupNN` strings. roeming's MSSB-Export-Models parses these all the way to OBJ. |
| `0x007B7960` | record table; as a small section it holds transform floats and ends with the object's `name.gpc` |
| `0x00184300`, `0x00014300` | related C3 palettes (not decoded) |
| `count, 0, ...` | texture table (first halfword is the texture count) |

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
  dsp.py          DSP-ADPCM and DTK audio decoding + WAV writer
  c3.py           C3 GeoPalette model parsing, OBJ and glTF export
  ui/vendor/      three.js r128 (three.min.js, OrbitControls, GLTFLoader) for the model viewer
  store.py        index + archive + cache + extraction
  cli.py          command line
  server.py       local HTTP API
  ui/index.html   the browser UI
index/GYQE01.json the generated index (checked in; rebuild with `index`)
extracted/        output folder (ignored)
```
