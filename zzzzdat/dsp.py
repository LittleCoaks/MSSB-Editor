"""Nintendo DSP-ADPCM decoding and WAV output.

The standard 0x60-byte DSPADPCM header (as written by Nintendo's dspadpcm
tool) is:

    u32 sample_count      u32 nibble_count     u32 sample_rate
    u16 loop_flag         u16 format (0 = ADPCM)
    u32 loop_start        u32 loop_end         u32 current_address
    s16 coef[16]
    u16 gain  u16 pred_scale  s16 hist1  s16 hist2
    u16 loop_pred_scale  s16 loop_hist1  s16 loop_hist2
    u16 pad[11]

Data follows as 8-byte frames: 1 header byte (predictor index << 4 | scale)
and 14 4-bit nibbles = 14 samples.

The `AdGCForm` bank in ZZZZ.dat wraps exactly this: 8-byte magic, 0x20 bytes
of form header, then the DSP header at 0x28 and frames at 0x88.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

HEADER_SIZE = 0x60
COMMON_RATES = {8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000}
ADGC_DSP_OFFSET = 0x28


@dataclass
class DspHeader:
    sample_count: int
    nibble_count: int
    sample_rate: int
    loop_flag: int
    format: int
    loop_start: int
    loop_end: int
    coefs: tuple
    pred_scale: int
    hist1: int
    hist2: int

    @property
    def data_size(self) -> int:
        return (self.nibble_count + 1) // 2

    @property
    def seconds(self) -> float:
        return self.sample_count / self.sample_rate if self.sample_rate else 0.0


def parse_header(data: bytes, pos: int = 0) -> DspHeader | None:
    if pos + HEADER_SIZE > len(data):
        return None
    f = struct.unpack_from(">IIIHHIII16hHHhhHhh", data, pos)
    sc, nc, rate, loop, fmt, ls, le, ca = f[:8]
    coefs = f[8:24]
    gain, ps, h1, h2 = f[24:28]
    if fmt != 0 or rate not in COMMON_RATES or sc == 0 or nc < sc or loop > 1:
        return None
    # nibbles = samples * 16/14 rounded up to a frame, give or take one frame
    expect = (sc + 13) // 14 * 16
    if not (sc <= nc <= expect + 16) or nc // 2 > len(data) - pos:
        return None
    if loop and not (ls <= le <= nc):
        return None
    if all(c == 0 for c in coefs):
        return None
    return DspHeader(sc, nc, rate, loop, fmt, ls, le, coefs, ps, h1, h2)


def decode(hdr: DspHeader, frames: bytes, max_samples: int | None = None) -> bytes:
    """Decode ADPCM frames to little-endian 16-bit PCM."""
    n = hdr.sample_count if max_samples is None else min(hdr.sample_count, max_samples)
    out = bytearray(n * 2)
    coefs = hdr.coefs
    h1, h2 = hdr.hist1, hdr.hist2
    pos = 0
    i = 0
    nib = [0] * 14
    pack_into = struct.pack_into
    while i < n and pos + 8 <= len(frames):
        head = frames[pos]
        scale = 1 << (head & 0xF)
        ci = (head >> 4) * 2
        c1, c2 = coefs[ci], coefs[ci + 1]
        for k in range(7):
            b = frames[pos + 1 + k]
            nib[k * 2] = b >> 4
            nib[k * 2 + 1] = b & 0xF
        pos += 8
        for v in nib:
            if v >= 8:
                v -= 16
            s = (v * scale * 2048 + c1 * h1 + c2 * h2 + 1024) >> 11
            if s > 32767:
                s = 32767
            elif s < -32768:
                s = -32768
            h2, h1 = h1, s
            pack_into("<h", out, i * 2, s)
            i += 1
            if i >= n:
                break
    return bytes(out[:i * 2])


def wav(pcm: bytes, rate: int, channels: int = 1) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
            + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * channels * 2, channels * 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def find_dsp_streams(data: bytes, step: int = 4, limit: int = 256) -> list[tuple[int, DspHeader]]:
    """Locate DSPADPCM headers anywhere in a blob (headers are 4-byte aligned)."""
    found = []
    pos = 0
    end = len(data) - HEADER_SIZE
    while pos <= end and len(found) < limit:
        h = parse_header(data, pos)
        if h and pos + HEADER_SIZE + h.data_size <= len(data) + 16:
            found.append((pos, h))
            pos += HEADER_SIZE + h.data_size
            pos = (pos + 3) & ~3
        else:
            pos += step
    return found


def decode_stream(data: bytes, pos: int, max_seconds: float | None = None) -> tuple[DspHeader, bytes]:
    h = parse_header(data, pos)
    if h is None:
        raise ValueError(f"no DSP header at {pos:#x}")
    frames = data[pos + HEADER_SIZE:pos + HEADER_SIZE + h.data_size]
    n = None if max_seconds is None else int(max_seconds * h.sample_rate)
    return h, wav(decode(h, frames, n), h.sample_rate)


# ------------------------------------------------------------------ DTK --
# The .adp files under snd/ on the disc are GameCube DTK streams: raw 32-byte
# frames (no file header), 48 kHz stereo. Bytes 0/1 are the channel 0/1 frame
# headers (predictor << 4 | shift), bytes 2/3 repeat them, and bytes 4..31
# carry 28 sample pairs: low nibble = channel 0, high nibble = channel 1.
# Arithmetic follows vgmstream's ngc_dtk_decoder.c (XA coefficients, history
# kept at 6 extra bits of precision).

DTK_RATE = 48000
DTK_FRAME = 32
DTK_COEFS = ((0, 0), (60, 0), (115, 52), (98, 55))


def dtk_decode(data: bytes, max_frames: int | None = None) -> bytes:
    """Decode DTK frames to interleaved little-endian 16-bit stereo PCM."""
    nframes = len(data) // DTK_FRAME
    if max_frames is not None:
        nframes = min(nframes, max_frames)
    out = bytearray(nframes * 28 * 4)
    hist = [[0, 0], [0, 0]]
    o = 0
    pack_into = struct.pack_into
    for f in range(nframes):
        base = f * DTK_FRAME
        for ch in range(2):
            hdr = data[base + ch]
            shift = hdr & 0xF
            c1, c2 = DTK_COEFS[(hdr >> 4) & 3]
            h1, h2 = hist[ch]
            for i in range(28):
                b = data[base + 4 + i]
                v = (b & 0xF) if ch == 0 else (b >> 4)
                if v >= 8:
                    v -= 16
                pred = (h1 * c1 - h2 * c2 + 32) >> 6
                if pred > 2097151:
                    pred = 2097151
                elif pred < -2097152:
                    pred = -2097152
                s = (((v << 12) >> shift) << 6) + pred
                h2, h1 = h1, s
                o16 = s >> 6
                if o16 > 32767:
                    o16 = 32767
                elif o16 < -32768:
                    o16 = -32768
                pack_into("<h", out, (o + i) * 4 + ch * 2, o16)
            hist[ch] = [h1, h2]
        o += 28
    return bytes(out)


def dtk_seconds(size: int) -> float:
    return size // DTK_FRAME * 28 / DTK_RATE


def dtk_wav(data: bytes, max_seconds: float | None = None) -> bytes:
    n = None if max_seconds is None else int(max_seconds * DTK_RATE / 28)
    return wav(dtk_decode(data, n), DTK_RATE, 2)
