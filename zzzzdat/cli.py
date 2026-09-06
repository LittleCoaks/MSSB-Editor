"""Command line interface: python -m zzzzdat <command> ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .descriptors import coverage
from .paths import EXTRACT_DIR
from .store import Store


def fmt_size(n: int) -> str:
    if n >= 1 << 20:
        return f"{n / (1 << 20):.1f}M"
    if n >= 1 << 10:
        return f"{n / (1 << 10):.1f}K"
    return str(n)


def cmd_index(a):
    store = Store()
    store.rebuild_index(verify=not a.no_verify, classify=not a.no_classify, scan=not a.no_scan)


def cmd_annotate(a):
    """Re-run the unreferenced-file analysis on the existing index."""
    from .descriptors import load_index, save_index
    from .twins import annotate
    import json
    store = Store()
    from .descriptors import load_known_names
    from .store import KNOWN_NAMES_PATH
    from . import formats
    ents = load_index(store.index_path)  # the shipped index, without clone adjustments
    known = load_known_names(KNOWN_NAMES_PATH)
    for e in ents:
        if e.archive == "ZZZZ.dat":
            e.known = known.get(e.offset, "")
            if e.kind == "unknown":  # cheap re-check for formats learnt since the index was built
                try:
                    fi = formats.identify(store.data(e))
                    e.kind, e.label = fi.kind, fi.label or e.label
                except Exception:
                    pass
    annotate(store, ents, print)
    meta = json.loads(store.index_path.read_text(encoding="utf-8")).get("meta", {})
    save_index(ents, store.index_path, meta)
    print(f"wrote {store.index_path}")


def cmd_thumbs(a):
    from .thumbs import build_all
    store = Store()
    print(f"{build_all(store, force=a.force)} thumbnails written")


def cmd_list(a):
    store = Store()
    ents = [e for e in store.entries if a.all or e.archive != "aaaa.dat"]
    if a.kind:
        ents = [e for e in ents if e.kind == a.kind]
    if a.module:
        ents = [e for e in ents if e.module == a.module]
    if a.grep:
        g = a.grep.lower()
        ents = [e for e in ents if g in e.symbol.lower() or g in e.name or g in e.known.lower()
                or any(g in n.lower() for n in e.names)]
    print(f"{'id':>5} {'offset':>10} {'size':>8} {'disc':>8} {'c':1} {'kind':10} {'tex':>4} {'aud':>3} {'label':22} symbol")
    for e in ents:
        print(f"{e.id:5d} {e.offset:#10x} {fmt_size(e.size):>8} {fmt_size(e.disc_size):>8} "
              f"{'z' if e.compressed else '-'} {e.kind:10} {e.ntex:4d} {e.naud:3d} {(e.known or e.label):22} {e.symbol}")
    print(f"{len(ents)} entries")


def cmd_info(a):
    store = Store()
    e = store.get(a.entry)
    print(f"entry {e.id}  {e.archive} @ {e.offset:#x}  disc {e.disc_size:#x}  size {e.size:#x}  "
          f"{'LZSS L=%d R=%d' % (e.lookback_bits, e.repeat_bits) if e.compressed else 'stored'}")
    print("kind:", e.kind)
    if e.known:
        print("known as:", e.known)
    if e.names:
        print("names:", ", ".join(e.names))
    for r in e.refs:
        print("  ref:", r)
    fi = store.info(e)
    if fi.hvqm4:
        for k, v in fi.hvqm4.items():
            print(f"  {k}: {v}")
    for s in fi.sections:
        print(f"  section {s.index:2d} @ {s.offset:#8x} size {s.size:#8x} magic {s.magic:#010x} {s.kind}"
              + (f" ({len(s.textures)} textures)" if s.textures else ""))
    for md in store.models(e):
        print(f"  model: section {md['section']} @ {md['offset']:#x}: {', '.join(md['meshes'])} ({md['triangles']} triangles, "
              f"{len(md['textures'])} textures)")
    for n, st in enumerate(fi.audio):
        print(f"  audio {n}: {st['kind']} {st['rate']} Hz {st['channels']}ch {st['seconds']} s @ {st['pos']:#x}"
              + (" loop" if st.get("loop") else ""))
    for n, (sec, t) in enumerate(fi.all_textures()):
        if n >= a.max_textures:
            print(f"  ... {len(fi.all_textures()) - n} more textures")
            break
        print(f"  tex {n:3d}: {t.width}x{t.height} {t.fmt_name} mips={t.mips} @ {t.abs_data_offset:#x}"
              + (f" tlut {t.tlut_count}x{t.tlut_fmt}" if t.tlut_count else ""))


def cmd_hexdump(a):
    store = Store()
    e = store.get(a.entry)
    data = store.raw(e) if a.raw else store.data(e)
    off = a.offset
    end = min(len(data), off + a.length)
    while off < end:
        row = data[off:min(off + 16, end)]
        print(f"{off:08x}  {row.hex(' '):47}  {''.join(chr(c) if 32 <= c < 127 else '.' for c in row)}")
        off += 16


def cmd_extract(a):
    store = Store()
    dest = Path(a.out) if a.out else EXTRACT_DIR
    for name in a.entries:
        e = store.get(name)
        for p in store.extract(e, dest, raw=a.raw, png=a.png, wav=a.wav, model=a.model):
            print(p)


def cmd_extract_all(a):
    store = Store()
    dest = Path(a.out) if a.out else EXTRACT_DIR
    ents = store.zzzz_entries()
    if a.kind:
        ents = [e for e in ents if e.kind == a.kind]
    n = 0
    for e in ents:
        if e.size > a.max_size:
            print(f"skip {e.id} ({fmt_size(e.size)})")
            continue
        try:
            store.extract(e, dest, raw=a.raw, png=a.png, wav=a.wav, model=a.model)
            n += 1
        except Exception as ex:
            print(f"entry {e.id}: {ex}", file=sys.stderr)
    print(f"extracted {n} entries to {dest}")


def cmd_textures(a):
    store = Store()
    e = store.get(a.entry)
    dest = Path(a.out) if a.out else EXTRACT_DIR / (store.file_name(e).rsplit(".", 1)[0] + "_tex")
    paths = store.extract_textures(e, dest)
    print(f"{len(paths)} textures -> {dest}")


def cmd_wav(a):
    store = Store()
    e = store.get(a.entry)
    dest = Path(a.out) if a.out else EXTRACT_DIR / (store.file_name(e).rsplit(".", 1)[0] + "_wav")
    if a.n is None:
        paths = store.extract_audio(e, dest, a.seconds)
    else:
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / f"{a.n:02d}.wav"
        p.write_bytes(store.wav(e, a.n, a.seconds))
        paths = [p]
    for p in paths:
        print(p)


def cmd_model(a):
    store = Store()
    e = store.get(a.entry)
    dest = Path(a.out) if a.out else EXTRACT_DIR / (store.file_name(e).rsplit(".", 1)[0] + "_model")
    for p in store.extract_models(e, dest, a.format):
        print(p)
    if not store.models(e):
        print("no GeoPalette sections in this entry")


def cmd_game(a):
    from .disc import current_game, set_game
    if a.path:
        g = set_game(a.path)
        print("game set")
    else:
        g = current_game()
    for k, v in g.describe().items():
        print(f"  {k:15} {v}")


def cmd_dump(a):
    from .disc import dump_iso
    dest = dump_iso(a.out, a.only, log=print)
    print(f"dumped to {dest} (now paired with the ISO for editing)")


def cmd_music(a):
    from . import music
    root = music.game_root() if not a.root else music.set_game_root(a.root)
    if a.music_cmd == "root":
        print(root or "no game root found: run `zzzzdat dump` or `zzzzdat music root <folder>`")
        return
    if root is None:
        print("no game dump found. Run `python -m zzzzdat dump --only snd/` (plus sys/) or "
              "`python -m zzzzdat music --root <dump> ...`", file=sys.stderr)
        sys.exit(1)
    if a.music_cmd == "list":
        print(f"game root: {root}")
        print(f"{'file':20} {'track':24} {'type':16} {'status':9} {'size':>10} {'stock':>10} note")
        for t in music.status(root):
            status = "missing" if not t["exists"] else ("modified" if t["modified"] else ("custom" if t["custom"] else "stock"))
            note = "SIZE != DOL table" if t["mismatch"] else ("" if t["in_table"] or t["custom"] else "not in DOL table")
            print(f"{t['file']:20} {t['label']:24} {t['category']:16} {status:9} {t['size']:>10} {t['stock_size'] or '-':>10} {note}")
    elif a.music_cmd == "install":
        def prog(done, total):
            print(f"\r  encoding {100 * done // max(total, 1):3d}%", end="", flush=True)
        r = music.install(a.audio, root, a.track, progress=prog, pad_to_stock=not a.no_pad)
        print()
        print(f"wrote {r['destination']} ({r['bytes']:,} bytes, {r['seconds']:.1f} s"
              f"{', resampled from %d Hz' % r['source_rate'] if r['resampled'] else ''})")
        if r["backup"]:
            print(f"original backed up to {r['backup']}")
        if r["padded"]:
            print("padded with silence to the stock length")
        if r["truncated"]:
            print("WARNING: longer than the stock track; the game will loop at the stock length")
        if r["gecko"]:
            print("Gecko lines for a tight loop / full length:")
            for g in r["gecko"]:
                print("  " + g)
    elif a.music_cmd == "restore":
        music.restore(root, a.track)
        print(f"restored {a.track}")
    elif a.music_cmd == "export":
        from .music import installer
        out = a.out or (str(EXTRACT_DIR / (a.track.rsplit(".", 1)[0] + ".wav")))
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        installer.extract(str(root), a.track, out)
        print(out)


def cmd_replace(a):
    from .edit import Editor
    store = Store()
    e = store.get(a.entry)
    ed = Editor(store.game)
    r = ed.replace(e, Path(a.file).read_bytes())
    print(f"replaced entry {e.id}: {r['size']:,} bytes -> {r['disc_size']:,} on disc at {r['offset']:#x} "
          f"({'in place' if r['in_place'] else 'appended to ZZZZ.dat'}), {r['descriptors']} descriptor(s) updated")


def cmd_replace_texture(a):
    from .edit import Editor
    from .texedit import replace_texture
    store = Store()
    e = store.get(a.entry)
    new, info = replace_texture(store.data(e), store.info(e), a.texture, Path(a.png).read_bytes())
    r = Editor(store.game).replace(e, new)
    store.forget(e)
    print(f"texture {info.n} of entry {e.id}: {info.width}x{info.height} {info.fmt}, {info.levels} level(s)"
          + (f", resized from {info.source_width}x{info.source_height}" if info.resized else "")
          + (f", {info.palette} palette colours" if info.palette else "")
          + f"; entry written {'in place' if r['in_place'] else 'appended to ZZZZ.dat'}, {r['descriptors']} descriptor(s) updated")


def cmd_characters(a):
    from .clone import slot_table
    from .edit import Editor, EditError
    store = Store()
    try:
        ed = Editor(store.game)
    except EditError:
        ed = None
    for row in slot_table(ed):
        note = ""
        if row["clone_of"] is not None:
            note = f"  <- clone of {row['clone_of']} {row['clone_of_name']} ({'copied' if row['copy'] else 'shared'})"
        print(f"{row['slot']:2d} {row['name']}{note}")


def cmd_clone_character(a):
    from .clone import Cloner
    from .edit import Editor
    store = Store()
    r = Cloner(Editor(store.game)).clone(a.source, a.target, copy=not a.share)
    print(f"slot {a.target} now plays as slot {a.source}: {r['copied']} files copied ({r['appended_bytes']:,} bytes appended), "
          f"{len(r['inplace'])} ARAM entries copied in place, {r['shared']} descriptors shared")


def cmd_restore_character(a):
    from .clone import Cloner
    from .edit import Editor
    store = Store()
    Cloner(Editor(store.game)).restore(a.target)
    print(f"slot {a.target} restored")


def cmd_restore_entry(a):
    from .edit import Editor
    store = Store()
    e = store.get(a.entry)
    Editor(store.game).restore(e)
    print(f"restored entry {e.id}")


def cmd_modified(a):
    from .edit import Editor
    store = Store()
    ids = store.modified_ids()
    print(f"{len(ids)} modified entr{'y' if len(ids) == 1 else 'ies'}")
    for i in ids:
        e = store.by_id.get(i)
        print(f"  {i}: {e.known or e.label or e.symbol if e else '?'}")


def cmd_layout(a):
    store = Store()
    ents = sorted(store.zzzz_entries(), key=lambda e: e.offset)
    cov = coverage(ents, store.archive.size)
    cur = 0
    for e in ents:
        if e.offset > cur + 0x800:
            print(f"  GAP     {cur:#10x}-{e.offset:#10x} {fmt_size(e.offset - cur):>8}")
        print(f"  {e.id:5d} {e.offset:#10x}-{e.end:#10x} {fmt_size(e.disc_size):>8} {e.kind:10} {e.symbol}")
        cur = max(cur, e.end)
    if cur < store.archive.size:
        print(f"  GAP     {cur:#10x}-{store.archive.size:#10x} {fmt_size(store.archive.size - cur):>8}")
    print(f"covered {cov['covered'] / 1e6:.1f} MB of {store.archive.size / 1e6:.1f} MB; "
          f"{cov['gaps']} gaps totalling {cov['gap_bytes'] / 1e6:.1f} MB")


def cmd_app(a):
    from .app import run
    run(a.port, a.width, a.height)


def cmd_serve(a):
    from .server import serve
    serve(a.port, open_browser=not a.no_browser)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="zzzzdat", description="Browse, view and extract MSSB's ZZZZ.dat")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("annotate", help="re-run the unreferenced-file analysis (twins, animation sources) on the index")
    s.set_defaults(fn=cmd_annotate)
    s = sub.add_parser("index", help="(re)build index/GYQE01.json by scanning the game executables")
    s.add_argument("--no-verify", action="store_true", help="skip decode verification (faster, noisier)")
    s.add_argument("--no-classify", action="store_true", help="skip content classification")
    s.add_argument("--no-scan", action="store_true", help="skip the AdGCForm and brute-force gap scans")
    s.set_defaults(fn=cmd_index)

    s = sub.add_parser("thumbs", help="build this game's thumbnail cache now (the app does it in the background)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_thumbs)

    s = sub.add_parser("list", help="list entries")
    s.add_argument("--kind")
    s.add_argument("--module", help="dol, game, menus or debug")
    s.add_argument("--grep", help="substring of symbol/name")
    s.add_argument("--all", action="store_true", help="include the aaaa.dat REL entries")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("info", help="details for one entry")
    s.add_argument("entry")
    s.add_argument("--max-textures", type=int, default=40)
    s.set_defaults(fn=cmd_info)

    s = sub.add_parser("hexdump", help="hex dump of an entry's (decompressed) contents")
    s.add_argument("entry")
    s.add_argument("--offset", type=lambda v: int(v, 0), default=0)
    s.add_argument("--length", type=lambda v: int(v, 0), default=0x100)
    s.add_argument("--raw", action="store_true", help="dump the on-disc bytes instead")
    s.set_defaults(fn=cmd_hexdump)

    s = sub.add_parser("extract", help="extract one or more entries")
    s.add_argument("entries", nargs="+")
    s.add_argument("-o", "--out")
    s.add_argument("--raw", action="store_true", help="write the compressed on-disc bytes")
    s.add_argument("--png", action="store_true", help="also decode textures to PNG")
    s.add_argument("--wav", action="store_true", help="also decode audio to WAV")
    s.add_argument("--model", choices=["glb", "obj", "both"], help="also export models")
    s.set_defaults(fn=cmd_extract)

    s = sub.add_parser("extract-all", help="extract every indexed entry")
    s.add_argument("-o", "--out")
    s.add_argument("--kind")
    s.add_argument("--raw", action="store_true")
    s.add_argument("--png", action="store_true")
    s.add_argument("--wav", action="store_true")
    s.add_argument("--model", choices=["glb", "obj", "both"])
    s.add_argument("--max-size", type=lambda v: int(v, 0), default=1 << 30)
    s.set_defaults(fn=cmd_extract_all)

    s = sub.add_parser("model", help="export an entry's models (glTF binary and/or OBJ+MTL+PNG)")
    s.add_argument("entry")
    s.add_argument("--format", choices=["glb", "obj", "both"], default="glb")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_model)

    s = sub.add_parser("wav", help="decode an entry's audio to WAV (disc .adp music or DSP streams)")
    s.add_argument("entry")
    s.add_argument("-n", type=int, help="stream index (default: all)")
    s.add_argument("--seconds", type=float, help="only the first N seconds")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_wav)

    s = sub.add_parser("textures", help="decode an entry's textures to PNG files")
    s.add_argument("entry")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_textures)

    s = sub.add_parser("game", help="show or set the game (an .iso/.gcm or an extracted folder)")
    s.add_argument("path", nargs="?")
    s.set_defaults(fn=cmd_game)

    s = sub.add_parser("dump", help="extract the game's files from the ISO into a Dolphin-style folder (needed for editing)")
    s.add_argument("-o", "--out", help="destination (default: '<iso name> (extracted)' beside the ISO)")
    s.add_argument("--only", help="only paths starting with this, e.g. snd/")
    s.set_defaults(fn=cmd_dump)

    s = sub.add_parser("music", help="custom music: list, install, restore, export tracks (from MSSB-Custom-Music)")
    s.add_argument("--root", help="game folder with snd/my_snd_h (also sets the editor's game)")
    ms = s.add_subparsers(dest="music_cmd", required=True)
    ms.add_parser("list", help="every stock track and custom slot with its status")
    ms.add_parser("root", help="show the game root in use")
    m = ms.add_parser("install", help="encode an audio file and install it as a track")
    m.add_argument("audio")
    m.add_argument("--track", required=True, help="e.g. mario_01_h.adp or custom_01_h.adp")
    m.add_argument("--no-pad", action="store_true", help="do not pad a short track to the stock length")
    m = ms.add_parser("restore", help="put the original track back")
    m.add_argument("--track", required=True)
    m = ms.add_parser("export", help="decode a track from the dump to WAV")
    m.add_argument("--track", required=True)
    m.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_music)

    s = sub.add_parser("replace", help="replace an entry's contents with a file (compressed as needed, descriptors repointed)")
    s.add_argument("entry")
    s.add_argument("file")
    s.set_defaults(fn=cmd_replace)

    s = sub.add_parser("replace-texture", help="replace one texture of an entry with a PNG (same size/format, resized if needed)")
    s.add_argument("entry")
    s.add_argument("texture", type=int, help="texture number as shown by `info`")
    s.add_argument("png")
    s.set_defaults(fn=cmd_replace_texture)

    s = sub.add_parser("characters", help="list the 54 character slots and their clone state")
    s.set_defaults(fn=cmd_characters)

    s = sub.add_parser("clone-character", help="make a slot play as another character (DOL tables; files copied unless --share)")
    s.add_argument("source", type=int, help="source slot 0..53")
    s.add_argument("target", type=int, help="target slot 0..53")
    s.add_argument("--share", action="store_true", help="point at the source files instead of copying them")
    s.set_defaults(fn=cmd_clone_character)

    s = sub.add_parser("restore-character", help="undo a character clone")
    s.add_argument("target", type=int)
    s.set_defaults(fn=cmd_restore_character)

    s = sub.add_parser("restore-entry", help="undo a replacement")
    s.add_argument("entry")
    s.set_defaults(fn=cmd_restore_entry)

    s = sub.add_parser("modified", help="list replaced entries")
    s.set_defaults(fn=cmd_modified)

    s = sub.add_parser("layout", help="print the archive layout and coverage")
    s.set_defaults(fn=cmd_layout)

    s = sub.add_parser("app", help="open the viewer in a desktop window (pywebview)")
    s.add_argument("--port", type=int, help="fixed port (default: any free port)")
    s.add_argument("--width", type=int, default=1400)
    s.add_argument("--height", type=int, default=900)
    s.set_defaults(fn=cmd_app)

    s = sub.add_parser("serve", help="start the web browser UI")
    s.add_argument("--port", type=int, default=8420)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    a = ap.parse_args(argv or (sys.argv[1:] or ["app"]))
    a.fn(a)


if __name__ == "__main__":
    main()
