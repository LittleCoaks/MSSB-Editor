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

- [ ] **Collision surface tags.** The stadium collision panels carry tags
      (3, 6, 0x83, 0x85, ...); colour the overlay by tag and work out which is
      grass, dirt, wall and out-of-play.
- [ ] **Stadium prop placement.** Mario Stadium's props are listed but not
      positioned in the scene; their positions live in game code.
- [ ] **Animation event codes** other than the hand pose (0x40xx, 0x50xx,
      0x80xx), probably sound and effect cues; would let the viewer play the
      bat pose at the right frame of a swing.
- [ ] What separates two daytime files of the same stadium (their skies match).
- [x] The bat (built into the batting hands, pulled out by a hand pose).
- [x] The hand tables, event-track sets, grip records, game.rel tables.
- [x] The 37 no-character animation source banks.
- [x] Entry 89's DSP-ADPCM stream ("Letters", Hikaru Utada).

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
