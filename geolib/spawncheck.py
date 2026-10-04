#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check npcpos.txt spawn points and territories against PTS geodata.

Read-only on npcpos. L2NPC GetRandomPos / fixed pos={x;y;z} need a geo
layer in the script Z window (territory) or near the script Z (point).
"""

from __future__ import annotations

import collections
import json
import math
import os
import re
import struct

from .formats import GeoError, PTS_HEADER, dec_h, dec_nswe, pts_flat_surface, sniff_format
from .ui import bold, dim, green, progress, red, yellow

REGION = 32768
CELLS = 2048
CELL = 16
OCEAN_LO, OCEAN_HI = -4720, -4580
POINT_OK = 64
POINT_NEAR = 200
REVIEW = ('hole', 'near_z', 'wrong_floor', 'no_geo_hit', 'missing_geo')
_MISS = object()


def world_region(wx, wy):
    """Region indices for a world XY (same as L2OFF CGeoData)."""
    return math.floor(wx / REGION) + 20, math.floor(wy / REGION) + 18


def region_origin(rx, ry):
    return (rx - 20) * REGION, (ry - 18) * REGION


def world_cell(wx, wy, rx, ry):
    west, north = region_origin(rx, ry)
    return int((wx - west) // CELL), int((wy - north) // CELL)


def cell_center(gx, gy, rx, ry):
    west, north = region_origin(rx, ry)
    return west + gx * CELL + CELL // 2, north + gy * CELL + CELL // 2


def is_ocean(h):
    return h is not None and OCEAN_LO <= h <= OCEAN_HI


def pip(x, y, verts):
    """Even-odd point-in-polygon on XY. verts are (x, y, ...)."""
    n = len(verts)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = verts[i][0], verts[i][1]
        xj, yj = verts[j][0], verts[j][1]
        if (yi > y) != (yj > y) and yj != yi:
            xint = xi + (xj - xi) * (y - yi) / (yj - yi)
            if x < xint:
                inside = not inside
        j = i
    return inside


def _read_npcpos(path):
    raw = open(path, 'rb').read()
    if raw[:2] == b'\xff\xfe':
        return raw.decode('utf-16')
    if raw[:2] == b'\xfe\xff':
        return raw.decode('utf-16-be')
    return raw.decode('utf-8', errors='replace')


_TERR = re.compile(
    r'territory_begin\s*\[([^\]]+)\]\s*\{(.+?)\}\s*territory_end', re.S)
_VERT = re.compile(r'\{(-?\d+);(-?\d+);(-?\d+);(-?\d+)\}')
_MAKER = re.compile(r'npcmaker_begin\s*\[([^\]]+)\]')
_NPC = re.compile(
    r'npc(?:_ex)?_begin\s*\[([^\]]+)\](.*?)npc(?:_ex)?_end', re.S)
_POS = re.compile(r'pos=\{(-?\d+);(-?\d+);(-?\d+)(?:;(-?\d+))?\}')


def parse_npcpos(path):
    """Territories and NPC spawn records from npcpos.txt.

    Returns (territories, points, anywhere).
    territories[name] = list of (x, y, zmin, zmax)
    points = list of dict npc/x/y/z/territory
    anywhere[name] = list of npc names using pos=anywhere on that maker
    """
    text = _read_npcpos(path)
    territories = {}
    for m in _TERR.finditer(text):
        name, body = m.group(1), m.group(2)
        verts = [(int(a), int(b), int(c), int(d))
                 for a, b, c, d in _VERT.findall(body)]
        if verts:
            territories[name] = verts

    points = []
    anywhere = collections.defaultdict(list)
    maker = None
    for line in text.splitlines():
        mm = _MAKER.search(line)
        if mm:
            maker = mm.group(1)
        if 'npcmaker_end' in line:
            maker = None
        for nm in _NPC.finditer(line):
            npc, body = nm.group(1), nm.group(2)
            if 'pos=anywhere' in body:
                if maker:
                    anywhere[maker].append(npc)
                continue
            pm = _POS.search(body)
            if pm:
                points.append({
                    'npc': npc,
                    'x': int(pm.group(1)),
                    'y': int(pm.group(2)),
                    'z': int(pm.group(3)),
                    'territory': maker,
                })
    return territories, points, dict(anywhere)


class RegionGeo:
    """Random-access PTS (or L2J) cell layers without expanding the whole map."""

    def __init__(self, path):
        self.path = path
        self.fmt = sniff_format(path)
        with open(path, 'rb') as f:
            self.data = f.read()
        self.offs = []
        if self.fmt == 'pts':
            pos = PTS_HEADER
            unpack = struct.unpack_from
            data = self.data
            for _ in range(65536):
                self.offs.append(pos)
                (t,) = unpack('<H', data, pos)
                pos += 2
                if t == 0x0000:
                    pos += 4
                elif t == 0x0040:
                    pos += 128
                else:
                    for _c in range(64):
                        (nl,) = unpack('<H', data, pos)
                        if nl == 0 or nl > 125:
                            raise GeoError(
                                f'{os.path.basename(path)}: corrupt layer count {nl}')
                        pos += 2 + nl * 2
        elif self.fmt == 'l2j':
            pos = 0
            unpack = struct.unpack_from
            data = self.data
            for _ in range(65536):
                self.offs.append(pos)
                t = data[pos]
                pos += 1
                if t == 0:
                    pos += 2
                elif t == 1:
                    pos += 128
                elif t == 2:
                    for _c in range(64):
                        nl = data[pos]
                        if nl == 0 or nl > 125:
                            raise GeoError(
                                f'{os.path.basename(path)}: corrupt layer count {nl}')
                        pos += 1 + nl * 2
                else:
                    raise GeoError(f'{os.path.basename(path)}: unknown type {t}')
        else:
            raise GeoError(f'unknown geodata format: {path}')

    def cell(self, gx, gy):
        """Layers [(h, nswe), ...] or empty if out of range."""
        if not (0 <= gx < CELLS and 0 <= gy < CELLS):
            return []
        bx, cx = divmod(gx, 8)
        by, cy = divmod(gy, 8)
        ci = cx * 8 + cy
        pos = self.offs[bx * 256 + by]
        data = self.data
        unpack = struct.unpack_from
        if self.fmt == 'pts':
            (t,) = unpack('<H', data, pos)
            pos += 2
            if t == 0x0000:
                fa, fb = unpack('<hh', data, pos)
                return [(pts_flat_surface(fa, fb), 15)]
            if t == 0x0040:
                v = unpack('<64H', data, pos)[ci]
                return [(dec_h(v), dec_nswe(v))]
            for i in range(64):
                (nl,) = unpack('<H', data, pos)
                pos += 2
                if i == ci:
                    ls = unpack(f'<{nl}H', data, pos)
                    return [(dec_h(v), dec_nswe(v)) for v in ls]
                pos += nl * 2
            return []
        t = data[pos]
        pos += 1
        if t == 0:
            (h,) = unpack('<h', data, pos)
            return [(h, 15)]
        if t == 1:
            v = unpack('<64H', data, pos)[ci]
            return [(dec_h(v), dec_nswe(v))]
        for i in range(64):
            nl = data[pos]
            pos += 1
            if i == ci:
                ls = unpack(f'<{nl}H', data, pos)
                return [(dec_h(v), dec_nswe(v)) for v in ls]
            pos += nl * 2
        return []


def closest_layer(layers, z):
    if not layers:
        return None
    return min(layers, key=lambda ln: abs(ln[0] - z))


def layer_in_window(layers, zmin, zmax):
    best = None
    mid = (zmin + zmax) / 2.0
    for h, n in layers:
        if zmin <= h <= zmax:
            if best is None or abs(h - mid) < abs(best[0] - mid):
                best = (h, n)
    return best


def classify_point(layers, z):
    """bucket, geo_z, |delta| for a fixed pos={x;y;z}."""
    if not layers:
        return 'no_geo_hit', None, None
    h, _n = closest_layer(layers, z)
    ad = abs(h - z)
    if ad <= POINT_OK:
        return 'ok', h, ad
    if is_ocean(h) and not is_ocean(z):
        return 'hole', h, ad
    if ad <= POINT_NEAR:
        return 'near_z', h, ad
    return 'wrong_floor', h, ad


def classify_territory(hit, closest_h, closest_ad, zmin, zmax, name):
    if zmax is not None and (zmax > 50000 or (zmin is not None and zmin > 10000)):
        return 'skip_broken'
    if hit:
        return 'ok'
    skyish = (
        'sky' in name.lower()
        or (zmin is not None and zmin >= 2000 and (closest_h is None or closest_h < zmin))
    )
    if closest_h is None:
        return 'skip_sky' if skyish else 'no_geo_hit'
    if is_ocean(closest_h) and (zmax is None or zmax > -4500):
        return 'hole'
    if closest_ad is not None and closest_ad <= POINT_NEAR:
        return 'near_z'
    if skyish:
        return 'skip_sky'
    return 'wrong_floor'


def _geo_path(geodir, rx, ry):
    p = os.path.join(geodir, f'{rx}_{ry}_conv.dat')
    if os.path.isfile(p):
        return p
    p = os.path.join(geodir, f'{rx}_{ry}.l2j')
    if os.path.isfile(p):
        return p
    return None


def _centroid(verts):
    cx = sum(v[0] for v in verts) // len(verts)
    cy = sum(v[1] for v in verts) // len(verts)
    zmin = min(v[2] for v in verts)
    zmax = max(v[3] for v in verts)
    return cx, cy, zmin, zmax


def _scan_territory_region(geo, verts, zmin, zmax, rx, ry):
    """Count cells in this region whose center is in the polygon and in Z.

    Returns (hits, closest_h, closest_ad, sampled).
    """
    west, north = region_origin(rx, ry)
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    gx0 = max(0, int((min(xs) - west) // CELL))
    gx1 = min(CELLS - 1, int((max(xs) - west) // CELL))
    gy0 = max(0, int((min(ys) - north) // CELL))
    gy1 = min(CELLS - 1, int((max(ys) - north) // CELL))
    if gx0 > gx1 or gy0 > gy1:
        return 0, None, None, 0

    hits = 0
    closest_h = None
    closest_ad = None
    sampled = 0
    nvert = len(verts)
    mid = (zmin + zmax) / 2.0
    for gy in range(gy0, gy1 + 1):
        py = north + gy * CELL + CELL // 2
        xs_hit = []
        j = nvert - 1
        for i in range(nvert):
            x1, y1 = verts[j][0], verts[j][1]
            x2, y2 = verts[i][0], verts[i][1]
            if (y1 > py) != (y2 > py) and y2 != y1:
                xs_hit.append(x1 + (x2 - x1) * (py - y1) / (y2 - y1))
            j = i
        xs_hit.sort()
        for k in range(0, len(xs_hit) - 1, 2):
            xa, xb = xs_hit[k], xs_hit[k + 1]
            gxa = max(gx0, int((xa - west) // CELL))
            gxb = min(gx1, int((xb - west) // CELL))
            for gx in range(gxa, gxb + 1):
                sampled += 1
                layers = geo.cell(gx, gy)
                if not layers:
                    continue
                win = layer_in_window(layers, zmin, zmax)
                if win:
                    hits += 1
                    continue
                h, _n = closest_layer(layers, mid)
                ad = min(abs(h - zmin), abs(h - zmax), abs(h - mid))
                if closest_ad is None or ad < closest_ad:
                    closest_ad = ad
                    closest_h = h
    return hits, closest_h, closest_ad, sampled


def _unique_points(points):
    groups = collections.OrderedDict()
    for p in points:
        key = (p['x'], p['y'], p['z'])
        g = groups.get(key)
        if g is None:
            g = {'x': p['x'], 'y': p['y'], 'z': p['z'],
                 'territory': p['territory'], 'npcs': []}
            groups[key] = g
        g['npcs'].append(p['npc'])
    return list(groups.values())


def _pin(name, region, wx, wy, geo_z, zmin, zmax, delta, side, bucket, verts=None):
    rx, ry = (int(x) for x in region.split('_')) if region else (0, 0)
    gx, gy = world_cell(wx, wy, rx, ry) if region else (0, 0)
    return {
        'name': name,
        'region': region,
        'wx': wx,
        'wy': wy,
        'geo_z': geo_z,
        'zmin': zmin,
        'zmax': zmax,
        'delta': delta,
        'side': side,
        'bucket': bucket,
        'action': {
            'near_z': 'widen_z',
            'hole': 'move_xy',
            'wrong_floor': 'check_floor',
            'no_geo_hit': 'move_xy',
            'missing_geo': 'missing_region',
        }.get(bucket, 'ignore'),
        'bx': max(0, min(255, gx // 8)),
        'by': max(0, min(255, gy // 8)),
        'cx': gx % 8,
        'cy': gy % 8,
        'poly': [[v[0], v[1]] for v in (verts or [])],
    }


def cmd_spawncheck(geodir, npcpos, out_json=None):
    """Check every npcpos spawn against PTS/L2J geodata. Does not edit npcpos."""
    if not os.path.isdir(geodir):
        print(red(f'  ✗ geodata folder not found: {geodir}'))
        return 1
    if not os.path.isfile(npcpos):
        print(red(f'  ✗ npcpos not found: {npcpos}'))
        return 1

    print(f'  {bold("Spawncheck")} {os.path.basename(npcpos)} vs {geodir}\n')
    territories, points, anywhere = parse_npcpos(npcpos)
    uniq = _unique_points(points)
    used = set(anywhere)
    print(dim(f'  territories {len(territories)}  anywhere {len(used)}  '
              f'fixed pos {len(points)} ({len(uniq)} unique XYZ)'))

    cache = collections.OrderedDict()

    def geo_for(rx, ry):
        key = (rx, ry)
        hit = cache.get(key, _MISS)
        if hit is not _MISS:
            cache.move_to_end(key)
            return hit
        path = _geo_path(geodir, rx, ry)
        geo = RegionGeo(path) if path else None
        cache[key] = geo
        if len(cache) > 6:
            cache.popitem(last=False)
        return geo

    buckets = collections.Counter()
    failures = []

    # ── fixed positions ──────────────────────────────────────────────
    uniq.sort(key=lambda p: world_region(p['x'], p['y']))
    n = len(uniq)
    for i, p in enumerate(uniq, 1):
        rx, ry = world_region(p['x'], p['y'])
        region = f'{rx}_{ry}'
        geo = geo_for(rx, ry)
        if geo is None:
            bucket, hz, ad = 'missing_geo', None, None
        else:
            gx, gy = world_cell(p['x'], p['y'], rx, ry)
            bucket, hz, ad = classify_point(geo.cell(gx, gy), p['z'])
        buckets['point_' + bucket] += 1
        if bucket != 'ok':
            side = 'unknown'
            if hz is not None:
                side = 'above' if hz > p['z'] else ('below' if hz < p['z'] else 'in_z')
            name = p['npcs'][0]
            if len(p['npcs']) > 1:
                name = f'{name} +{len(p["npcs"]) - 1}'
            pin = _pin(name, region, p['x'], p['y'], hz, p['z'], p['z'],
                       ad, side, bucket if bucket != 'missing_geo' else 'no_geo_hit')
            pin['kind'] = 'point'
            pin['npc_count'] = len(p['npcs'])
            pin['territory'] = p['territory']
            failures.append(pin)
        if i == n or i % 2000 == 0:
            progress(i, n, 'points ')
    print()

    # ── pos=anywhere territories ─────────────────────────────────────
    names = sorted(used)
    tn = len(names)
    for i, name in enumerate(names, 1):
        verts = territories.get(name)
        if not verts:
            buckets['territory_missing_script'] += 1
            pin = _pin(name, '0_0', 0, 0, None, None, None, None, 'unknown',
                       'no_geo_hit')
            pin['kind'] = 'territory'
            pin['npc_count'] = len(anywhere[name])
            failures.append(pin)
            continue
        cx, cy, zmin, zmax = _centroid(verts)
        rx, ry = world_region(cx, cy)
        region = f'{rx}_{ry}'
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        rx0 = world_region(min(xs), 0)[0]
        rx1 = world_region(max(xs), 0)[0]
        ry0 = world_region(0, min(ys))[1]
        ry1 = world_region(0, max(ys))[1]
        regs = {(arx, ary)
                for arx in range(rx0, rx1 + 1)
                for ary in range(ry0, ry1 + 1)}

        hits = 0
        closest_h = None
        closest_ad = None
        missing = []
        sampled = 0
        for arx, ary in sorted(regs):
            geo = geo_for(arx, ary)
            if geo is None:
                missing.append(f'{arx}_{ary}')
                continue
            h, ch, cad, ncell = _scan_territory_region(
                geo, verts, zmin, zmax, arx, ary)
            hits += h
            sampled += ncell
            if cad is not None and (closest_ad is None or cad < closest_ad):
                closest_ad, closest_h = cad, ch

        geo_c = geo_for(rx, ry)
        center_ok = False
        center_h = None
        if geo_c is not None:
            gx, gy = world_cell(cx, cy, rx, ry)
            layers = geo_c.cell(gx, gy)
            win = layer_in_window(layers, zmin, zmax) if layers else None
            if win:
                center_ok = True
                center_h = win[0]
            elif layers:
                center_h = closest_layer(layers, (zmin + zmax) / 2.0)[0]

        if missing and hits == 0 and geo_c is None:
            bucket = 'missing_geo'
        else:
            bucket = classify_territory(
                hits > 0, closest_h, closest_ad, zmin, zmax, name)
        buckets['territory_' + bucket] += 1
        if center_ok:
            buckets['territory_center_ok'] += 1
        elif bucket == 'ok':
            buckets['territory_center_miss'] += 1

        if bucket != 'ok':
            side = 'unknown'
            gz = center_h if center_h is not None else closest_h
            delta = None
            if gz is not None:
                if gz > zmax:
                    side, delta = 'above', gz - zmax
                elif gz < zmin:
                    side, delta = 'below', zmin - gz
                else:
                    side, delta = 'in_z', 0
            view_bucket = bucket if bucket != 'missing_geo' else 'no_geo_hit'
            pin = _pin(name, region, cx, cy, gz, zmin, zmax, delta, side,
                       view_bucket, verts)
            pin['kind'] = 'territory'
            pin['npc_count'] = len(anywhere[name])
            pin['hits'] = hits
            pin['sampled'] = sampled
            pin['center_ok'] = center_ok
            failures.append(pin)
        if i == tn or i % 200 == 0:
            progress(i, tn, 'territory')
    print()

    point_fail = sum(v for k, v in buckets.items()
                     if k.startswith('point_') and k != 'point_ok')
    terr_fail = sum(v for k, v in buckets.items()
                    if k.startswith('territory_') and k not in (
                        'territory_ok', 'territory_center_ok',
                        'territory_center_miss', 'territory_skip_sky',
                        'territory_skip_broken'))
    skip = buckets['territory_skip_sky'] + buckets['territory_skip_broken']
    print(f'  {green("✓")} fixed pos ok: {green(str(buckets["point_ok"]))} / {len(uniq)} unique')
    if point_fail:
        print(f'  {red("✗")} fixed pos fail: {red(str(point_fail))}')
        for k in ('point_hole', 'point_near_z', 'point_wrong_floor',
                  'point_no_geo_hit', 'point_missing_geo'):
            if buckets[k]:
                print(f'      {k[6:]}: {buckets[k]}')
    print(f'  {green("✓")} anywhere ok: {green(str(buckets["territory_ok"]))} / {len(names)} territories')
    if buckets['territory_center_miss']:
        print(dim(f'      center miss but cells exist: {buckets["territory_center_miss"]} '
                  '(L2NPC logs CenterPos; spawn still possible)'))
    if terr_fail:
        print(f'  {red("✗")} anywhere fail: {red(str(terr_fail))}')
        for k in ('territory_hole', 'territory_near_z', 'territory_wrong_floor',
                  'territory_no_geo_hit', 'territory_missing_geo',
                  'territory_missing_script'):
            if buckets[k]:
                print(f'      {k[10:]}: {buckets[k]}')
    if skip:
        print(f'  {yellow("⚠")} skipped sky/broken: {skip}')

    view_counts = collections.Counter()
    for s in failures:
        view_counts[s['bucket']] += 1
    payload = {
        'source': os.path.abspath(npcpos),
        'geodata': os.path.abspath(geodir),
        'counts': dict(view_counts),
        'buckets': dict(buckets),
        'n_points': len(points),
        'n_unique_xyz': len(uniq),
        'n_anywhere': len(names),
        'spawns': failures,
    }
    if out_json:
        os.makedirs(os.path.dirname(os.path.abspath(out_json)) or '.', exist_ok=True)
        with open(out_json, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=1)
        print(dim(f'\n  wrote {out_json} ({len(failures)} pins)'))

    byr = collections.Counter(s['region'] for s in failures if s['bucket'] in REVIEW)
    if byr:
        print('\n  review by region:')
        for r, c in byr.most_common(20):
            print(f'    {c:4} {r}')
    return 0 if point_fail + terr_fail == 0 else 2
