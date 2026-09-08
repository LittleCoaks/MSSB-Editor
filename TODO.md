# MSSB Editor — what's left

Ticked items are done; the rest is open, roughly in the order worth doing them.
Details of what already works are in the README.

## Editing

- [ ] **Model import.** Bring an edited glTF or OBJ back into a C3 GeoPalette
      section: quantised positions, normals, UVs and vertex colours, display
      lists, the texture table, and hand-pose vertex sets for hands. The
      section re-basing writer (`zzzzdat/rebase.py`) already slides the rest
      of the container to fit.
- [ ] **ARAM chunk rebuilder.** Files whose descriptors sit in the master
      table's ARAM chunk (character body models and texture sets) are refused
      growth because the game loads the chunk whole and packed. Rebuild the
      chunk and re-base every master descriptor so those files can grow too;
      character skins are the textures people most want to change.
- [ ] **Song import** for the sequenced menu music (export to MIDI exists).
- [ ] **Faster REL replacements.** Anything referenced from menus.rel takes
      about a minute because the module is recompressed each time; cache it.
- [x] Texture replacement at any size (re-basing writer).
- [x] Dolphin texture packs: textures export under Dolphin's dump names.

## Data still not understood

- [x] Collision surface tags: game.rel's `BALL_COLLISION_TYPE` (grass, wall,
      structure, foul line, dirt, pit, water, Chain Chomp hazard...; 0x80 =
      foul territory); the overlay is coloured by type with a legend.
- [ ] **Stadium prop placement.** Mario Stadium's props are listed but not
      positioned in the scene; their positions live in game code.
- [x] Animation event keys: (code, frame) pairs; the frame's high byte marks
      bat contact (0x80), pitch release (0x50), the catch (0x40),
      follow-through (0x60), last frame (0x20). Inferred from where they fall
      across every character, not from code. Still open: the meaning of the
      code channels other than 0x64 (0x3c, 0x32, 0x28, 0x1e), and playing the
      bat pose at the contact frame in the viewer.
- [ ] What separates two daytime files of the same stadium (their skies match).
- [x] The bat (built into the batting hands, pulled out by a hand pose).
- [x] The hand tables, event-track sets, grip records, game.rel tables.
- [x] The 37 no-character animation source banks.
- [x] Entry 89's DSP-ADPCM stream ("Letters", Hikaru Utada).

## Other versions of the game

- [x] Load the European (GYQP01), Japanese (GYQJ01) and kiosk-demo discs as
      well as the American one. The build is named from the disc header
      (`zzzzdat/versions.py`) and its descriptor tables are found in its own
      main.dol (`zzzzdat/layout.py`), so nothing is written down per version;
      each build gets its own index, built on first use.
- [ ] **Community names for the other builds.** `index/known_names.json` is a
      list of offsets in the American ZZZZ.dat. The same files could be
      matched across builds by content, so the names carry over.
- [ ] **Mario Stadium's props** are only recognised on the American disc,
      where the decomp names the `marioStadiumCDR` table; find that table by
      shape instead.

## Animation fidelity

- [ ] Hermite tangents are played as linear / slerp.
- [ ] 83 tracks with an unknown animation type flag are skipped.
- [ ] Bank 13's sixteen sequences have no names in the game data; name them by
      hand from what they look like.

## Shipping

- [ ] **First tagged release** (`v0.1.0`): runs the Release workflow, which
      also gives the macOS build its first run.
- [ ] A macOS job in CI so Mac builds are tested on every push, not only at
      release.
- [ ] Code signing / notarisation (deferred; needs an Apple developer account
      and a Windows certificate).
- [x] Windows installer, macOS disk image, in-app update check.

## Polish

- [ ] The deferred "Menu music" and "Dictionary" layered-song presets (need
      the exact song combinations).
- [ ] Movie export to MP4 needs ffmpeg on the path; document or bundle.
- [ ] Stadium file variants: label the third Bowser Castle file (a daylight
      practice field) and any other odd ones by hand.
