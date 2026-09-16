"""Movie export to one file: the Motion JPEG muxer, and the ffmpeg path that
replaces it when ffmpeg is on PATH."""
import json
import struct
import sys
import wave

import pytest

from zzzzdat import hvqm, mp4

JPEG = b"\xff\xd8" + b"payload-" + b"\xff\xd9"        # not decodable, but framed like one
USEC = 33333


def _movie_folder(tmp_path, frames=7, rate=8000, channels=2, seconds=None):
    """A decoded-movie folder in the shape the helper leaves behind."""
    d = tmp_path / "movie"
    d.mkdir()
    index, blob = [], bytearray()
    for n in range(frames):
        jpg = b"\xff\xd8" + bytes([n]) * (10 + n) + b"\xff\xd9"
        index.append((len(blob), len(jpg)))
        blob += jpg
    (d / "frames.mjpg").write_bytes(bytes(blob))
    (d / "frames.idx").write_bytes(b"".join(struct.pack("<II", o, s) for o, s in index))
    n_samples = int(round((seconds if seconds is not None else frames * USEC / 1e6) * rate))
    with wave.open(str(d / "audio.wav"), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes((i * 7) % 251 for i in range(n_samples * channels * 2)))
    (d / "info.json").write_text(json.dumps(
        {"width": 64, "height": 48, "frames": frames, "usec_per_frame": USEC,
         "fps": 1e6 / USEC, "sample_rate": rate, "channels": channels}), encoding="utf-8")
    return d, index


def _boxes(data, start=0, end=None, out=None):
    """Every box as {type: [(payload start, box end)]}, checking the sizes chain."""
    end = len(data) if end is None else end
    out = {} if out is None else out
    pos = start
    while pos < end:
        size, kind = struct.unpack_from(">I4s", data, pos)
        body = pos + 8
        if size == 1:
            size = struct.unpack_from(">Q", data, pos + 8)[0]
            body = pos + 16
        assert 8 <= size and pos + size <= end, f"{kind} of {size} at {pos} overruns {end}"
        out.setdefault(kind, []).append((body, pos + size))
        if kind in (b"moov", b"trak", b"mdia", b"minf", b"stbl", b"dinf"):
            _boxes(data, body, pos + size, out)
        pos += size
    assert pos == end
    return out


def _samples(data, stsz_at, stsc_at, stco_at, wide):
    """(offset, size) per sample, resolved the way a player resolves them."""
    sample_size, count = struct.unpack_from(">II", data, stsz_at + 4)
    sizes = ([sample_size] * count if sample_size
             else list(struct.unpack_from(f">{count}I", data, stsz_at + 12)))
    n = struct.unpack_from(">I", data, stsc_at + 4)[0]
    runs = [struct.unpack_from(">III", data, stsc_at + 8 + i * 12) for i in range(n)]
    n = struct.unpack_from(">I", data, stco_at + 4)[0]
    offs = list(struct.unpack_from(f">{n}{'Q' if wide else 'I'}", data, stco_at + 8))
    per = []
    for i, (first, spc, _sdi) in enumerate(runs):
        last = runs[i + 1][0] - 1 if i + 1 < len(runs) else len(offs)
        per += [spc] * (last - first + 1)
    assert len(per) == len(offs) and sum(per) == count
    out, si = [], 0
    for ci, spc in enumerate(per):
        o = offs[ci]
        for _ in range(spc):
            out.append((o, sizes[si]))
            o += sizes[si]
            si += 1
    return out


def _mux(tmp_path, **kw):
    d, index = _movie_folder(tmp_path, **kw)
    info = json.loads((d / "info.json").read_text())
    dest = tmp_path / "out.mp4"
    mp4.write(dest, d / "frames.mjpg", index, info["usec_per_frame"],
              info["width"], info["height"], d / "audio.wav")
    return d, index, dest.read_bytes()


def test_every_frame_and_pcm_byte_survives(tmp_path):
    """The muxer re-wraps, it does not re-encode: what comes out has to be the
    frames and the PCM exactly as they went in."""
    d, index, data = _mux(tmp_path)
    boxes = _boxes(data)
    assert struct.unpack_from(">4s", data, 8)[0] == b"isom"
    wide = b"co64" in boxes
    stco = boxes.get(b"stco") or boxes[b"co64"]
    vs = _samples(data, boxes[b"stsz"][0][0], boxes[b"stsc"][0][0], stco[0][0], wide)
    aud = _samples(data, boxes[b"stsz"][1][0], boxes[b"stsc"][1][0], stco[1][0], wide)

    mjpg = (d / "frames.mjpg").read_bytes()
    assert [data[o:o + n] for o, n in vs] == [mjpg[o:o + n] for o, n in index]
    apos, asize, _ch, _rate, _bits = mp4._wav_pcm(d / "audio.wav")
    pcm = (d / "audio.wav").read_bytes()[apos:apos + asize]
    assert b"".join(data[o:o + n] for o, n in aud) == pcm

    # and every sample has to lie inside mdat, or a player reads garbage
    lo, hi = boxes[b"mdat"][0]
    assert all(lo <= o and o + n <= hi for o, n in vs + aud)


def test_codings_and_timing(tmp_path):
    _d, index, data = _mux(tmp_path)
    boxes = _boxes(data)
    codings = [struct.unpack_from(">4s", data, at + 12)[0] for at, _e in boxes[b"stsd"]]
    assert codings == [b"jpeg", b"sowt"]
    # video: one stts run of every frame, at the microsecond the decoder reported
    count, delta = struct.unpack_from(">II", data, boxes[b"stts"][0][0] + 8)
    assert (count, delta) == (len(index), USEC)
    assert struct.unpack_from(">I", data, boxes[b"mdhd"][0][0] + 12)[0] == mp4.VIDEO_TIMESCALE
    # audio: one PCM frame per sample, so the timescale is the sample rate
    assert struct.unpack_from(">I", data, boxes[b"mdhd"][1][0] + 12)[0] == 8000
    assert struct.unpack_from(">II", data, boxes[b"stts"][1][0] + 8)[1] == 1


def test_audio_longer_than_the_video_is_not_cut(tmp_path):
    """The decoded WAV can run past the last frame; dropping the tail would lose
    real audio, so it goes into a final chunk of its own."""
    d, _index, data = _mux(tmp_path, frames=3, seconds=2.0)
    boxes = _boxes(data)
    wide = b"co64" in boxes
    stco = boxes.get(b"stco") or boxes[b"co64"]
    aud = _samples(data, boxes[b"stsz"][1][0], boxes[b"stsc"][1][0], stco[1][0], wide)
    apos, asize, _ch, _r, _b = mp4._wav_pcm(d / "audio.wav")
    assert sum(n for _o, n in aud) == asize
    assert b"".join(data[o:o + n] for o, n in aud) == (d / "audio.wav").read_bytes()[apos:apos + asize]


def test_silent_movie_still_writes_one_track(tmp_path):
    _d, index, data = _mux(tmp_path, seconds=0)
    boxes = _boxes(data)
    assert len(boxes[b"trak"]) == 1
    assert struct.unpack_from(">4s", data, boxes[b"stsd"][0][0] + 12)[0] == b"jpeg"


def test_ffmpeg_command_keeps_the_frame_rate_exact(tmp_path):
    """29.97-ish rates are why: a rounded 30.0 drifts a five-minute intro out of
    sync, so the ratio the decoder reported goes in verbatim."""
    d, _index = _movie_folder(tmp_path)
    cmd = hvqm.Movie(d).ffmpeg_cmd("ffmpeg", tmp_path / "o.mp4")
    assert cmd[cmd.index("-framerate") + 1] == f"1000000/{USEC}"
    assert cmd[cmd.index("-f") + 1] == "mjpeg"
    # AAC will not take the game's 32028 Hz, so the resample is explicit
    assert cmd[cmd.index("-ar") + 1] == "48000"
    assert cmd[-1] == str(tmp_path / "o.mp4")


def _stub(tmp_path, body: str):
    p = tmp_path / ("ffmpeg.bat" if sys.platform == "win32" else "ffmpeg.sh")
    p.write_text(("@echo off\n" + body) if sys.platform == "win32" else ("#!/bin/sh\n" + body))
    p.chmod(0o755)
    return p


@pytest.mark.skipif(sys.platform != "win32", reason="stub is a .bat")
def test_ffmpeg_progress_is_reported_and_output_kept(tmp_path):
    d, index = _movie_folder(tmp_path)
    out = tmp_path / "o.mp4"
    stub = _stub(tmp_path, "echo frame=3\necho frame=7\necho progress=end\n"
                           f'echo encoded> "{out}"\n')
    seen = []
    hvqm.Movie(d)._ffmpeg(stub, out, progress=lambda a, b: seen.append((a, b)))
    assert seen == [(3, len(index)), (7, len(index))]
    assert out.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="stub is a .bat")
def test_ffmpeg_failure_raises_and_leaves_no_half_file(tmp_path):
    d, _index = _movie_folder(tmp_path)
    out = tmp_path / "o.mp4"
    stub = _stub(tmp_path, f'echo half> "{out}"\necho Unknown encoder libx264\nexit /b 1\n')
    with pytest.raises(RuntimeError, match="libx264"):
        hvqm.Movie(d)._ffmpeg(stub, out)
    assert not out.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="stub is a .bat")
def test_make_mp4_prefers_ffmpeg_then_caches(tmp_path, monkeypatch):
    d, _index = _movie_folder(tmp_path)
    m = hvqm.Movie(d)
    calls = []
    # write to whatever destination it is handed, so the .part-then-replace that
    # make_mp4 does is exercised rather than assumed
    stub = _stub(tmp_path, 'set "LAST="\nfor %%x in (%*) do set "LAST=%%~x"\n'
                           'echo via-ffmpeg> "%LAST%"\n')
    monkeypatch.setattr(hvqm, "ffmpeg_path", lambda: (calls.append(1), stub)[1])
    assert not m.has_mp4()
    assert m.make_mp4().read_text().strip() == "via-ffmpeg"
    assert m.has_mp4()
    m.make_mp4()                       # cached: ffmpeg is not asked a second time
    assert len(calls) == 1


def test_make_mp4_falls_back_to_the_muxer(tmp_path, monkeypatch):
    """No ffmpeg: the frames are muxed as they are, and the result still parses."""
    d, index = _movie_folder(tmp_path)
    monkeypatch.setattr(hvqm, "ffmpeg_path", lambda: None)
    m = hvqm.Movie(d)
    data = m.make_mp4().read_bytes()
    boxes = _boxes(data)
    assert [struct.unpack_from(">4s", data, at + 12)[0] for at, _e in boxes[b"stsd"]] == [b"jpeg", b"sowt"]
    assert not m.mp4_path().with_suffix(".part").exists()
