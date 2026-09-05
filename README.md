# MSSB Editor

Browse, view and extract the assets packed inside `ZZZZ.dat`, the 450 MB
archive that holds nearly all of Mario Superstar Baseball's (GYQE01) data,
with editing and custom-music support on the roadmap. Pure Python 3.10+; the
only optional dependency is pywebview for the desktop window.

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

## The interface

The UI is a Svelte + TypeScript app in `frontend/`, built into
`zzzzdat/ui/dist` (checked in, so nothing but Python is needed to run it).
It is organised for people who are not reverse engineers:

- **Home** - game status in plain words and the three things people come for:
  browse assets, change the music, movies & sounds.
- **Browse assets** - a catalog by *Characters*, *Stadiums*, *Menus & UI*,
  *Props*, *Movies*, *Music*, *Sounds* and *Everything else*, built from the
  community names, the model names inside the files and the executable tables
  they are loaded from. Cards show a representative texture; the detail panel
  has a 3D model tab, texture gallery, audio player, details and hex.
- **Music** - a three-step replace flow (pick a song, choose the track, install)
  with the original always restorable.
- **Game** - drop / browse / explore to pick the ISO or folder, extract for editing.
- The original technical page is kept as **Advanced view** (`/legacy`).

To work on the UI:

```bash
cd frontend
npm install
npm run dev        # Vite dev server with hot reload, proxying /api to the Python server on 8420
npm run build      # writes zzzzdat/ui/dist (commit the result)
npm run check      # svelte-check / tsc
```

## Setup: choosing the game

The editor needs your copy of the game, chosen once on the **Game** page (or
with `python -m zzzzdat game <path>`), and saved in `config.json` next to the
program. Either of these works:

- a **.iso / .gcm image** - drag it onto the Game page (desktop window), use
  *Browse for ISO...*, pick it in the in-page file explorer, or type the path.
  Everything can be viewed straight out of the image; nothing is extracted.
- an **extracted folder** - Dolphin's *Extract Files* layout (`files/` and
  `sys/` side by side, or the `files/` folder itself) or a GameCube Rebuilder
  root (`&&systemdata/`). This is the writable form: custom music and, later,
  asset replacement write into it.

Viewing works from both; editing needs the folder. When an ISO is selected the
Game page offers to extract it (all 1.4 GB, or just `sys/` + `snd/` for music)
to `<iso name> (extracted)` beside the image, and pairs the two so the image
stays the read source while the folder takes the writes. The decomp repo is
not required: the index ships with the program, and a rebuild decompresses the
RELs out of `aaaa.dat` itself (symbol names are only added when the decomp repo
is present as a sibling `MSSB Decomp` folder or via `MSSB_DECOMP`).

Drag-and-drop of paths and the native Browse dialogs work in the desktop
window; a plain browser tab cannot see dropped file paths, so it gets the
in-page explorer instead.

## Usage

```bash
cd "MSSB Editor"
pip install pywebview              # optional: needed for the desktop window
python -m zzzzdat                  # desktop window (same as `python -m zzzzdat app`)
python -m zzzzdat serve            # or the web UI in your browser at http://127.0.0.1:8420/
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

## Editing: replacing files

With ZZZZ.dat and aaaa.dat in the game folder (*Prepare for editing* on the
Game page, or `python -m zzzzdat dump --only ZZZZ.dat,aaaa.dat`) any indexed
entry can be replaced with new raw contents, from the Details tab of an asset
or from the command line:

```bash
python -m zzzzdat replace 893 my_mario_pack.bin   # entry id + file with the raw (decompressed) contents
python -m zzzzdat modified                        # what has been replaced
python -m zzzzdat restore-entry 893               # undo
```

`zzzzdat/edit.py` compresses the data with the entry's original LZSS settings
(`zzzzdat/lzss.py` now has an encoder; it packs ~3% tighter than the game's
own files and round-trips exactly), writes it in place when it fits the old
0x800-aligned slot and otherwise appends it to ZZZZ.dat, then repoints every
descriptor that references the entry: in `main.dol` directly (including the
ARAM-relative master character table), or inside a REL by decompressing it out
of `aaaa.dat`, patching, recompressing and updating the REL's own descriptor.
The first change to an entry backs up its bytes and descriptors (and the
stock REL slot) under `<files>/_mssb_editor_backup/`; `restore` puts
everything back byte-for-byte. `overrides.json` there tells the index where
replaced entries now live.

This is the raw layer that texture and model replacement will build on: for
now the replacement file must already be in the game's own format (for
example a "Raw file" download edited in a hex editor). The approach follows
DrSeil's character-cloning work
([mssb-dtk, feat/character-cloning-texture-decoupling](https://github.com/DrSeil/mssb-dtk/tree/feat/character-cloning-texture-decoupling)),
which also proved in-game that repointed descriptors and appended data work
with no code patches.

### Character tables

`zzzzdat/chars.py` names the two DOL tables that define the 54 playable
character slots (from DrSeil's guide): the **sub-files table** at
`0x800F1D78` (54 slots x 19 tracks: model, equipment, 17 animation banks) and
the **master descriptors** at `0x800EFD38` (516 entries, offsets relative to
the 0x1A15E800 ARAM chunk: body model, right/left hand, bat, alternate bat,
three grip poses and the skeleton rig per slot). The index now includes the
master table's entries, and the catalog uses both tables to name assets
("Toad (red) - model", "Bowser - pitching grip") and to group them by
character.

## Custom music

The [MSSB-Custom-Music](https://github.com/LittleCoaks/MSSB-Custom-Music)
tool is merged in as `zzzzdat/music/` (its encoder, resampler, DOL
stream-table reader and installer, unchanged apart from imports; its self-test
runs with `python -m zzzzdat.music.selftest`). It needs a **writable game
dump** with `snd/my_snd_h` and `sys/main.dol`:

```bash
python -m zzzzdat game "D:\games\Mario Superstar Baseball.iso"   # or an extracted folder
python -m zzzzdat dump --only snd/      # extracts snd/ and sys/ beside the ISO (~180 MB) and pairs them
python -m zzzzdat dump                  # or the whole disc (1.4 GB), the folder Dolphin can boot
python -m zzzzdat music list
python -m zzzzdat music install song.mp3 --track mario_01_h.adp
python -m zzzzdat music restore --track mario_01_h.adp
python -m zzzzdat music --root "D:\dumps\GYQE01\files" list   # another dump (also sets the game)
```

Any audio the decoders can open (wav always; mp3/flac/ogg with
`pip install miniaudio`, more with ffmpeg on PATH) is conformed to 48 kHz
16-bit stereo, encoded to DTK ADPCM (bit-exact decoder, encoder within 0.03 dB
of Nintendo's `trkmake`), padded with silence to the stock length so the
console never streams past the end, and written over the track after backing
up the original once. When the length differs from the DOL's stream table it
prints the two Gecko writes that repoint it. `pip install numpy` makes
encoding about 30x faster.

The **Music** page in the UI does the same with a file drop zone, progress
bar, a player for every track, and restore buttons.

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

## Desktop window and packaging

`python -m zzzzdat app` runs the HTTP server on a random loopback port in a
background thread and shows the UI in a native window through
[pywebview](https://pywebview.flowrl.com/) (Edge WebView2 on Windows, WebKit
elsewhere). Without pywebview installed it falls back to the browser. The page
and the API are identical in both modes, so everything the browser tab can do,
the window can do.

To ship it as a standalone program:

```bash
pip install pywebview pyinstaller
python build.py            # -> dist/MSSB Editor/MSSB Editor.exe
```

The bundle carries the UI, three.js and the shipped index; the executable
opens the window when double-clicked and behaves like the CLI when given
arguments (`"MSSB Editor.exe" list --kind hvqm4`). Users pick their
own ISO or extracted folder on the Game page the first time; `config.json`,
`extracted/` and `index/` are written next to the executable.

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
  app.py          desktop window (pywebview) around the server
build.py          PyInstaller one-folder build
pyproject.toml    package metadata; `pip install -e .` gives a `zzzzdat` command
  store.py        index + archive + cache + extraction
  cli.py          command line
  server.py       local HTTP API
  ui/index.html   the legacy technical UI (served at /legacy)
  ui/dist/        the built Svelte UI (served at /)
  catalog.py      groups entries into characters / stadiums / menus / ... for the UI
  chars.py        the DOL character tables (54 slots x 19 sub-files, master descriptors)
  edit.py         replace / restore entries: LZSS encode, write, repoint descriptors, backups
index/GYQE01.json the generated index (checked in; rebuild with `index`)
extracted/        output folder (ignored)
```
