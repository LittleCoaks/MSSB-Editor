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
  *Props*, *Movies*, *Music*, *Sounds*, *Everything else* and *Unused data*, built from the
  community names, the model names inside the files and the executable tables
  they are loaded from. Cards show a representative texture; the detail panel
  has a 3D model tab, texture gallery (with *Replace with PNG* on an extracted
  game), audio player, details and hex.
- **Music** - a three-step replace flow (pick a song, choose the track, install)
  with the original always restorable.
- **Game** - drop / browse / explore to pick the ISO or folder, extract for editing.
- **All files** - the raw entry table: every indexed file with offsets, sizes,
  kind and the executable references it is loaded from; sortable and filterable.

To work on the UI:

```bash
cd frontend
npm install
npm run dev        # Vite dev server with hot reload, proxying /api to the Python server on 8420
npm run build      # writes zzzzdat/ui/dist (commit the result)
npm run check      # svelte-check / tsc
```

**All files** also carries an archive map: a strip of ZZZZ.dat with every
file drawn to scale and coloured by kind, gaps dark. Hovering names a block,
clicking opens it, and the "archive order" tick lists the files in the order
they sit in the archive with the unindexed gaps as rows, which is how a
leftover such as the Utada song shows up next to the files it was packed
with. A file's Details tab links to its neighbours in the archive.

## Setup: choosing the game

The editor needs your copy of the game, chosen once on the **Game** page (or
with `python -m zzzzdat game <path>`), and saved in `config.json` next to the
program. Either of these works:

- a **.iso / .gcm image** - drag it onto the Game page (desktop window), use
  *Browse for ISO...*, pick it in the in-page file explorer, or type the path.
  Everything can be viewed straight out of the image; nothing is extracted.
- an **extracted folder** - Dolphin's *Extract Files* layout (`files/` and
  `sys/` side by side, or the `files/` folder itself) or a GameCube Rebuilder
  root (`&&systemdata/`). This is the writable form: custom music, file and
  texture replacement and character cloning write into it.

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

## What ships, what is generated

The program never carries game data. The repository and the built binary
contain only the index (offsets, sizes, names) and the UI. Everything visual is
produced from the user's own copy after a game is selected:

- thumbnails are built in the background into `cache/<game>/thumbs/` (the
  header shows progress; cards fill in as they finish, and a replaced entry's
  thumbnail is rebuilt);
- full-size textures, WAVs and models are decoded on demand into `cache/`.

`cache/` can be deleted at any time.

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
character slots: the **sub-files table** at `0x800F1D78` (54 slots x 19
tracks: model, low-detail model, 17 animation banks; colour variants point at the
same files as their base slot) and the **master descriptors** at
`0x800EFD38` (516 entries, offsets relative to the 0x1A15E800 ARAM chunk:
the 33 distinct body models, 21 texture sets for the colour-variant slots,
then per slot right/left hand, bat, alternate bat, three grip poses, and the
rig), plus the **slot table** at `0x800F73B8` (54 x u16, `model << 8 |
textureSet`, 0xFF = the model's own textures), which is what makes a colour
variant: the same body model drawn with another texture set. The slot order
is the game's roster order, confirmed from the model names inside each
slot's pack and the community's "First Found" names. DrSeil's guide first
documented the tables but lists the slots in another order. The **hand table** at `0x800F5D98` holds six descriptors per slot (hands with
the batting event track, gloves, hands with the pitching track), reached
through the per-slot u16 table at `0x800EEAAC` (slot x 6); the u16 table at
`0x800EEB18` gives each character one of the 29 **hand-pose event sets**
(master items 486+, mirrored at `0x800F71D8`), -1 for Boo, King Boo, Shy Guy
and Petey. Both those tables were once thought to be sound. The per-slot
sub-items 4..6 and the shared sets share one record layout: a count, then
entries of (total frames, key count, flags, (frame, code) pairs); code 0x64xx
selects a hand pose. debug.rel keeps the development file names of every
sub-file (`char/ninNN/model0.dat`, `model1.dat`, `motb.dat` ... `motpm.dat`),
which is where the bank names in the UI come from. game.rel's two data
tables are the preset team rosters (12 x 1440 bytes, copied to
`inMemRoster`) and 18 camera keyframe sets loaded into `g_Camera`. The catalog
uses these tables to name assets ("Toad (blue) - textures (ARAM)", "Bowser -
pitching hand-pose track") and groups every slot, variants included. A character
model's viewer has a colour-variant selector that draws it with a variant
slot's texture set (the `variant=` query of the `.glb` route).

### The Characters page

The **Characters** page lists the game's 32 characters (`zzzzdat/roster.py`,
`/api/roster`): the 54 slots folded onto the 32 character ids the game itself
uses, so the five Toads are one entry with five colours. Each character shows
its model (the slot's pack, the low-detail copy and the ARAM body), a colour
dropdown that redraws it with a variant slot's texture set, its hands and
gloves, the bat (see below), the 17 animation banks labelled by their
development file names and what they animate (click one to play its
animations on the model), the voice group with a play button and WAV download
per clip, and every file the tables tie to the character. "Export everything"
writes the model as glTF with all animations, OBJ, textures per colour and
the voice clips under `extracted/characters/<name>/`.

**Where the bat is.** There is no bat file. Every hand container carries,
after its GeoPalette, a section with version word 0x40001 holding complete
vertex sets for the hand (`zzzzdat/handpose.py`): the batting hands
(`L/R_hand07`, 556 triangles) model the bat as triangles collapsed onto the
palm, and two of their twelve poses pull it out into a 1.8-unit bat gripped
in the fist; the simpler `L/R_hand00` hands have three poses (open, holding
the bat, hidden). The animation event tracks (sub-items 4..6 of each slot,
codes 0x64xx) choose the pose per frame. Goomba, Paragoomba and Petey, who
have no hands, have the bat itself in their hand slots. The viewer's "with
bat" attachment and the "with bat" equipment chips on the Characters page
apply the bat pose (`pose=` on the `.glb`/`.obj` routes).

### The Stadiums page

The **Stadiums** page (`zzzzdat/stadiums.py`, `/api/stadiums`) lists the seven
parks from the DOL's `StadiumFiles` table (21 descriptors, three per stadium
in table order: Mario Stadium, Bowser Castle, Wario Palace, Yoshi Park,
Peach's Garden, DK Jungle, Toy Field; a stadium with fewer files repeats one
file across its slots). The viewer draws every model section of a file
together (`/api/entry/<id>/model/all.glb`): the park, its sky dome drawn
inside-out so the camera can look through it, and the sun-glare billboard
(a mesh named 加算光, "additive light") blended additively. Mario Stadium's
props from game.rel's `marioStadiumCDR` table are listed beside the file
variants. The variants are labelled day or night from the sky dome's
texture (Mario Stadium: two day files and a night one; Bowser Castle: two
dark files and a daylight practice field); what separates two day files is
still unknown. The night look is baked into the geometry: every stadium mesh
carries per-vertex colours (GX RGB565/RGB8/RGBA4 arrays, now exported as
glTF COLOR_0), and the night file's average about half the day file's, which
is where the shadows and lighting live; the skeleton sections only differ in
object positions. Each pack also has a collision mesh (`zzzzdat/collision.py`): a
`00 NN 43 00` section of NN records, each a run of GX-style primitives
(u16 kind, u16 n: kind 1 = triangle strip of n triangles, kind 0 = triangle
list of n triangles) whose points are (x, y, z, u16 surface tag, u16 0). The
viewer's "collision" tick draws it as translucent panels: the outfield wall
ring, the dugouts and the ground. Finding it also fixed the posing of packs
with several skeletons: actors pair with GeoPalettes in order (the park's,
then the sky's), not by nearest-preceding section, which had posed the park
with the sky's transform. Two field packs (Wario Palace, Toy Field) are GeoPalettes with a
version word of 0, which the parser now accepts; before that they rendered
as an empty sky.

### Character cloning

The **Characters** page (folded away under "Slot cloning") and
`clone-character SOURCE TARGET` make one
roster slot play as another character, following DrSeil's verified recipe:
the slot's 19 sub-file descriptors, seven sub-items and rig in the master
table, its glove index and its slot-table entry (body model and texture
set) are rewritten to describe the source, so cloning a colour variant gives
the recolour too. By default the 19 sub-files are copied to the end of
ZZZZ.dat so the clone can be retextured on its own, and the rig is copied in
place inside the ARAM chunk when the source fits the target's span (the
chunk is packed tightly and loaded whole, so it cannot grow); the body
model is copied in place as well when the target's own model has no other
user and the source has no recolour, otherwise the clone shares the
source's model through the slot table. Sub-items are shared. `--share`
writes no data at all. The index shows the
copies under the target character; `restore-character` puts every table and
in-place byte back exactly. See `zzzzdat/clone.py`.

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
  mono stream inside the `AdGCForm` file at 0x8F2E808 (entry 89). It is not a
  sound bank: it is a complete, unlooped, fade-out master of **"Letters" by
  Hikaru Utada** (Deep River, 2002), identified by ear. Nothing in the game
  references it; it sits between two referenced files (`p_machine00.gpc` and
  `chain.gpc`), so it was packed by the build like any other asset, presumably
  a placeholder or test stream someone forgot to remove. The sound effects and
  voice lines are in the MusyX groups of the `lbl_800EF508` series (see below).

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

`python build.py --installer` goes on to pack that folder into
`dist/MSSB Editor Setup <version>.exe` with NSIS (`installer/installer.nsi`):
Program Files, a Start menu entry, an optional desktop shortcut and an
uninstaller. The installed program keeps its settings and cache in
`%APPDATA%\MSSB Editor` and writes exports to `Documents\MSSB Editor\extracted`,
so uninstalling never touches your work. On macOS the same command
produces `dist/MSSB Editor <version>.dmg` with the .app bundle and an
Applications shortcut. CI builds the Windows folder and installer on every
push; pushing a tag `vX.Y.Z` (matching `zzzzdat/version.py`) runs the
Release workflow, which builds the Windows installer and the macOS disk image
and publishes them as a GitHub Release.

**Updates.** The program checks the newest GitHub Release when it starts
(`zzzzdat/update.py`; a setting on the Game page turns the check off, and a
button runs it by hand). When a newer version exists a bar appears at the
top; Install downloads the installer for your platform into the data folder
and starts it: on Windows the setup upgrades in place, on macOS the disk
image opens for a drag to Applications. A development checkout only reports
updates.

The bundle carries the UI, three.js and the shipped index; the executable
opens the window when double-clicked and behaves like the CLI when given
arguments (`"MSSB Editor.exe" list --kind hvqm4`). The icon (a black-and-white
baseball) is drawn by `tools/make_icon.py`, which writes the browser favicon
(`frontend/public/favicon.svg`) and the window/executable icon
(`zzzzdat/ui/icon.ico`, `icon.png`); re-run it and rebuild the frontend after
changing the drawing. Users pick their
own ISO or extracted folder on the Game page the first time; `config.json`
and the cache go to `%APPDATA%\MSSB Editor`, exports to
`Documents\MSSB Editor\extracted`.

## What is indexed

`index/GYQE01.json` holds 2212 entries covering 447.8 MB of the 450 MB
archive (the rest is 0x800 padding). Where they come from:

| source (`refs`) | count | how |
| --- | --- | --- |
| `dol`, `menus`, `game`, `debug` | 1226 | 16-byte descriptors in the executables, each test-decoded |
| `scan:AdGCForm` | 345 | files tagged with an `AdGCForm` fingerprint: one 5 MB stored DSP-ADPCM bank at 0x8F2E800, plus 344 compressed texture containers packed back to back at 0x19C86800-0x1A15E800 |
| `scan:lzss-probe` | 641 | every 0x800 boundary in the remaining gaps that decodes as LZSS; a stream is assumed to run to the next hit. Their decompressed sizes are approximate (a little trailing junk decoded from padding is possible). |

### What the unreferenced files are

About 40% of the archive is never named by a descriptor. `zzzzdat/twins.py`
works out what it is when the index is built (or with `python -m zzzzdat
annotate`), and the catalog names and groups it accordingly:

* **Animation sources** (0x0F12C800-0x186A1800, 157 MB, 540 banks): one bank
  per character and category with the sequence names still in them
  (`b00_wa_000`: category letter, base roster slot, action, take). The 17
  shipped banks per character hold the same animations with the names
  stripped; each source is matched to its shipped twin by sequence count,
  track count and durations, and the viewer then shows the real names on the
  shipped bank (417 of the shipped banks get names this way). They are listed
  under their character as "batting/running/pitching/fielding/catching/
  reaction animation source".
* **Prototype library** (0x0CE16800-0x0E581000, 25 MB): the same categories
  for a placeholder rig (`f_k_01`) plus test packs (`hitomi.gpc`, `s16.gpc`,
  `taiki.gpc`, a Koopa skin test), each stored twice.
* **Earlier copy of the character data** (0x19A6F800-0x1A15E800, 7 MB): the
  chunk the master table addresses at 0x1A15E800, mostly byte-identical.
  Bank 13 (`motrtoy`) names all sixteen of its sequences "other01", so
  those 32 sources carry no slot digits; they are placed by the character
  run they sit in. Three banks at the end of the run are a prototype Bowser
  batting set (`Kuppa_B_bant`, `_swing`, `_takeback`, ...) and two are test
  banks (`test`, `f_h_01`).
* **Leftovers**: small records next to those blocks.

Entries whose content is identical to a referenced file are shown as "copy
of ..." with a link to the original (`twin`). The remaining DOL-table entries
(title screen, team logos, help screens, loading tips, debug graphics, ...)
are named by hand in `index/editor_names.json`, which is loaded alongside the
community names.

Index entries are classified by content:

| kind | count | notes |
| --- | --- | --- |
| `anim` | 1161 | Files starting with `00 7B 79 60`: large record tables pointed at by the per-character tables, probably animation sets (unverified) |
| `container` | 779 | Table of u32 section offsets; sections hold textures, C3 geometry palettes, etc. |
| `textures` | 40 | A bare texture table |
| `hvqm4` | 3 | Nintendo HVQM4 1.3 movies (intro 82 MB, 23 MB, 3 MB) |
| `rel` | 3 | `menus.rel`, `game.rel`, `debug.rel` in `aaaa.dat` (listed for completeness) |
| `adgc` | 1 | the DSP-ADPCM sound bank |
| `songs` | 2 | MusyX song containers (19 + 1 sequenced songs), exported as MIDI |
| `text` | 3 | text string tables from menus.rel and game.rel |
| `musyx` | 48 | MusyX sound groups from the `lbl_800EF508` table: 47 sound-effect groups (875 effects, 1,300 samples) and one instrument bank |
| `unknown` | 175 | |
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

### Animation banks and skins

`ANIMBank` files (the 1,193 standalone `anim` entries and the ANIM sections
inside character packs) share the 0x007B7960 version word with actors.
`zzzzdat/anim.py` documents the layout. The important findings: keyframe
settings hold a quaternion (4 x s16, 14 fraction bits) when `animType & 8`
and a translation (3 x s16, fraction bits from `quantizeInfo`) when
`animType & 1`; tracks are keyed by bone id; the animation *replaces* the
bone's rest rotation. The skin section (`sHdr`) maps ranges of the body's
interleaved position array to bones by their pre-order index in the actor's
tree, with source vertices equal to the rest pose, so it exports as ordinary
glTF skinning. Hermite tangents are ignored (linear / slerp between keys).

Hands, gloves and bats are separate models (per-slot items in the master
table, or extra sections in menu packs) modelled from the wrist along +X.
Every rig shares the same arm ids (16..20 right, 22..26 left), so the viewer
can hang them from wrist bones 19 and 25 ("with hands / gloves / bat") and
they follow the animation.

The model viewer plays them: pick a bank (sections of the file itself, then
the character's standalone banks from the DOL sub-file table), then a
sequence; `.glb` downloads carry the skeleton, skin and animations
(`/api/entry/<id>/model/<sec>.glb?anim=<entry>:<section>`).

### MusyX sound groups

The game's sound effects run on Factor 5's MusyX engine (the decomp has its
source under `src/Musyx`). The 48 files of the `lbl_800EF508` table are
group files: four sections (project, sample directory, pool, sample data)
that `sndPushGroup` takes as-is. `zzzzdat/musyx.py` documents the layout;
in short, the project's FX table maps a sound-effect id to a macro, the
macro's `START_SAMPLE` steps name the samples, and the sample directory
gives each sample's offset, rate, base note, loop and DSP-ADPCM
coefficients. The Audio tab lists every sample of a group with the effects
that use it, and a button per effect plays its sample. Thirty-four of the
groups are character voice sets (13 lines each); which character each
belongs to is not yet known. Sequenced music (the instrument bank plus
`.song` data elsewhere) is not rendered.

### Movies

The three cutscenes are HVQM4 1.3 (Hudson's codec, 640x448 at 30 fps with
32 kHz ADPCM audio). Decoding uses Tilka's bit-accurate reverse-engineered
decoder (LGPL v2+, vendored under `native/hvqm4/` with the changes listed in
its header and re-applied by `vendor.py`), built into a small helper:

```
python native/build_hvqm4.py     # needs clang or gcc; on Windows the LLVM
                                 # component of Visual Studio is enough
```

The helper (`native/bin/hvqm4dec`) decodes a movie once into the cache as
back-to-back JPEG frames (TinyJPEG, public domain) with an index, plus the
audio as WAV; the Movie tab then plays it with the audio element as the
clock and frames drawn on a canvas, and *Export frames + WAV* writes
numbered JPEGs for ffmpeg (`ffmpeg -framerate 30 -i frame_%05d.jpg -i
audio.wav movie.mp4`). Without the helper the movies are still listed and
their raw `.h4m` can be exported. The Windows build ships the helper beside
the exe.

### Sequenced songs

The menu themes, jingles and results music are not recordings: they are
MusyX sequences played on the instrument bank (sound group 31). They live in
two files referenced from game.rel, a 19-song container and a one-song
container, and `src/menus/rep_01A0.c` in the decomp shows the menus using
the first two songs of the 19. `zzzzdat/song.py` documents the arrangement
layout (an older MusyX version: track table at 0x18, no loop-point table),
decodes the 4- and 6-byte pattern events and writes standard MIDI files
with the tempo track and one track per channel at 384 ticks per quarter.
Program numbers are the bank's instrument slots, so a General MIDI player
substitutes its own sounds. The Songs tab can also *play* a song:
`zzzzdat/render.py` resolves each note through the bank's pages, layers,
keymaps and macros to a sample, pitch-shifts it against the sample's base
note, loops it while the note is held and mixes with velocity, channel
volume and pan (numpy required). Envelopes and effects are not modelled,
so it is a faithful-enough preview rather than the game's mixer. Each song
also downloads as MIDI or WAV; *Export MIDI* writes them all.

The two small tables from menus.rel and game.rel that an earlier heuristic
called ADPCM are the games text string tables (u16 count, version 0x131,
offsets to records of 16-bit glyph codes) and are now labelled as such.

### Texture table

0x20-byte records, data offsets relative to the table start:

```
u16 count (record 0 only)   u16 pad
u32 data offset             u32 TLUT offset
u16 height u16 width        u8 flags[4] (wrap S/T, filter, ?)   (height first, as in the SDK's TEXHeader)
f32 LOD bias                u16 pad  u8 mip levels  u8 GX format
u16 TLUT entries            u8 TLUT format  u8 pad
```

All GX formats (I4, I8, IA4, IA8, RGB565, RGB5A3, RGBA8, C4, C8, C14X2, CMPR)
are decoded and encoded by `zzzzdat/gx.py`. Mip levels follow the base level
contiguously, each at the block-rounded size of its dimensions, so a record
with `mip levels = n` owns `n + 1` levels. A few tables reserve fewer bytes
than the block-rounded size (the last block row of an odd-sized C8 image runs
into the next texture) and some records share pixel data.

### Replacing a texture

`replace-texture` (and *Replace with PNG* in the gallery) re-encodes a PNG in
the record's own format, size, mip count and palette size and writes it over
the original bytes, so nothing else in the file moves. A PNG of another size is
resampled to fit; palette formats get a median-cut palette in the record's
TLUT format; CMPR uses a small DXT1 encoder with 1-bit alpha. Writes are
capped at the room the table reserves for that record. The whole entry then
goes through the usual replace path (recompress, repoint, backup), so
*Restore original* undoes it.

## Layout

Per-user files (`config.json`, `cache/`, `extracted/`) live in the repository
root during development and, when frozen, in the platform's app-data folder
(`%APPDATA%\MSSB Editor`, `~/Library/Application Support/MSSB Editor`,
`~/.local/share/mssb-editor`); `MSSB_EDITOR_HOME` overrides that. Shipped
read-only data (the index, the built UI) comes from the bundle. See
`zzzzdat/paths.py`.

Tests: `pip install pytest` then `pytest` (unit tests on synthetic data; the
`game`-marked tests use the configured game and skip without one).

```
zzzzdat/
  disc.py         find ZZZZ.dat (file or inside the ISO), FST parsing, decomp-repo path
  lzss.py         decompressor
  descriptors.py  scan executables for descriptors, verify, build/load the index
  formats.py      identify contents: container / textures / HVQM4 / ADPCM / anim bank
  gx.py           GX texture decoding/encoding + PNG writer
  png.py          PNG reader (stdlib only) and resampling
  texedit.py      in-place texture replacement inside an entry
  dsp.py          DSP-ADPCM and DTK audio decoding + WAV writer
  hvqm.py         HVQM4 movies through the native helper and the movie cache
  musyx.py        MusyX sound groups: sfx -> macro -> sample, sample decoding
  song.py         MusyX sequenced songs -> MIDI
  render.py       plays songs with the instrument bank's samples (numpy)
  c3.py           C3 GeoPalette model parsing, actors, OBJ and glTF export (rigged)
  anim.py         ANIM banks and skin files
  app.py          desktop window (pywebview) around the server
build.py          PyInstaller one-folder build
native/hvqm4/     vendored HVQM4 decoder (LGPL) + TinyJPEG + the hvqm4dec driver; native/build_hvqm4.py builds it
pyproject.toml    package metadata; `pip install -e .` gives a `zzzzdat` command
  store.py        index + archive + cache + extraction
  cli.py          command line
  paths.py        shipped vs per-user locations
  server/         local HTTP API: router + context + jobs, routes/{static,game,entries,media,music,edit}
  ui/dist/        the built Svelte UI (served at /)
  catalog.py      groups entries into characters / stadiums / menus / ... for the UI
  chars.py        the DOL character tables (54 slots x 19 sub-files, master descriptors)
  edit.py         replace / restore entries: LZSS encode, write, repoint descriptors, backups
  clone.py        character cloning on top of edit.py
index/GYQE01.json the generated index (checked in; rebuild with `index`)
extracted/        output folder (ignored)
```
