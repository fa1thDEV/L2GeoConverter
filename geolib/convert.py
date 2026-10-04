#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PTS → L2J conversion and back."""

import glob
import os
import re
import struct
import time

from .formats import (
    BLOCKS, PROTO_GD, PTS_HEADER, GeoError, normalize_protocol, pack_pts_header,
    complex_is_flat, dec_h, dec_nswe, pack_pts_flat_heights,
    pts_flat_surface, quant_h, L2GCodec, region_of,
)
from .ui import bold, dim, green, progress, red, yellow


def pts2l2j_bytes(data):
    """PTS conv.dat bytes → (l2j bytes, (flat, cx, ml))."""
    out = bytearray()
    pos = PTS_HEADER
    stats = [0, 0, 0]
    try:
        for _ in range(BLOCKS):
            (t,) = struct.unpack_from('<H', data, pos); pos += 2
            if t == 0x0000:                       # flat: (high, low) → surface (max)
                a, b = struct.unpack_from('<hh', data, pos); pos += 4
                out.append(0)
                out += struct.pack('<h', pts_flat_surface(a, b))
                stats[0] += 1
            elif t == 0x0040:                     # complex: cell encoding matches
                out.append(1)
                out += data[pos:pos + 128]; pos += 128
                stats[1] += 1
            else:                                 # multilayer: u16-count → u8
                out.append(2)
                for _cell in range(64):
                    (nl,) = struct.unpack_from('<H', data, pos); pos += 2
                    if nl == 0 or nl > 125:
                        raise GeoError(f'corrupt layer count {nl} @0x{pos - 2:x}')
                    out.append(nl)
                    out += data[pos:pos + nl * 2]; pos += nl * 2
                stats[2] += 1
    except struct.error:
        raise GeoError(f'unexpected end of file @0x{pos:x}')
    if pos != len(data):
        raise GeoError(f'parsed {pos} bytes, file size {len(data)} — not PTS?')
    return bytes(out), stats


def convert_file(src, dst):
    """PTS conv.dat → l2j (streaming recode). Returns (flat, cx, ml)."""
    data = open(src, 'rb').read()
    l2j, stats = pts2l2j_bytes(data)
    open(dst, 'wb').write(l2j)
    return stats


def validate_l2j_bytes(data):
    """Parser mirroring the engine’s Region.load(): must reach exactly EOF."""
    pos = 0
    try:
        for b in range(BLOCKS):
            t = data[pos]; pos += 1
            if t == 0:
                pos += 2
            elif t == 1:
                pos += 128
            elif t == 2:
                for _cell in range(64):
                    nl = data[pos]; pos += 1
                    if nl == 0 or nl > 125:
                        raise GeoError(f'block {b}: corrupt layer count {nl}')
                    pos += nl * 2
            else:
                raise GeoError(f'block {b}: unknown type {t}')
    except IndexError:
        raise GeoError(f'unexpected end of file @0x{pos:x}')
    if pos != len(data):
        raise GeoError(f'parsed {pos} bytes, file size {len(data)}')


def validate_l2j(path):
    """Parser mirroring the engine’s Region.load(): must reach exactly EOF."""
    with open(path, 'rb') as f:
        validate_l2j_bytes(f.read())


def validate_pts_bytes(data):
    """Walk a PTS body to EOF and check the 18-byte header counters.

    The first u32 accepts either protocol: gd / official L2OFF (sum of
    non-flat layers — Glory Days, Interlude, HF, Epilogue) or official
    protocol 286 ((complex + multilayer) * 64). Body layout is the same.
    """
    if len(data) < PTS_HEADER:
        raise GeoError('PTS too short for header')
    _rx, _ry, a, b, c, d, n_field, n_flat_cx, n_flat = struct.unpack_from(
        '<BBBBBBIII', data, 0)
    if (a, b, c, d) != (0x80, 0x00, 0x10, 0x00):
        raise GeoError(f'bad PTS magic {a:02x} {b:02x} {c:02x} {d:02x}')
    pos = PTS_HEADER
    got_flat = got_cx = got_ml = got_layers = 0
    try:
        for bidx in range(BLOCKS):
            (t,) = struct.unpack_from('<H', data, pos); pos += 2
            if t == 0x0000:
                pos += 4
                got_flat += 1
            elif t == 0x0040:
                pos += 128
                got_cx += 1
                got_layers += 64
            else:
                total = 0
                for _cell in range(64):
                    (nl,) = struct.unpack_from('<H', data, pos); pos += 2
                    if nl == 0 or nl > 125:
                        raise GeoError(f'block {bidx}: corrupt layer count {nl}')
                    pos += nl * 2
                    total += nl
                if t != total:
                    raise GeoError(f'block {bidx}: type {t} ≠ layer sum {total}')
                got_ml += 1
                got_layers += total
    except struct.error:
        raise GeoError(f'unexpected end of file @0x{pos:x}')
    if pos != len(data):
        raise GeoError(f'parsed {pos} bytes, file size {len(data)}')
    il_field = (got_cx + got_ml) * 64
    if n_field != got_layers and n_field != il_field:
        raise GeoError(
            f'header field {n_field} is neither official L2OFF layer sum '
            f'{got_layers} nor protocol-286 (cx+ml)*64={il_field}')
    if got_flat != n_flat:
        raise GeoError(f'header n_flat {n_flat} ≠ body {got_flat}')
    if got_flat + got_cx != n_flat_cx:
        raise GeoError(f'header n_flat+cx {n_flat_cx} ≠ body {got_flat + got_cx}')


def validate_pts(path):
    """PTS loader walk: header magic, block types, EOF, header counters."""
    with open(path, 'rb') as f:
        validate_pts_bytes(f.read())


def _confirm_overwrite(names, out_dir, assume_yes):
    existing = [n for n in names if os.path.exists(os.path.join(out_dir, n))]
    if existing and not assume_yes:
        ans = input(f'  {yellow("⚠")} {len(existing)} files already exist in {out_dir}.'
                    f' Overwrite? [y/N] ')
        if ans.strip().lower() not in ('y', 'yes', 'д', 'да'):
            print(dim('  cancelled.'))
            return False
    return True


def cmd_convert(paths, out_dir, assume_yes=False):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*_conv.dat')))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(red(f'  ✗ not found: {p}'))
    # name is preserved: 27_24_Classic_conv.dat → 27_24_Classic.l2j
    jobs = {}
    for f in files:
        base = os.path.basename(f)
        stem = base[:-len('_conv.dat')] if base.endswith('_conv.dat') else os.path.splitext(base)[0]
        jobs[stem + '.l2j'] = f
    if not jobs:
        print(red('  ✗ nothing to convert.'))
        return 1
    print(f'\n  {bold("Plan:")} {green(str(len(jobs)))} regions → {out_dir}')
    if not _confirm_overwrite(jobs, out_dir, assume_yes):
        return 1
    os.makedirs(out_dir, exist_ok=True)
    t0 = time.time()
    totals = [0, 0, 0]
    errors = []
    names = sorted(jobs)
    for i, name in enumerate(names, 1):
        dst = os.path.join(out_dir, name)
        try:
            st = convert_file(jobs[name], dst)
            validate_l2j(dst)
            for j in range(3):
                totals[j] += st[j]
        except GeoError as e:
            errors.append((name, str(e)))
            # dst may coincide with the source (wrong conversion direction
            # + output into the same folder) — do not touch the source
            if os.path.exists(dst) and \
                    os.path.realpath(dst) != os.path.realpath(jobs[name]):
                os.remove(dst)
        progress(i, len(names), 'conversion ')
    print(f'\n  {bold("Summary")} in {time.time() - t0:.1f} s:')
    print(f'    {green("✓")} ok: {green(str(len(names) - len(errors)))} files'
          f' (engine-parser validation passed)')
    print(f'    blocks: flat {totals[0]:,} · complex {totals[1]:,} · multilayer {totals[2]:,}'.replace(',', ' '))
    if errors:
        print(f'    {red("✗")} errors: {red(str(len(errors)))}')
        for name, why in errors[:10]:
            print(f'      {red("✗")} {name}: {why}')
    return 2 if errors else 0


def _pts_from_complex64(raw):
    """64 encoded cells → PTS type-0 (high, low) if official-flat, else complex."""
    cells = struct.unpack_from('<64H', raw, 0)
    hs = [dec_h(v) for v in cells]
    ns = [dec_nswe(v) for v in cells]
    if complex_is_flat(hs, ns, span=0):
        return struct.pack('<H', 0x0000) + pack_pts_flat_heights(max(hs), min(hs)), True
    return struct.pack('<H', 0x0040) + raw, False


def l2j2pts_bytes(data, rx, ry, protocol=PROTO_GD):
    """l2j bytes → (pts bytes, n_flat, n_cx, n_ml).

    The multilayer-block marker in PTS is the total number of layers in the block.
    A degenerate multilayer where all 64 cells are single-layer yields
    sum 64 == 0x40 and would be indistinguishable from complex — such a block
    is encoded as complex (semantics identical; real geodata has no such blocks).

    Single-layer all-open 8×8 with identical quantized heights become
    PTS type-0 (high, low). A 16–32u ramp is kept complex: flattening it
    to max() turns the 8×8 into a 24u cliff at the next block and SuperPoint
    NPCs freeze on the step. Official packs flatten span ≤ 32; that rule
    fights bilinear heightmap ramps on new Talking Island.

    `protocol` only changes the first u32 of the 18-byte header
    (gd / Interlude / HF / Epilogue = layer sum; 286 = (cx+ml)*64).
    Body bytes are the same.
    """
    body = bytearray()
    pos = 0
    n_flat = n_cx = n_ml = n_layers = 0
    try:
        for b in range(BLOCKS):
            t = data[pos]; pos += 1
            if t == 0:
                (h,) = struct.unpack_from('<h', data, pos); pos += 2
                h = quant_h(h)
                body += struct.pack('<H', 0x0000) + pack_pts_flat_heights(h, h)
                n_flat += 1
            elif t == 1:
                raw = data[pos:pos + 128]; pos += 128
                payload, flattened = _pts_from_complex64(raw)
                body += payload
                if flattened:
                    n_flat += 1
                else:
                    n_cx += 1
                    n_layers += 64
            elif t == 2:
                cells = bytearray()
                total = 0
                single = bytearray()  # cells as complex, if all are single-layer
                for _cell in range(64):
                    nl = data[pos]; pos += 1
                    if nl == 0 or nl > 125:
                        raise GeoError(f'block {b}: corrupt layer count {nl}')
                    cells += struct.pack('<H', nl)
                    cells += data[pos:pos + nl * 2]
                    if nl == 1:
                        single += data[pos:pos + 2]
                    total += nl
                    pos += nl * 2
                if total == 64:
                    payload, flattened = _pts_from_complex64(single)
                    body += payload
                    if flattened:
                        n_flat += 1
                    else:
                        n_cx += 1
                        n_layers += 64
                else:
                    body += struct.pack('<H', total) + cells
                    n_ml += 1
                    n_layers += total
            else:
                raise GeoError(f'block {b}: unknown type {t}')
    except (struct.error, IndexError):
        raise GeoError(f'unexpected end of file @0x{pos:x}')
    if pos != len(data):
        raise GeoError(f'parsed {pos} bytes, file size {len(data)} — not l2j?')
    hdr = pack_pts_header(rx, ry, n_flat, n_cx, n_ml, n_layers, protocol)
    return bytes(hdr + body), n_flat, n_cx, n_ml


def l2j2pts_file(src, dst, rx, ry, protocol=PROTO_GD):
    """l2j → PTS file. Returns (flat, cx, ml)."""
    with open(src, 'rb') as f:
        pts, n_flat, n_cx, n_ml = l2j2pts_bytes(f.read(), rx, ry, protocol)
    with open(dst, 'wb') as f:
        f.write(pts)
    return n_flat, n_cx, n_ml


def cmd_l2j2pts(paths, out_dir, assume_yes=False, protocol=PROTO_GD):
    proto = normalize_protocol(protocol)
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.l2j')))
        elif os.path.isfile(p):
            files.append(p)
        else:
            print(red(f'  ✗ not found: {p}'))
    # name is preserved: 27_24_Classic.l2j → 27_24_Classic_conv.dat;
    # region coordinates (PTS header) — from the first two numbers in the name
    jobs, skipped = {}, []
    for f in files:
        base = os.path.basename(f)
        m = re.match(r'^(\d+)_(\d+)', base)
        # PTS header encodes coordinates as u8 — numbers >255 are not coordinates
        if not m or int(m.group(1)) > 255 or int(m.group(2)) > 255:
            skipped.append(f)
            continue
        stem = base[:-len('.l2j')] if base.endswith('.l2j') else os.path.splitext(base)[0]
        jobs[stem + '_conv.dat'] = (f, int(m.group(1)), int(m.group(2)))
    if skipped:
        print(yellow(f'  ⚠ SKIPPED {len(skipped)} files — name does not start with XX_YY,'
                     f' cannot extract region coordinates:'))
        for f in skipped[:20]:
            print(yellow(f'      {os.path.basename(f)}'))
    if not jobs:
        print(red('  ✗ no .l2j files found.'))
        return 1
    print(f'  {bold("Reverse conversion")} {len(jobs)} files → {out_dir}'
          f' (PTS protocol {proto})')
    if not _confirm_overwrite(jobs, out_dir, assume_yes):
        return 1
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    names = sorted(jobs)
    for i, name in enumerate(names, 1):
        src, rx, ry = jobs[name]
        try:
            dst = os.path.join(out_dir, name)
            l2j2pts_file(src, dst, rx, ry, proto)
            validate_pts(dst)
        except GeoError as e:
            errors.append((name, str(e)))
        progress(i, len(names), 'conversion ')
    print(f'\n  {green("✓")} done: {len(names) - len(errors)} files.'
          f' PTS headers restored (protocol {proto}: '
          + ('layer sum' if proto == PROTO_GD else '(cx+ml)*64')
          + ' + block counters).')
    if errors:
        print(f'  {red("✗")} errors: {len(errors)}')
        for name, why in errors[:10]:
            print(f'      {red("✗")} {name}: {why}')
    if errors:
        return 2
    return 3 if skipped else 0


def l2g2l2j_file(src, dst):
    """Decrypts Lucera 2 .l2g to standard .l2j."""
    enc = open(src, 'rb').read()
    dec = L2GCodec.decrypt(enc)
    validate_l2j_bytes(dec)
    open(dst, 'wb').write(dec)


def l2j2l2g_file(src, dst):
    """Encrypts standard .l2j to Lucera 2 .l2g."""
    raw = open(src, 'rb').read()
    validate_l2j_bytes(raw)
    enc = L2GCodec.encrypt(raw)
    open(dst, 'wb').write(enc)


def pts2l2g_file(src, dst):
    """PTS _conv.dat -> Lucera 2 .l2g."""
    # Convert to L2J in-memory, then encrypt
    data = open(src, 'rb').read()
    out = bytearray()
    pos = PTS_HEADER
    for _ in range(BLOCKS):
        (t,) = struct.unpack_from('<H', data, pos); pos += 2
        if t == 0x0000:
            a, b = struct.unpack_from('<hh', data, pos); pos += 4
            out.append(0)
            out += struct.pack('<h', pts_flat_surface(a, b))
        elif t == 0x0040:
            out.append(1)
            out += data[pos:pos + 128]; pos += 128
        else:
            out.append(2)
            for _cell in range(64):
                (nl,) = struct.unpack_from('<H', data, pos); pos += 2
                if nl == 0 or nl > 125:
                    raise GeoError(f'corrupt layer count {nl} @0x{pos - 2:x}')
                out.append(nl)
                out += data[pos:pos + nl * 2]; pos += nl * 2
    validate_l2j_bytes(out)
    enc = L2GCodec.encrypt(bytes(out))
    open(dst, 'wb').write(enc)


def l2g2pts_file(src, dst, rx, ry, protocol=PROTO_GD):
    """Lucera 2 .l2g -> PTS _conv.dat."""
    enc = open(src, 'rb').read()
    dec = L2GCodec.decrypt(enc)
    validate_l2j_bytes(dec)
    pts, _, _, _ = l2j2pts_bytes(dec, rx, ry, protocol)
    open(dst, 'wb').write(pts)


def cmd_l2g2l2j(paths, out_dir, assume_yes=False):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.l2g')))
        elif os.path.isfile(p):
            files.append(p)
    jobs = {os.path.splitext(os.path.basename(f))[0] + '.l2j': f for f in files}
    if not jobs:
        print(red('  ✗ no .l2g files found.'))
        return 1
    print(f'  {bold("Decrypting Lucera 2 .l2g -> .l2j")}: {len(jobs)} files -> {out_dir}')
    if not _confirm_overwrite(jobs, out_dir, assume_yes):
        return 1
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    names = sorted(jobs)
    for i, name in enumerate(names, 1):
        dst = os.path.join(out_dir, name)
        try:
            l2g2l2j_file(jobs[name], dst)
        except Exception as e:
            errors.append((name, str(e)))
        progress(i, len(names), 'decrypting ')
    print(f'\n  {green("✓")} done: {len(names) - len(errors)} files converted to .l2j.')
    return 2 if errors else 0


def cmd_l2j2l2g(paths, out_dir, assume_yes=False):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.l2j')))
        elif os.path.isfile(p):
            files.append(p)
    jobs = {os.path.splitext(os.path.basename(f))[0] + '.l2g': f for f in files}
    if not jobs:
        print(red('  ✗ no .l2j files found.'))
        return 1
    print(f'  {bold("Encrypting .l2j -> Lucera 2 .l2g")}: {len(jobs)} files -> {out_dir}')
    if not _confirm_overwrite(jobs, out_dir, assume_yes):
        return 1
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    names = sorted(jobs)
    for i, name in enumerate(names, 1):
        dst = os.path.join(out_dir, name)
        try:
            l2j2l2g_file(jobs[name], dst)
        except Exception as e:
            errors.append((name, str(e)))
        progress(i, len(names), 'encrypting ')
    print(f'\n  {green("✓")} done: {len(names) - len(errors)} files converted to .l2g.')
    return 2 if errors else 0


def pts2l2g_file(src, dst, rx, ry):
    """PTS _conv.dat -> Lucera 2 .l2g."""
    data = open(src, 'rb').read()
    l2j_bytes, _ = pts2l2j_bytes(data)
    enc = L2GCodec.encrypt(l2j_bytes)
    open(dst, 'wb').write(enc)


def cmd_l2g2pts(paths, out_dir, assume_yes=False, protocol=PROTO_GD):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*.l2g')))
        elif os.path.isfile(p):
            files.append(p)
    jobs = {os.path.splitext(os.path.basename(f))[0] + '_conv.dat': f for f in files}
    if not jobs:
        print(red('  ✗ no .l2g files found.'))
        return 1
    print(f'  {bold("Converting Lucera 2 .l2g -> PTS _conv.dat")}: {len(jobs)} files -> {out_dir}')
    if not _confirm_overwrite(jobs, out_dir, assume_yes):
        return 1
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    names = sorted(jobs)
    for i, name in enumerate(names, 1):
        dst = os.path.join(out_dir, name)
        try:
            rx, ry = region_of(jobs[name])
            l2g2pts_file(jobs[name], dst, rx, ry, protocol=protocol)
        except Exception as e:
            errors.append((name, str(e)))
        progress(i, len(names), 'converting ')
    print(f'\n  {green("✓")} done: {len(names) - len(errors)} files converted to PTS.')
    if errors:
        for n, err in errors:
            print(f'    {red("✗")} {n}: {err}')
    return 2 if errors else 0


def cmd_pts2l2g(paths, out_dir, assume_yes=False):
    files = []
    for p in paths:
        if os.path.isdir(p):
            files += sorted(glob.glob(os.path.join(p, '*_conv.dat')))
        elif os.path.isfile(p):
            files.append(p)
    jobs = {os.path.splitext(os.path.basename(f))[0].replace('_conv', '') + '.l2g': f for f in files}
    if not jobs:
        print(red('  ✗ no _conv.dat files found.'))
        return 1
    print(f'  {bold("Converting PTS _conv.dat -> Lucera 2 .l2g")}: {len(jobs)} files -> {out_dir}')
    if not _confirm_overwrite(jobs, out_dir, assume_yes):
        return 1
    os.makedirs(out_dir, exist_ok=True)
    errors = []
    names = sorted(jobs)
    for i, name in enumerate(names, 1):
        dst = os.path.join(out_dir, name)
        try:
            rx, ry = region_of(jobs[name])
            pts2l2g_file(jobs[name], dst, rx, ry)
        except Exception as e:
            errors.append((name, str(e)))
        progress(i, len(names), 'converting ')
    print(f'\n  {green("✓")} done: {len(names) - len(errors)} files converted to Lucera 2 .l2g.')
    if errors:
        for n, err in errors:
            print(f'    {red("✗")} {n}: {err}')
    return 2 if errors else 0

