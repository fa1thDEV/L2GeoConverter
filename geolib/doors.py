#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DoorData footprints: force NSWE open where official geo leaves gates walkable.

UNR Mover meshes stay omitted. After NSWE from walls/steps, cells whose XY
overlaps a non-wall door range and whose layer Z sits in the door height
are set to NSWE=15 so DoorData can close them at runtime.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from .formats import GeoError, quant_h

CELLS = 2048
REGION = 32768
Z_SLACK = 48
_DOOR_RE = re.compile(
    r'door_begin\s+\[([^\]]+)\]\s+(.*?)\s+door_end',
    re.DOTALL | re.IGNORECASE,
)
_POS_RE = re.compile(r'pos=\{(-?\d+);(-?\d+);(-?\d+)\}')
_RANGE_RE = re.compile(r'\{(-?\d+);(-?\d+);(-?\d+)\}')
_TYPE_RE = re.compile(r'type=(\S+)')
_HEIGHT_RE = re.compile(r'height=(\d+)')


def find_doordata(client_dir, explicit=None):
    """Path to doordata.txt, or None.

    Lookup: ``explicit`` (``--doordata``), then ``L2_DOORDATA``, then
    ``<client>/doordata.txt`` and ``<client>/Script/doordata.txt``.
    """
    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get('L2_DOORDATA')
    if env:
        candidates.append(env)
    if client_dir:
        candidates += [
            os.path.join(client_dir, 'doordata.txt'),
            os.path.join(client_dir, 'Script', 'doordata.txt'),
        ]
    for p in candidates:
        if p and os.path.isfile(p):
            return p
    return None


def _read_text(path):
    raw = Path(path).read_bytes()
    if raw[:2] == b'\xff\xfe':
        return raw.decode('utf-16')
    if raw[:2] == b'\xfe\xff':
        return raw.decode('utf-16-be')
    return raw.decode('utf-8', errors='replace')


def parse_doors(path):
    """List of dicts: name, typ, x0,y0,x1,y1, z0,z1. Skips wall_type."""
    text = _read_text(path)
    out = []
    for m in _DOOR_RE.finditer(text):
        name, body = m.group(1), m.group(2)
        tm = _TYPE_RE.search(body)
        typ = (tm.group(1) if tm else '').lower()
        if typ == 'wall_type':
            continue
        pos = _POS_RE.search(body)
        pts = [(int(a), int(b), int(c)) for a, b, c in _RANGE_RE.findall(body)]
        if pos:
            pts.append((int(pos.group(1)), int(pos.group(2)), int(pos.group(3))))
        if not pts:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        zs = [p[2] for p in pts]
        ht = _HEIGHT_RE.search(body)
        height = int(ht.group(1)) if ht else 0
        z0, z1 = min(zs), max(zs)
        if height:
            z0 = min(z0, z1 - height)
        out.append({
            'name': name, 'typ': typ,
            'x0': min(xs), 'x1': max(xs),
            'y0': min(ys), 'y1': max(ys),
            'z0': z0, 'z1': z1,
        })
    return out


def door_index_for_region(doors, west, north):
    """(gx, gy) → (zmin, zmax) for cells in this square that overlap a door."""
    east, south = west + REGION, north + REGION
    idx = {}
    for d in doors:
        x0, x1, y0, y1 = d['x0'], d['x1'], d['y0'], d['y1']
        if x1 < west or x0 >= east or y1 < north or y0 >= south:
            continue
        if x1 - x0 < 16:
            mid = (x0 + x1) / 2.0
            x0, x1 = mid - 8, mid + 8
        if y1 - y0 < 16:
            mid = (y0 + y1) / 2.0
            y0, y1 = mid - 8, mid + 8
        gx0 = max(0, int((x0 - west) // 16))
        gx1 = min(CELLS - 1, int((x1 - west) // 16))
        gy0 = max(0, int((y0 - north) // 16))
        gy1 = min(CELLS - 1, int((y1 - north) // 16))
        z0, z1 = d['z0'] - Z_SLACK, d['z1'] + Z_SLACK
        for gx in range(gx0, gx1 + 1):
            cx0 = west + gx * 16
            cx1 = cx0 + 16
            if cx1 <= x0 or cx0 >= x1:
                continue
            for gy in range(gy0, gy1 + 1):
                cy0 = north + gy * 16
                cy1 = cy0 + 16
                if cy1 <= y0 or cy0 >= y1:
                    continue
                key = (gx, gy)
                old = idx.get(key)
                if old is None:
                    idx[key] = [z0, z1]
                else:
                    old[0] = min(old[0], z0)
                    old[1] = max(old[1], z1)
    return {k: (v[0], v[1]) for k, v in idx.items()}


def open_door_nswe(nswe, gx, gy, z, index):
    """NSWE=15 if this layer sits in a door footprint.

    Check raw Z and the packed 8-grid height: generate applies this before
    pack, but the file stores quant_h(z). A ray 1–4 units outside the window
    can pack inside it (Seed of Destruction gates).
    """
    if not index:
        return nswe
    span = index.get((int(gx), int(gy)))
    if span is None:
        return nswe
    z0, z1 = span
    if z0 <= z <= z1:
        return 15
    q = quant_h(z)
    if q != z and z0 <= q <= z1:
        return 15
    return nswe


def load_region_doors(path, west, north):
    """Parse doordata and index cells for one region. Empty dict if path is None."""
    if not path:
        return {}
    if not os.path.isfile(path):
        raise GeoError(f'doordata not found: {path}')
    return door_index_for_region(parse_doors(path), west, north)
