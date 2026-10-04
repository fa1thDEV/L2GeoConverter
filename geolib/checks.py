#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pack checks and PTS ↔ L2J verification."""

import glob
import os
import struct

from .formats import BLOCKS, GeoError, block_type, parse_region
from .ui import bold, green, progress, red, yellow


def cmd_check(paths):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.l2j'))) + \
                     sorted(glob.glob(os.path.join(p, '*_conv.dat')))
        else:
            files.append(p)
    if not files:
        print(red('  ✗ no files found.'))
        return 1
    print(f'  {bold("Check")} {len(files)} files…\n')
    n_ok = n_stub = n_bad = 0
    stubs, bads = [], []
    for i, f in enumerate(files, 1):
        name = os.path.basename(f)
        try:
            blocks = parse_region(f)
            flat = sum(1 for b in blocks if block_type(b) == 0)
            heights = {b[0][0][0] for b in blocks if block_type(b) == 0}
            if flat == BLOCKS and len(heights) <= 2:
                stubs.append((name, f'entire region is a plane ({sorted(heights)})'))
                n_stub += 1
            else:
                n_ok += 1
        except GeoError as e:
            bads.append((name, str(e)))
            n_bad += 1
        except (struct.error, IndexError):
            bads.append((name, 'file is corrupt or truncated'))
            n_bad += 1
        progress(i, len(files), 'check ')
    print()
    print(f'  {green("✓")} valid: {green(str(n_ok))}')
    if stubs:
        print(f'  {yellow("⚠")} stubs (flat): {yellow(str(n_stub))}')
        for n, why in stubs:
            print(f'      {yellow("⚠")} {n}: {why}')
    if bads:
        print(f'  {red("✗")} corrupt: {red(str(n_bad))}')
        for n, why in bads:
            print(f'      {red("✗")} {n}: {why}')
    return 0 if not bads else 2


def cmd_verify(pts_dir, l2j_dir):
    """Per-cell verification of XX_YY_conv.dat ↔ XX_YY.l2j pairs.

    Conversion direction does not matter (both formats parse into
    the same structure); folders can be passed in any order —
    which is PTS and which is L2J is determined from the contents."""
    import glob as _g
    if not _g.glob(os.path.join(pts_dir, '*_conv.dat')) and \
            _g.glob(os.path.join(l2j_dir, '*_conv.dat')):
        pts_dir, l2j_dir = l2j_dir, pts_dir
    # Pairs by name: X_conv.dat ↔ X.l2j (conversion preserves the name,
    # 27_24_Classic_conv.dat ↔ 27_24_Classic.l2j).
    pairs = []
    unpaired = 0
    for f in sorted(glob.glob(os.path.join(pts_dir, '*_conv.dat'))):
        stem = os.path.basename(f)[:-len('_conv.dat')]
        dst = os.path.join(l2j_dir, stem + '.l2j')
        if os.path.exists(dst):
            pairs.append((stem, f, dst))
        else:
            unpaired += 1
    if unpaired:
        print(yellow(f'  ⚠ without a matching .l2j (will not be verified): {unpaired}'))
    if not pairs:
        print(red('  ✗ no PTS↔L2J pairs found.'))
        return 1
    print(f'  {bold("Verify")} {len(pairs)} regions (semantics: heights, layers, NSWE)…\n')
    n_ok = n_diff = 0
    for i, (key, src, dst) in enumerate(pairs, 1):
        try:
            a = parse_region(src, 'pts')
            b = parse_region(dst, 'l2j')
        except GeoError as e:
            n_diff += 1
            print('\r  ' + red(f'✗ {key}: corrupt file ({e})') + ' ' * 20)
            progress(i, len(pairs), 'verify ')
            continue
        except (struct.error, IndexError, ValueError):
            n_diff += 1
            print('\r  ' + red(f'✗ {key}: corrupt file (damaged or truncated)') + ' ' * 20)
            progress(i, len(pairs), 'verify ')
            continue
        diffs = 0
        for blk_a, blk_b in zip(a, b):
            for cell_a, cell_b in zip(blk_a, blk_b):
                if cell_a != cell_b:
                    diffs += 1
        if diffs:
            n_diff += 1
            print(f'\r  {red("✗")} {key}: {diffs} cells differ' + ' ' * 30)
        else:
            n_ok += 1
        progress(i, len(pairs), 'verify ')
    print()
    if n_diff == 0:
        print(f'  {green("✓")} all {n_ok} regions match the sources — lossless conversion.')
    else:
        print(f'  {green("✓")} match: {n_ok}   {red("✗")} differ: {n_diff}')
    return 0 if n_diff == 0 else 2
