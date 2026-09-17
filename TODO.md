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
- [ ] **Stadium prop placement.** Each park has one prop pack (the seven
      `marioStadiumCDR` files, in park order: waves, Bowser's parts, Chain
      Chomps and the sandstorm, Piranha Plants, garden parts, barrels with
      the Klaptrap and river, toy parts). Since 2026-09-17 the Stadiums page
      draws the pack in the scene (toggle, on by default) where its actors
      place the objects: scenery like the waves, river and smoke carries
      world positions; instanced props (barrels, Piranha Plants, Chain
      Chomps) sit at the origin because the game positions those in code.
- [x] Animation event keys: (code, frame) pairs; the frame's high byte marks
      bat contact (0x80), pitch release (0x50), the catch (0x40),
      follow-through (0x60), last frame (0x20). Inferred from where they fall
      across every character, not from code. Still open: the meaning of the
      code channels other than 0x64 (0x3c, 0x32, 0x28, 0x1e), and playing the
      bat pose at the contact frame in the viewer.
- [ ] What separates two daytime files of the same stadium (their skies match).
- [x] Text control words, confirmed against the decomp's DrawText; strings
      render with the game's font pages and metrics. Editing text needs the
      table rewritten (a glyph encoder is the inverse of the decoder).
- [ ] **Stat editing.** The stat table decodes; writing edited stats back
      (the file is 18,144 bytes and uncompressed) is a small step from there.
- [ ] **Line-up records.** Which menu reads the 48 filled 18-byte records
      after the stat rows, and what the nine 0x0A bytes per record are.
- [ ] **Camera sets** (`lbl_3_data_20FDC`, 461 KB): the stride guess says
      48-byte records; the layout is still unread.
- [x] Whether an unused model's animations are simply the entries after it in
      the archive. **They are not**, so the viewer will not guess: see
      "Animations are not found by adjacency" below.
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

## Viewer feedback from the v0.2 testers (2026-09-16)

- [x] **Hands are textureless.** Fixed 2026-09-16 (parts with no textures keep the body's indices; viewed alone, an equipment file borrows its character's body texture set via `Store.texture_donor`). Was: the hand and glove containers
      carry no texture table; their draws index the character's *body*
      texture set (Luigi's hands use body textures 4, 8 and 9). `export_model`
      offsets part texture indices past the body's, so they dangle. Fix: when
      a part has no textures of its own, keep its indices as they are.
- [ ] **Hand poses are not animated.** The hands hang on wrist bones 19/25 and
      follow the arm, but the finger/bat pose sets (0x40001 sections, chosen
      per frame by the 0x64xx event tracks) are never switched, so the bat
      never appears at contact. Same item as "animated hands+bat" above. If a
      tester sees the hands not following the arm at all, that is a separate
      bug still to reproduce.
- [x] **Per-hand equipment selector.** Done 2026-09-16: `parts` takes per-side
      mesh names (`L_glove,R_bat`); the viewer has a dropdown per hand.
- [x] **Default playback speed.** Viewer now starts at 1/2x (2026-09-16); the true step is still unconfirmed. Tracks are exported at 60 frames/s
      (`anim.FRAME_RATE`) and the viewer starts at 1x; a tester reports the
      game looks like half that. `ANIMTick` is a stub in the decomp, so the
      real step is unconfirmed: start at 1/2x for now and find the frame
      advance in the actor update code to settle it.
- [x] **Bat only for Mario.** Not reproduced on the US disc, but Donkey Kong
      had no bat: his fist closes as the bat unfolds, so the whole hand never
      grew. `bat_pose()` now finds the draw that unfolds from under 0.1 to
      over 0.9 units (2026-09-16); DK's pose sets also cover only 301 of his
      327 vertices, which `parse_poses` now fills from the rest mesh. Every
      character with hands gets the bat now.
- [ ] **Animation names blank for most characters.** Names come from the
      source-bank twins (`twins.sequence_names`, tag `names:` in the index).
      On the US index 13-15 of 17 banks per character are named (Boo 1/17).
      A fresh index without `annotate`, or an EU/JP build, has none: either
      ship the annotation in every build's index or run it on first use.
- [ ] **Facial animation.** The body is one mesh plus the cap; faces are
      textures (the two 128x128 pages in the body set), so expressions must
      be texture or UV swaps, probably the unidentified event channels
      (0x3c, 0x32, 0x28, 0x1e). Research item.

- [x] **Prop packs render** (2026-09-16). `ball.gpc` and `toy_ball.gpc` (the
      ball, its shadow, a loose 144-triangle bat, the meet marker, banana,
      egg, Bullet Bill, Koopa shells, mushroom, fire flower, star, "special"),
      and `ball_kage.gpc`, list their sections out of order and repeat shared
      ones, which `parse_container` refused; each object's draws also count
      textures from the table right after its GeoPalette (`Store.texture_base`).
      The same table layout in `teamstar.gpc` is global, told apart by the
      indices fitting. Index records refreshed in all five builds.

- [x] **Text tables on every build** (2026-09-16). The second header word is
      not a version (US 0x131/0x132, EU 0x10d/0x10e, JP 0x1c4, demos 0x1d8
      and 0x2ed..), so `text.is_table` now recognises the table by its shape;
      each of the five builds indexes exactly its six tables. The EU disc
      decodes and draws like the US one.
- [ ] **Japanese text and the demos.** The JP disc and both kiosk demos
      encode their strings as proportional-font cells (the US demo too, at
      cell ids from 0x154 up), and `Store.font` does not find their font
      pages, so they show as `<cell N>` with no "as drawn" view. Needs the
      cell -> glyph remap and the font pages located per build.

## Animation fidelity

- [ ] Hermite tangents are played as linear / slerp.
- [ ] 83 tracks with an unknown animation type flag are skipped.
- [ ] Bank 13's sixteen sequences have no names in the game data; name them by
      hand from what they look like.

### Animations are not found by adjacency

Measured on the retail disc (2,596 entries), after asking whether a model in
the asset browser could just be given the banks that follow it. It cannot, and
the idea is parked rather than open:

- The game does not resolve animations positionally. Character assets come out
  of the subfiles table at `0x800F1D78`, a 54x19 grid of 16-byte descriptors
  indexed `slot * 19 + track` (`chars.classify`). Archive order is a packing
  artefact of whatever built ZZZZ.dat, not a link the game reads.
- The packing convention is real but narrow. The 576 classified anim files are
  exactly 18 per character across the 32 characters, in a contiguous run after
  that character's model. Even so, only 32 of 141 classified model files are
  immediately followed by an anim - the other 109 are followed by containers
  (54 same slot, 54 not) or textures - and 32 of the 576 banks have a
  *different* character's model as their nearest preceding model file.
- For the unused models this was actually about, the pattern is mostly absent:
  of 405 unclassified entries holding a model, 15 have an anim next and 346
  have a container. The rule would fire for under 4% of them, and those are
  the ones with no table to check the answer against.
- A wrong bank fails silently, which is what settles it. Tracks name a bone by
  id (`by_id.get(tr.bone)` in `c3._rig` and `dae._animations`) and bone ids are
  small integers reused across every skeleton, so a foreign bank binds 74-100%
  of its bones: Mario's binds 100% of them to Peach's, Daisy's, Bowser's and
  Wario's rigs. The result is fully rigged, plausible and wrong.
- There is already a sounder signal doing this job: 138 of those 405 unused
  models carry ANIM sections inside their own file, which is real containment,
  and `Store.banks` offers them today.

If it is ever wanted, the shape is an opt-in group in the bank dropdown -
labelled as a guess, listed under the in-file and slot-matched banks, never
preselected - not an automatic association.

## Shipping

- [x] **First tagged release**: v0.1 and v0.2 are tagged and released.
- [ ] A macOS job in CI so Mac builds are tested on every push, not only at
      release.
- [ ] Code signing / notarisation (deferred; needs an Apple developer account
      and a Windows certificate).
- [x] Windows installer, macOS disk image, in-app update check.

## Polish

- [x] ~~The deferred "Menu music" layered-song presets.~~ Not needed: a tester
      confirmed (2026-09-16) the main menu music is the sampled stereo pair
      34+35 in sound group 32 (US entry 67, 0x84f1800), not a mix of the
      sequenced songs.
- [ ] Bundle ffmpeg with the release so *Download MP4* gives H.264 out of
      the box; without it the fallback muxes Motion JPEG, which is correct
      but large and will not play in a browser.
- [ ] Stadium file variants: label the third Bowser Castle file (a daylight
      practice field) and any other odd ones by hand.
