/* hvqm4dec: decode an HVQM4 movie into a folder for MSSB Editor.
 *
 *   hvqm4dec movie.h4m outdir
 *
 * Writes outdir/frames.mjpg (baseline JPEGs back to back), outdir/frames.idx
 * (u32 little-endian offset,size per frame in display order), outdir/audio.wav
 * and outdir/info.json. Progress goes to stdout as "frames N" then "frame i".
 *
 * The decoder is Tilka's (LGPL v2+, h4m_decoder.c); the JPEG encoder is
 * TinyJPEG (public domain). This driver is part of MSSB Editor (MIT).
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#define TJE_IMPLEMENTATION
#include "tiny_jpeg.h"
#ifdef small
#undef small  /* Windows rpcndr.h macro clashes with a local in the decoder */
#endif
#include "h4m_decoder.c"

static FILE *g_frames;
static uint32_t *g_offsets, *g_sizes, g_count, g_written;
static uint64_t g_pos;
static uint8_t *g_buf;
static size_t g_len, g_cap;

static void jpeg_write(void *ctx, void *data, int size)
{
    (void)ctx;
    if (g_len + (size_t)size > g_cap)
    {
        g_cap = (g_len + size) * 2;
        g_buf = realloc(g_buf, g_cap);
    }
    memcpy(g_buf + g_len, data, size);
    g_len += size;
}

static inline uint8_t clamp_u8(float v)
{
    return v < 0.f ? 0 : v > 255.f ? 255 : (uint8_t)(v + 0.5f);
}

static void emit_frame(Player *player, uint32_t index)
{
    uint32_t w = player->seqobj.width, h = player->seqobj.height;
    uint8_t const *yp = player->present;
    uint8_t const *up = yp + w * h;
    uint8_t const *vp = up + w * h / 4;
    uint8_t *rgb = malloc((size_t)w * h * 3), *ptr = rgb;
    for (uint32_t i = 0; i < h; ++i)
        for (uint32_t j = 0; j < w; ++j)
        {
            float y = yp[i * w + j], u = up[i / 2 * (w / 2) + j / 2], v = vp[i / 2 * (w / 2) + j / 2];
            *ptr++ = clamp_u8(y + 1.402f * (v - 128.f));
            *ptr++ = clamp_u8(y - 0.34414f * (u - 128.f) - 0.71414f * (v - 128.f));
            *ptr++ = clamp_u8(y + 1.772f * (u - 128.f));
        }
    g_len = 0;
    tje_encode_with_func(jpeg_write, NULL, 3, (int)w, (int)h, 3, rgb);
    free(rgb);
    if (index < g_count)
    {
        g_offsets[index] = (uint32_t)g_pos;
        g_sizes[index] = (uint32_t)g_len;
    }
    fwrite(g_buf, 1, g_len, g_frames);
    g_pos += g_len;
    g_written++;
    if (g_written % 16 == 0 || g_written == g_count)
    {
        printf("frame %u\n", g_written);
        fflush(stdout);
    }
}

int main(int argc, char **argv)
{
    if (argc != 3)
    {
        fprintf(stderr, "usage: %s movie.h4m outdir\n", argv[0]);
        return 2;
    }
    FILE *in = fopen(argv[1], "rb");
    if (!in)
    {
        fprintf(stderr, "cannot open %s\n", argv[1]);
        return 1;
    }
    uint8_t raw[0x44];
    if (fread(raw, 1, 0x44, in) != 0x44)
    {
        fprintf(stderr, "short header\n");
        return 1;
    }
    fclose(in);
    HVQM4_header header;
    load_header(&header, raw);
    g_count = header.video_frames;
    g_offsets = calloc(g_count, sizeof(uint32_t));
    g_sizes = calloc(g_count, sizeof(uint32_t));
    char path[4096];
    snprintf(path, sizeof path, "%s/frames.mjpg", argv[2]);
    g_frames = fopen(path, "wb");
    if (!g_frames)
    {
        fprintf(stderr, "cannot write %s\n", path);
        return 1;
    }
    printf("frames %u\n", g_count);
    fflush(stdout);
    char wav[4096];
    snprintf(wav, sizeof wav, "%s/audio.wav", argv[2]);
    h4m_decode(argv[1], wav);
    fclose(g_frames);
    snprintf(path, sizeof path, "%s/frames.idx", argv[2]);
    FILE *idx = fopen(path, "wb");
    for (uint32_t i = 0; i < g_count; ++i)
    {
        uint8_t rec[8] = {g_offsets[i], g_offsets[i] >> 8, g_offsets[i] >> 16, g_offsets[i] >> 24,
                          g_sizes[i], g_sizes[i] >> 8, g_sizes[i] >> 16, g_sizes[i] >> 24};
        fwrite(rec, 1, 8, idx);
    }
    fclose(idx);
    snprintf(path, sizeof path, "%s/info.json", argv[2]);
    FILE *info = fopen(path, "w");
    fprintf(info, "{\"width\": %u, \"height\": %u, \"frames\": %u, \"usec_per_frame\": %u, \"fps\": %.4f, "
                  "\"sample_rate\": %u, \"channels\": %u}\n",
            header.hres, header.vres, header.video_frames, header.usec_per_frame,
            header.usec_per_frame ? 1e6 / header.usec_per_frame : 0.0, header.audio_srate, header.audio_channels);
    fclose(info);
    printf("done %u frames\n", g_written);
    return 0;
}
