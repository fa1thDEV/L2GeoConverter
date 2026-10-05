#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare two geodata packs: summary report and detailed region breakdown."""

import glob
import os
import random
import re
import struct

from .formats import BLOCKS, PTS_HEADER, GeoError, parse_region, sniff_format, pts_flat_surface
from .ui import bold, cyan, dim, green, progress, red, yellow

SAMPLE_BLOCKS = 1200   # blocks per region in summary mode (deterministic sample)
NEAR = 16              # |Δh| ≤ NEAR counts as a match (one height step)
FAR = 64               # |Δh| > FAR — “different terrain”


def region_files(d):
    """Folder files: name stem → path (.l2j/.l2g preferred over _conv.dat).
    The stem keeps the suffix: 27_24_Classic is a separate region from 27_24;
    coordinates must be extracted from the first two numbers in the name."""
    out = {}
    for f in sorted(glob.glob(os.path.join(d, '*.l2j'))) + \
             sorted(glob.glob(os.path.join(d, '*.l2g'))) + \
             sorted(glob.glob(os.path.join(d, '*_conv.dat'))):
        base = os.path.basename(f)
        if not re.match(r'^\d+_\d+', base):
            continue
        if base.endswith('_conv.dat'):
            stem = base[:-len('_conv.dat')]
        elif base.endswith('.l2g'):
            stem = base[:-len('.l2g')]
        else:
            stem = base[:-len('.l2j')]
        out.setdefault(stem, f)
    return out


def _dec_h(v):
    return struct.unpack('<h', struct.pack('<H', v & 0xFFF0))[0] >> 1


def sampled_surface(path, wanted):
    """Surface heights for selected blocks (8 cells per block).

    Walks the file as a stream, decoding only the needed blocks —
    an order of magnitude faster than a full parse_region."""
    fmt = sniff_format(path)
    data = open(path, 'rb').read()
    if fmt == 'l2g':
        from .formats import L2GCodec
        data = L2GCodec.decrypt(data)
        fmt = 'l2j'
    pos = PTS_HEADER if fmt == 'pts' else 0
    res = {}
    for b in range(BLOCKS):
        take = b in wanted
        if fmt == 'l2j':
            t = data[pos]; pos += 1
            if t == 0:
                if take:
                    (h,) = struct.unpack_from('<h', data, pos)
                    res[b] = [h] * 8
                pos += 2
            elif t == 1:
                if take:
                    cells = struct.unpack_from('<64H', data, pos)
                    res[b] = [_dec_h(cells[c]) for c in range(0, 64, 8)]
                pos += 128
            else:
                hs = []
                for c in range(64):
                    nl = data[pos]; pos += 1
                    if take and c % 8 == 0:
                        layers = struct.unpack_from(f'<{nl}H', data, pos)
                        hs.append(max(_dec_h(l) for l in layers))
                    pos += nl * 2
                if take:
                    res[b] = hs
        else:  # pts
            (t,) = struct.unpack_from('<H', data, pos); pos += 2
            if t == 0x0000:
                if take:
                    _mn, mx = struct.unpack_from('<hh', data, pos)
                    res[b] = [pts_flat_surface(_mn, mx)] * 8
                pos += 4
            elif t == 0x0040:
                if take:
                    cells = struct.unpack_from('<64H', data, pos)
                    res[b] = [_dec_h(cells[c]) for c in range(0, 64, 8)]
                pos += 128
            else:
                hs = []
                for c in range(64):
                    (nl,) = struct.unpack_from('<H', data, pos); pos += 2
                    if take and c % 8 == 0:
                        layers = struct.unpack_from(f'<{nl}H', data, pos)
                        hs.append(max(_dec_h(l) for l in layers))
                    pos += nl * 2
                if take:
                    res[b] = hs
    return res


def _world(region, bx, by):
    rx, ry = map(int, re.match(r'^(\d+)_(\d+)', region).groups())
    return (rx - 20) * 32768 + bx * 128, (ry - 18) * 32768 + by * 128


def _detail(region, fa, fb, name_a, name_b):
    """Full per-block breakdown of one region + ASCII mismatch map."""
    print(f'  {bold(region)}: full breakdown (all 4.2 million cells)…')
    try:
        a = parse_region(fa)
    except (GeoError, struct.error, IndexError, ValueError) as e:
        print(red(f'  ✗ corrupt file in A ({os.path.basename(fa)}): {e}'))
        return 1
    try:
        b = parse_region(fb)
    except (GeoError, struct.error, IndexError, ValueError) as e:
        print(red(f'  ✗ corrupt file in B ({os.path.basename(fb)}): {e}'))
        return 1
    surf = lambda cell: max(h for h, _ in cell)
    grid = [0] * BLOCKS           # max |Δh| of the surface per block
    n_cells = n_same = n_near = 0
    for i in range(BLOCKS):
        m = 0
        for ca, cb in zip(a[i], b[i]):
            dh = surf(ca) - surf(cb)
            n_cells += 1
            if dh == 0:
                n_same += 1
            if abs(dh) <= NEAR:
                n_near += 1
            if abs(dh) > abs(m):
                m = dh
        grid[i] = m
    n_far_blocks = sum(1 for m in grid if abs(m) > FAR)
    print(f'\n  cells: {n_cells:,} · exact match {n_same / n_cells:.1%}'
          f' · within ±{NEAR}: {n_near / n_cells:.1%}'.replace(',', ' '))
    print(f'  blocks with |Δh| > {FAR}: {n_far_blocks} ({n_far_blocks / 655.36:.1f}%)')

    # NSWE: walkability on comparable surfaces (|Δh| ≤ NEAR)
    nswe_n = nswe_same = 0
    dir_diff = [0, 0, 0, 0]                       # N, S, W, E
    for i in range(BLOCKS):
        for ca, cb in zip(a[i], b[i]):
            la = max(ca, key=lambda l: l[0])
            lb = max(cb, key=lambda l: l[0])
            if abs(la[0] - lb[0]) > NEAR:
                continue
            nswe_n += 1
            if la[1] == lb[1]:
                nswe_same += 1
            else:
                x = la[1] ^ lb[1]
                for bi_, bit in enumerate((8, 4, 2, 1)):
                    if x & bit:
                        dir_diff[bi_] += 1
    if nswe_n:
        print(f'  NSWE (on comparable surfaces): match '
              f'{nswe_same / nswe_n:.1%} of {nswe_n:,} cells'.replace(',', ' '))
        print(f'    mismatches by direction: N {dir_diff[0]:,} · S {dir_diff[1]:,}'
              f' · W {dir_diff[2]:,} · E {dir_diff[3]:,}'.replace(',', ' '))

    # clusters: 16×16 superblocks with the most mismatched blocks
    sup = {}
    for bx in range(256):
        for by in range(256):
            if abs(grid[bx * 256 + by]) > FAR:
                sup[(bx // 16, by // 16)] = sup.get((bx // 16, by // 16), 0) + 1
    if sup:
        print(f'\n  {bold("Mismatch hotspots")} (world coordinates of centers):')
        for (sx, sy), cnt in sorted(sup.items(), key=lambda kv: -kv[1])[:5]:
            wx, wy = _world(region, sx * 16 + 8, sy * 16 + 8)
            print(f'    ~({wx}, {wy}) — {cnt}/256 blocks ({cnt / 2.56:.0f}%)')

    print(f'\n  Map (32×32, `#` |Δh|>{FAR}, `+` |Δh|>{NEAR}, `·` matches);'
          f' X → east, Y ↓ south:')
    for sy in range(0, 256, 8):
        row = '  '
        for sx in range(0, 256, 8):
            worst = max((abs(grid[(sx + dx) * 256 + sy + dy])
                         for dx in range(8) for dy in range(8)))
            row += '#' if worst > FAR else ('+' if worst > NEAR else '·')
        print(cyan(row))
    print(f'\n  {dim(f"A = {name_a}, B = {name_b}; Δh = A − B (surface)")}')
    return 0


def cmd_diff(dir_a, dir_b, region=None, stop_event=None):
    fa_all, fb_all = region_files(dir_a), region_files(dir_b)
    if not fa_all or not fb_all:
        print(red('  ✗ one of the folders has no geodata files (*.l2j / *_conv.dat named from XX_YY).'))
        return 1
    name_a, name_b = (os.path.basename(os.path.normpath(d)) for d in (dir_a, dir_b))
    common = sorted(set(fa_all) & set(fb_all))
    only_a = sorted(set(fa_all) - set(fb_all))
    only_b = sorted(set(fb_all) - set(fa_all))

    if region:
        if region not in common:
            print(red(f'  ✗ region {region} is missing from one of the folders.'))
            return 1
        return _detail(region, fa_all[region], fb_all[region], name_a, name_b)

    print(f'  {bold("Compare:")} A = {name_a} ({len(fa_all)}) · B = {name_b} ({len(fb_all)})'
          f' · shared regions: {len(common)}\n')
    rnd = random.Random(42)
    sample = set(rnd.sample(range(BLOCKS), SAMPLE_BLOCKS))
    rows = []
    for i, r in enumerate(common, 1):
        if stop_event and stop_event.is_set():
            print("\n  [DIFF] Comparison stopped by user.")
            return 0
        try:
            ha = sampled_surface(fa_all[r], sample)
        except (GeoError, struct.error, IndexError, ValueError):
            rows.append((r, -1.0, 'A'))
            progress(i, len(common), 'compare ')
            continue
        try:
            hb = sampled_surface(fb_all[r], sample)
        except (GeoError, struct.error, IndexError, ValueError):
            rows.append((r, -1.0, 'B'))
            progress(i, len(common), 'compare ')
            continue
        n = ok = 0
        worst = 0
        for blk in sample:
            for x, y in zip(ha[blk], hb[blk]):
                n += 1
                d = abs(x - y)
                if d <= NEAR:
                    ok += 1
                if d > worst:
                    worst = d
        rows.append((r, ok / n if n else 0.0, worst))
        progress(i, len(common), 'compare ')

    rows.sort(key=lambda x: x[1])
    print(f'\n  {bold("Regions by mismatch")} (match = |Δh| ≤ {NEAR}):')
    print(f'  {"region":8} {"match":>8} {"max|Δh|":>9}')
    shown = 0
    for r, pct, worst in rows:
        if pct < 0:
            side = name_a if worst == 'A' else name_b
            print('  ' + red(f'{r:8} corrupt file in folder {worst} ({side})'))
            continue
        if pct >= 0.99 and shown >= 15:
            continue  # do not print the tail of identical ones in full
        mark = green('✓') if pct >= 0.99 else (yellow('~') if pct >= 0.90 else red('✗'))
        print(f'  {r:8} {pct:>8.1%} {worst:>9} {mark}')
        shown += 1
    n_id = sum(1 for _, p, _ in rows if p >= 0.99)
    n_near_ = sum(1 for _, p, _ in rows if 0.90 <= p < 0.99)
    n_far_ = sum(1 for _, p, _ in rows if 0 <= p < 0.90)
    n_bad = sum(1 for _, p, _ in rows if p < 0)
    print(f'\n  {bold("Summary:")} {green(f"✓ identical: {n_id}")} · '
          f'{yellow(f"~ close: {n_near_}")} · {red(f"✗ differ: {n_far_}")}'
          + (f' · {red(f"corrupt files: {n_bad}")}' if n_bad else ''))
    if only_a:
        print(f'  only in A ({name_a}): {len(only_a)} — {" ".join(only_a[:12])}'
              + (' …' if len(only_a) > 12 else ''))
    if only_b:
        print(f'  only in B ({name_b}): {len(only_b)} — {" ".join(only_b[:12])}'
              + (' …' if len(only_b) > 12 else ''))
    print(dim(f'\n  detailed region breakdown: geotool.py diff <A> <B> --region <name, e.g. 23_18 or 23_18_Classic>'))
    return 2 if n_bad else 0
