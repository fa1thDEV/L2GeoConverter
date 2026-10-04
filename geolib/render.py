#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Render a region to PNG: height palette + encoder (pure stdlib).

Used by the viewer (/api/render) to download a region image.
"""

import struct
import zlib

# Height palette: monotonic in lightness (depth → peaks),
# normalized to the region's actual height range
ELEV_STOPS = [
    (0.000, (0x1a, 0x23, 0x40)), (0.125, (0x23, 0x48, 0x6b)),
    (0.250, (0x2e, 0x6d, 0x75)), (0.375, (0x3d, 0x8f, 0x6f)),
    (0.500, (0x6a, 0xae, 0x6a)), (0.625, (0xa8, 0xc0, 0x7a)),
    (0.750, (0xd3, 0xc9, 0x9a)), (0.875, (0xec, 0xe3, 0xc8)),
    (1.000, (0xff, 0xff, 0xff)),
]
NO_LAYER = (0x1a, 0x1d, 0x23)  # block without the selected layer


def elev_color(h, lo=-16384, hi=16384):
    t = 0.5 if hi <= lo else max(0.0, min(1.0, (h - lo) / (hi - lo)))
    for (t0, c0), (t1, c1) in zip(ELEV_STOPS, ELEV_STOPS[1:]):
        if t <= t1:
            f = (t - t0) / (t1 - t0)
            return tuple(int(a + (b - a) * f) for a, b in zip(c0, c1))
    return ELEV_STOPS[-1][1]


def png_bytes(w, h, rows):
    """RGB rows → PNG (8-bit truecolor, filter 0)."""
    def chunk(tag, payload):
        return (struct.pack('>I', len(payload)) + tag + payload +
                struct.pack('>I', zlib.crc32(tag + payload)))
    raw = b''.join(b'\x00' + bytes(v for px in row for v in px) for row in rows)
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(raw, 6)) +
            chunk(b'IEND', b''))


def render_png(blocks, layer=-1):
    """Region → PNG 2048×2048 (pixel = cell).

    layer = -1: surface (top layer of each cell);
    layer = N ≥ 0: N-th from the top layer, cells without it — dark.
    """
    if layer < 0:
        # normalize by the 2nd percentile of surface heights — pits
        # and dungeons do not wash out the map (elev_color clamps outliers)
        tops = sorted(max(h for h, _ in cell) for blk in blocks for cell in blk)
        lo, hi = tops[len(tops) // 50], tops[-1]
    else:
        lo = min(h for blk in blocks for cell in blk for h, _ in cell)
        hi = max(h for blk in blocks for cell in blk for h, _ in cell)
    rows = [[NO_LAYER] * 2048 for _ in range(2048)]
    for bx in range(256):
        for by in range(256):
            blk = blocks[bx * 256 + by]
            for cx in range(8):
                for cy in range(8):
                    cell = blk[cx * 8 + cy]
                    if layer < 0:
                        h = max(hh for hh, _ in cell)
                    else:
                        if len(cell) <= layer:
                            continue  # remains NO_LAYER
                        h = sorted((hh for hh, _ in cell), reverse=True)[layer]
                    rows[by * 8 + cy][bx * 8 + cx] = elev_color(h, lo, hi)
    return png_bytes(2048, 2048, rows)
