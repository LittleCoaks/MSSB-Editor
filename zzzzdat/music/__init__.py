"""Custom music: encode audio to the game's DTK .adp streams and install them
into a dumped game folder. Merged from LittleCoaks/MSSB-Custom-Music; the
encoder, resampler, DOL stream-table reader and installer are that project's
modules, kept intact under this package.

Public surface used by the CLI and the UI:
    game_root()                      -> Path | None   folder holding snd/my_snd_h
    status(root)                     -> list[dict]    every stock track and custom slot
    install(audio, root, track, ...) -> dict          encode + write + backup
    restore(root, track)             -> None
"""
from __future__ import annotations

import filecmp
import os
from pathlib import Path

from . import audioin, dolinfo, dtkadpcm, installer, tracks
from ..disc import current_game, set_game

InstallError = installer.InstallError


def game_root() -> Path | None:
    """The writable game folder (files/ root with snd/my_snd_h), from the
    editor's game setting. None when only an ISO is configured."""
    g = current_game()
    if g.files_dir:
        r = tracks.find_root(str(g.files_dir))
        if r:
            return Path(r)
    return None


def set_game_root(path: str) -> Path:
    r = tracks.find_root(path)
    if not r:
        raise InstallError(f"{path} does not contain snd/my_snd_h with the game's music")
    g = current_game()
    if g.layout == "iso" and g.iso:
        set_game(g.iso, Path(r).parent if Path(r).name == "files" else Path(r))
    else:
        set_game(Path(r).parent if (Path(r).name == "files" and (Path(r).parent / "sys").is_dir()) else Path(r))
    return Path(r)


def status(root: Path | str) -> list[dict]:
    root = str(root)
    table, dol_path = dolinfo.read_table(root)
    snd = tracks.snd_dir(root)
    out = []
    for name, label in tracks.STOCK_TRACKS + tracks.CUSTOM_SLOTS:
        p = os.path.join(snd, name)
        exists = os.path.isfile(p)
        size = os.path.getsize(p) if exists else 0
        info = table.get(name)
        bpath = installer.backup_path(root, name)
        backup = os.path.isfile(bpath)
        modified = backup and exists and not filecmp.cmp(bpath, p, shallow=False)
        out.append({
            "file": name, "label": label, "custom": name.startswith("custom_"), "category": tracks.category(name),
            "exists": exists, "size": size,
            "seconds": round(dtkadpcm.decode.__globals__["SAMPLES_PER_FRAME"] * (size // dtkadpcm.FRAME_BYTES) / dtkadpcm.SAMPLE_RATE, 2) if exists else 0,
            "stock_size": info["size"] if info else None,
            "loop_end": info["loop_end"] if info else None,
            "in_table": info is not None,
            "modified": modified,
            "has_backup": backup,
            "mismatch": bool(info and exists and info["size"] != size),
        })
    return out


def install(audio_path: str, root: Path | str, track: str, progress=None, pad_to_stock: bool = True) -> dict:
    return installer.install(audio_path, str(root), track, progress=progress, pad_to_stock=pad_to_stock)


def restore(root: Path | str, track: str) -> None:
    installer.restore_backup(str(root), track)


def backends() -> dict:
    return {"numpy": dtkadpcm._np is not None, "backends": audioin.available_backends(),
            "can_install_decoder": audioin.can_install_decoder()}
