"""A minimal MP4 (ISO base media) writer for Motion JPEG video and PCM audio.

The HVQM4 helper leaves a movie as JPEG frames plus a WAV (see hvqm.py). With
ffmpeg on PATH those become a real H.264/AAC file; without it this module packs
the same frames into an MP4 unchanged, so the feature works on a machine that
has nothing installed. Nothing is re-encoded, which is why it is quick and
lossless - and also why the result is as big as the frames are, a bit over
200 KB each at 640x480.

The video sample entry is `jpeg` and the audio one is `sowt` (the little-endian
PCM16 a WAV already holds), both QuickTime codings that the ISO container
carries perfectly well; `qt  ` is in the compatible brands so a reader knows to
expect them. ffmpeg, VLC and the editors read this; a browser will not, since
none of them decode Motion JPEG.

`mdat` is written first and streamed straight from the frame file, so a
1.2 GB movie never has to be held in memory; the tables that point into it are
gathered as it goes and `moov` is appended once the offsets are known.
"""
from __future__ import annotations

import struct
from pathlib import Path

# the sample tables index into mdat with file offsets, so a movie past 4 GB
# needs the 64-bit flavour of the chunk offset box
U32_MAX = 0xFFFFFFFF
VIDEO_TIMESCALE = 1_000_000        # frame durations arrive as whole microseconds
MOVIE_TIMESCALE = 1000


def _box(kind: bytes, *parts: bytes) -> bytes:
    body = b"".join(parts)
    return struct.pack(">I4s", len(body) + 8, kind) + body


def _full(kind: bytes, version: int, flags: int, *parts: bytes) -> bytes:
    return _box(kind, struct.pack(">B3s", version, flags.to_bytes(3, "big")), *parts)


def _str_box(kind: bytes, version: int, flags: int, *parts: bytes) -> bytes:
    return _full(kind, version, flags, *parts)


class _Track:
    """The sample tables for one track, filled in as mdat is written."""

    def __init__(self, kind: bytes, timescale: int):
        self.kind = kind
        self.timescale = timescale
        self.sizes: list[int] = []       # one per sample
        self.chunks: list[tuple[int, int]] = []   # (file offset, sample count)

    def add_chunk(self, offset: int, sizes: list[int]) -> None:
        if not sizes:
            return
        self.chunks.append((offset, len(sizes)))
        self.sizes += sizes

    def stsc(self) -> bytes:
        """One entry per run of chunks holding the same number of samples."""
        runs = []
        for i, (_off, n) in enumerate(self.chunks):
            if not runs or runs[-1][1] != n:
                runs.append((i + 1, n))
        return _full(b"stsc", 0, 0, struct.pack(">I", len(runs)),
                     b"".join(struct.pack(">III", a, b, 1) for a, b in runs))

    def stsz(self) -> bytes:
        uniform = self.sizes and len(set(self.sizes)) == 1
        if uniform:
            return _full(b"stsz", 0, 0, struct.pack(">II", self.sizes[0], len(self.sizes)))
        return _full(b"stsz", 0, 0, struct.pack(">II", 0, len(self.sizes)),
                     b"".join(struct.pack(">I", s) for s in self.sizes))

    def stco(self) -> bytes:
        offs = [o for o, _n in self.chunks]
        if offs and max(offs) > U32_MAX:
            return _full(b"co64", 0, 0, struct.pack(">I", len(offs)),
                         b"".join(struct.pack(">Q", o) for o in offs))
        return _full(b"stco", 0, 0, struct.pack(">I", len(offs)),
                     b"".join(struct.pack(">I", o) for o in offs))


def _ftyp() -> bytes:
    return _box(b"ftyp", b"isom", struct.pack(">I", 0x200), b"isom", b"iso2", b"mp41", b"qt  ")


def _visual_entry(width: int, height: int) -> bytes:
    name = b"Motion JPEG"
    return _box(b"jpeg",
                b"\0" * 6, struct.pack(">H", 1),          # reserved, data_reference_index
                b"\0" * 16,                                # pre_defined / reserved
                struct.pack(">HH", width, height),
                struct.pack(">II", 0x00480000, 0x00480000),  # 72 dpi
                b"\0" * 4,
                struct.pack(">H", 1),                      # frame_count
                bytes([len(name)]) + name + b"\0" * (31 - len(name)),
                struct.pack(">Hh", 0x0018, -1))            # depth, pre_defined


def _audio_entry(channels: int, rate: int, bits: int) -> bytes:
    return _box(b"sowt",
                b"\0" * 6, struct.pack(">H", 1),
                struct.pack(">HHI", 0, 0, 0),              # version, revision, vendor
                struct.pack(">HH", channels, bits),
                struct.pack(">HH", 0, 0),                  # compression_id, packet_size
                struct.pack(">I", rate << 16))             # 16.16 fixed


def _stbl(entry: bytes, t: _Track, stts: bytes) -> bytes:
    return _box(b"stbl", _full(b"stsd", 0, 0, struct.pack(">I", 1), entry),
                stts, t.stsc(), t.stsz(), t.stco())


def _mdia(t: _Track, handler: bytes, name: bytes, duration: int, header: bytes, stbl: bytes) -> bytes:
    mdhd = _full(b"mdhd", 0, 0, struct.pack(">IIIIHH", 0, 0, t.timescale, duration, 0x55C4, 0))
    hdlr = _full(b"hdlr", 0, 0, struct.pack(">I4s", 0, handler) + b"\0" * 12 + name + b"\0")
    dinf = _box(b"dinf", _full(b"dref", 0, 0, struct.pack(">I", 1), _full(b"url ", 0, 1)))
    return _box(b"mdia", mdhd, hdlr, _box(b"minf", header, dinf, stbl))


UNITY = struct.pack(">9i", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)


def _trak(track_id: int, movie_duration: int, mdia: bytes, width: int = 0, height: int = 0) -> bytes:
    tkhd = _full(b"tkhd", 0, 7,      # enabled, in movie, in preview
                 struct.pack(">IIIII", 0, 0, track_id, 0, movie_duration)
                 + b"\0" * 8 + struct.pack(">hhhh", 0, 0, 0 if width else 0x0100, 0)
                 + UNITY + struct.pack(">II", width << 16, height << 16))
    return _box(b"trak", tkhd, mdia)


def _wav_pcm(path: Path) -> tuple[int, int, int, int, int]:
    """(data offset, data size, channels, sample rate, bits) of a PCM WAV."""
    with open(path, "rb") as f:
        if f.read(4) != b"RIFF" or f.read(8)[4:] != b"WAVE":
            raise ValueError(f"{path.name} is not a WAV")
        channels = rate = bits = 0
        while True:
            head = f.read(8)
            if len(head) < 8:
                raise ValueError(f"{path.name} has no data chunk")
            kind, size = struct.unpack("<4sI", head)
            if kind == b"fmt ":
                fmt = f.read(size)
                channels, rate = struct.unpack_from("<HI", fmt, 2)
                bits = struct.unpack_from("<H", fmt, 14)[0]
            elif kind == b"data":
                return f.tell(), size, channels, rate, bits
            else:
                f.seek(size + (size & 1), 1)


def write(dest: Path, frames_path: Path, index: list[tuple[int, int]], usec_per_frame: int,
          width: int, height: int, wav_path: Path, progress=None) -> Path:
    """Mux `index` frames of `frames_path` and the PCM of `wav_path` into `dest`.

    `index` is (offset, size) per frame in display order, as frames.idx holds
    it. Video and audio are interleaved a second at a time so the file plays
    without seeking around."""
    apos, asize, channels, rate, bits = _wav_pcm(wav_path)
    block = channels * bits // 8                     # bytes per PCM frame
    total_pcm = asize // block if block else 0
    per_chunk = max(1, round(1_000_000 / usec_per_frame))   # a second of video
    vid = _Track(b"vide", VIDEO_TIMESCALE)
    aud = _Track(b"soun", rate or 1)

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as out, open(frames_path, "rb") as fr, open(wav_path, "rb") as wf:
        out.write(_ftyp())
        mdat_at = out.tell()
        # the size is not known until the samples are in, so reserve the 64-bit
        # form and come back for it
        out.write(struct.pack(">I4sQ", 1, b"mdat", 0))
        wf.seek(apos)
        audio_left = asize
        for first in range(0, len(index), per_chunk):
            group = index[first:first + per_chunk]
            offset, sizes = out.tell(), []
            for off, size in group:
                fr.seek(off)
                out.write(fr.read(size))
                sizes.append(size)
            vid.add_chunk(offset, sizes)
            # the audio that plays under those frames, to the nearest PCM frame
            want = min(audio_left, block * round(len(group) * usec_per_frame * rate / 1_000_000))
            if want:
                offset = out.tell()
                out.write(wf.read(want))
                audio_left -= want
                aud.add_chunk(offset, [block] * (want // block))
            if progress:
                progress(min(first + per_chunk, len(index)), len(index))
        if audio_left > 0:                            # a tail longer than the video
            offset = out.tell()
            out.write(wf.read(audio_left))
            aud.add_chunk(offset, [block] * (audio_left // block))
        end = out.tell()
        out.seek(mdat_at + 8)
        out.write(struct.pack(">Q", end - mdat_at))
        out.seek(end)

        vdur = len(index) * usec_per_frame
        seconds = max(vdur / VIDEO_TIMESCALE, total_pcm / rate if rate else 0)
        movie_dur = round(seconds * MOVIE_TIMESCALE)
        mvhd = _full(b"mvhd", 0, 0, struct.pack(">IIII", 0, 0, MOVIE_TIMESCALE, movie_dur)
                     + struct.pack(">Ihh", 0x10000, 0x0100, 0) + b"\0" * 8 + UNITY
                     + b"\0" * 24 + struct.pack(">I", 3))
        vstts = _full(b"stts", 0, 0, struct.pack(">III", 1, len(index), usec_per_frame))
        astts = _full(b"stts", 0, 0, struct.pack(">III", 1, len(aud.sizes), 1))
        traks = [_trak(1, movie_dur,
                       _mdia(vid, b"vide", b"Video", vdur, _full(b"vmhd", 0, 1, b"\0" * 8),
                             _stbl(_visual_entry(width, height), vid, vstts)),
                       width, height)]
        if aud.sizes:
            traks.append(_trak(2, movie_dur,
                               _mdia(aud, b"soun", b"Sound", len(aud.sizes),
                                     _box(b"smhd", b"\0" * 8),
                                     _stbl(_audio_entry(channels, rate, bits), aud, astts))))
        out.write(_box(b"moov", mvhd, *traks))
    return dest
