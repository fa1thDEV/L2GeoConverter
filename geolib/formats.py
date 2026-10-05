#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2J and PTS geodata formats: parsing, cell encoding, summaries.

L2J : block u8 type (0 flat: i16; 1 complex: 64×i16; 2 multi: 64×[u8 n + n×i16])
PTS : 18B header; block u16 type (0 flat: 2×i16 min/max; 0x40 complex: 64×i16;
      otherwise multi: 64×[u16 n + n×i16]; the multilayer-block type-u16 itself
      equals the total number of layers in the block — verified on all real files)
Cell (both formats): (height<<1)&0xFFF0 | nswe(4 bits: 8=N 4=S 2=W 1=E)
PTS type-0 stores two i16s as (high, low) — official files never write the
second word higher; the walkable surface is max(high, low). Official packs
flatten an 8×8 to type-0 when every cell is one layer, NSWE=15, and
quantized max−min ≤ FLAT_SPAN (32). This toolkit *writes* type-0 only when
those heights are identical (`complex_is_flat(..., span=0)`): flattening a
16–32u ramp to max() makes a 24u wall at the next block. L2J type-0 has
only one i16 (the surface).
PTS header: u8 rx, u8 ry, "80 00 10 00", then three u32 counters,
      then the block body. The first u32 differs by protocol:

      * gd (Glory Days, Interlude, High Five, Epilogue — official L2OFF PTS):
        total non-flat *layers* (sum of layers in every complex +
        multilayer cell — what CGeoData allocates). Stacked cells make
        this larger than cell count. Default for this fork.
      * 286 (official protocol 286): (complex + multilayer) * 64 — non-flat
        *cells*, not layers.

      The other two u32s are the same: flat+complex blocks, then flat blocks.
      The block body is identical. L2J has no 18-byte header, so protocol
      only matters when writing PTS (`generate --format pts`, `l2j2pts`).
"""

import os
import re
import struct

BLOCKS = 65536
PTS_HEADER = 18
# Official type-0: all 64 cells single-layer, NSWE=15, quantized span
# only 0/8/16/24/32. Walk height is the higher of the two i16s.
FLAT_SPAN = 32

# PTS 18-byte header first u32 — see module docstring.
# Default is gd: official L2OFF layer-sum (GD / Interlude / HF / Epilogue).
PROTO_286 = '286'
PROTO_GD = 'gd'
_PROTO_ALIASES = {
    # Official protocol 286: non-flat *cells*
    '286': PROTO_286,
    'c4': PROTO_286,
    # Official L2OFF: non-flat *layers*
    'gd': PROTO_GD,
    'glory': PROTO_GD,
    'glorydays': PROTO_GD,
    'interlude': PROTO_GD,
    'il': PROTO_GD,
    'hf': PROTO_GD,
    'highfive': PROTO_GD,
    'high-five': PROTO_GD,
    'high_five': PROTO_GD,
    'epilogue': PROTO_GD,
    'ep': PROTO_GD,
}

# Aliases shown in CLI help / README (not every accepted spelling).
PROTO_SHOWN = {
    PROTO_GD: ('gd', 'interlude', 'hf', 'epilogue', 'glory'),
    PROTO_286: ('286', 'c4'),
}
PROTO_CLI_HELP = (
    'PTS header: gd (default; also interlude, hf, epilogue, glory) = '
    'official L2OFF layer-sum. 286 (also c4) = official protocol 286 (cx+ml)*64'
)


class GeoError(Exception):
    pass


def normalize_protocol(name):
    """'286' | 'gd' from a CLI/menu alias. Default gd (official L2OFF)."""
    key = (name or PROTO_GD).strip().lower().replace(' ', '')
    proto = _PROTO_ALIASES.get(key)
    if proto is None:
        shown = ', '.join(PROTO_SHOWN[PROTO_GD] + PROTO_SHOWN[PROTO_286])
        raise GeoError(f'unknown PTS protocol {name!r} (use {shown})')
    return proto


def pts_layer_field(n_layers, n_cx, n_ml, protocol=PROTO_GD):
    """First u32 of the PTS header for the chosen protocol."""
    if normalize_protocol(protocol) == PROTO_286:
        return (n_cx + n_ml) * 64
    return n_layers


def pack_pts_header(rx, ry, n_flat, n_cx, n_ml, n_layers, protocol=PROTO_GD):
    """18-byte PTS header. Body encoding does not depend on protocol."""
    return struct.pack('<BBBBBBIII', rx, ry, 0x80, 0x00, 0x10, 0x00,
                       pts_layer_field(n_layers, n_cx, n_ml, protocol),
                       n_flat + n_cx, n_flat)


def dec_h(v):
    """Encoded cell → height."""
    return struct.unpack('<h', struct.pack('<H', v & 0xFFF0))[0] >> 1


def dec_nswe(v):
    return v & 0x000F


def enc_cell(h, nswe):
    return ((h << 1) & 0xFFF0) | (nswe & 0xF)


def quant_h(h):
    """8-unit packed height — same grid as enc_cell / complex cells."""
    h = max(-16384, min(16376, int(h)))
    return dec_h(enc_cell(h, 0))


def pts_flat_surface(a, b):
    """Walk height of a PTS type-0 pair. Official stores (high, low)."""
    return a if a >= b else b


def pack_pts_flat_heights(a, b):
    """Two i16s for a PTS type-0 block: (high, low)."""
    lo, hi = (a, b) if a <= b else (b, a)
    return struct.pack('<hh', hi, lo)


def complex_is_flat(heights, nswes, span=FLAT_SPAN):
    """True if 64 single-layer open cells may be PTS type-0.

    Default ``span=FLAT_SPAN`` (32) is the official pack rule. Writers pass
    ``span=0`` so a 16–32u ramp stays complex.
    """
    if len(heights) != 64 or any(n != 15 for n in nswes):
        return False
    return max(heights) - min(heights) <= span


import ctypes

L2G_KEY_MAGIC = -2126429781 # 0x814467AB (Lucera 2 GeoEngine)


class L2GCodec:
    """Lucera 2 proprietary encrypted geodata format codec."""
    @staticmethod
    def decrypt(raw_bytes: bytes) -> bytes:
        if len(raw_bytes) < 4:
            raise GeoError("L2G buffer too short (must be >= 4 bytes)")
        key_raw = struct.unpack('<I', raw_bytes[:4])[0]
        data = bytearray(raw_bytes[4:])

        c_var7 = ctypes.c_int32(L2G_KEY_MAGIC ^ key_raw).value
        var9 = ((c_var7 >> 24) & 0xFF) ^ ((c_var7 >> 16) & 0xFF) ^ ((c_var7 >> 8) & 0xFF) ^ (c_var7 & 0xFF)
        var9 = ctypes.c_int8(var9).value

        payload = bytearray(len(data))
        check_var7 = c_var7
        for i in range(len(data)):
            b = data[i]
            dec = (b ^ var9) & 0xFF
            payload[i] = dec
            var9 = ctypes.c_int8(dec).value
            check_var7 = ctypes.c_int32(check_var7 - var9).value

        if check_var7 != 0:
            raise GeoError(f"L2G Checksum mismatch: remainder is {check_var7}, expected 0")
        return bytes(payload)

    @staticmethod
    def encrypt(payload: bytes) -> bytes:
        sum_bytes = 0
        for b in payload:
            sum_bytes = ctypes.c_int32(sum_bytes + ctypes.c_int8(b).value).value

        enc_key = ctypes.c_int32(L2G_KEY_MAGIC ^ sum_bytes).value
        initial_var7 = sum_bytes
        enc_var9 = ((initial_var7 >> 24) & 0xFF) ^ ((initial_var7 >> 16) & 0xFF) ^ ((initial_var7 >> 8) & 0xFF) ^ (initial_var7 & 0xFF)
        enc_var9 = ctypes.c_int8(enc_var9).value

        enc_data = bytearray(len(payload))
        for i in range(len(payload)):
            p = payload[i]
            enc_data[i] = (p ^ enc_var9) & 0xFF
            enc_var9 = ctypes.c_int8(p).value

        return struct.pack('<i', enc_key) + bytes(enc_data)

    encode = encrypt
    decode = decrypt


def sniff_format(path):
    """'l2j' | 'l2g' | 'pts' | None from name and contents."""
    name = os.path.basename(path).lower()
    if name.endswith('.l2g'):
        return 'l2g'
    if name.endswith('.l2j'):
        return 'l2j'
    if name.endswith('.dat'):
        return 'pts'
    return None


def region_of(path):
    m = re.match(r'^(\d+)_(\d+)', os.path.basename(path))
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def parse_region(path, fmt=None):
    """File -> list of 65536 blocks; block = list of 64 cells;
    cell = list of layers (h, nswe). Format is detected automatically."""
    fmt = fmt or sniff_format(path)
    with open(path, 'rb') as f:
        data = f.read()
    if fmt == 'l2g':
        data = L2GCodec.decrypt(data)
        fmt = 'l2j'
    blocks = []
    if fmt == 'l2j':
        pos = 0
        for b in range(BLOCKS):
            t = data[pos]; pos += 1
            if t == 0:
                # IMPORTANT: all 64 cells share one list object — data is
                # read-only; copy first if mutating
                (h,) = struct.unpack_from('<h', data, pos); pos += 2
                blocks.append([[(h, 15)]] * 64)
            elif t == 1:
                cells = struct.unpack_from('<64H', data, pos); pos += 128
                blocks.append([[(dec_h(v), dec_nswe(v))] for v in cells])
            elif t == 2:
                cells = []
                for _ in range(64):
                    nl = data[pos]; pos += 1
                    if nl == 0 or nl > 125:
                        raise GeoError(f'block {b}: corrupt layer count {nl}')
                    ls = struct.unpack_from(f'<{nl}H', data, pos); pos += nl * 2
                    cells.append([(dec_h(v), dec_nswe(v)) for v in ls])
                blocks.append(cells)
            else:
                raise GeoError(f'block {b}: unknown type {t}')
    elif fmt == 'pts':
        pos = PTS_HEADER
        for b in range(BLOCKS):
            (t,) = struct.unpack_from('<H', data, pos); pos += 2
            if t == 0x0000:
                # shared list — see comment in the l2j branch
                fa, fb = struct.unpack_from('<hh', data, pos); pos += 4
                h = pts_flat_surface(fa, fb)
                blocks.append([[(h, 15)]] * 64)
            elif t == 0x0040:
                cells = struct.unpack_from('<64H', data, pos); pos += 128
                blocks.append([[(dec_h(v), dec_nswe(v))] for v in cells])
            else:
                cells = []
                for _ in range(64):
                    (nl,) = struct.unpack_from('<H', data, pos); pos += 2
                    if nl == 0 or nl > 125:
                        raise GeoError(f'block {b}: corrupt layer count {nl}')
                    ls = struct.unpack_from(f'<{nl}H', data, pos); pos += nl * 2
                    cells.append([(dec_h(v), dec_nswe(v)) for v in ls])
                blocks.append(cells)
    else:
        raise GeoError(f'unknown format: {path}')
    return blocks


def block_type(block):
    """0 flat / 1 complex / 2 multilayer from contents."""
    if any(len(cell) > 1 for cell in block):
        return 2
    hs = {cell[0] for cell in block}
    return 0 if len(hs) == 1 and block[0][0][1] == 15 else 1


def summarize(blocks):
    """Per-block summary for the map: type, min/max heights (all layers),
    max layers, min SURFACE height (for palette normalization)."""
    types, hmin, hmax, lmax, smin = [], [], [], [], []
    for blk in blocks:
        t = block_type(blk)
        mn, mx, lm, sm = 32767, -32768, 0, 32767
        for cell in blk:
            lm = max(lm, len(cell))
            top = -32768
            for h, _ in cell:
                if h < mn:
                    mn = h
                if h > mx:
                    mx = h
                if h > top:
                    top = h
            if top < sm:
                sm = top
        types.append(t); hmin.append(mn); hmax.append(mx); lmax.append(lm); smin.append(sm)
    return types, hmin, hmax, lmax, smin
