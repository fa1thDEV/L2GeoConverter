#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pathnode.bin/.idx compiler — 64-bit PathMaker replacement.

PathMaker.exe is 32-bit and aborts (`bad_alloc` → `__fastfail(7)`) once the
candidate graph plus mapped PTS no longer fit in ~4 GB. This writer emits the
same files L2Server already loads:

  pathnode.bin  dummy index 0 plus N records of 11×i32 (x, y, z, 8 links)
  pathnode.idx  ``Total = N`` then ``Zone(rx,ry)[has]`` and section lines
  pathnode.txt  optional debug dump (PathMaker always wrote this; 1–2 GB)

Algorithm (PathMaker's two seed passes, thinned so the bin stays under
Loader's signed 2 GiB ``long`` / ``_filelength`` check):

  * 256-unit sections (16×16 geo cells), 128×128 per region.
  * T-junction seed: a layer whose NSWE has exactly 3 open sides, at the
    cell centre (origin + gx×16+8, gy×16+8).
  * Fill: every walkable layer at the section centre that does not already
    have a same-floor node (so a roof T-junction cannot starve the street).
  * Merge nodes in a section closer than 48 world units (PathMaker used 7,
    which kept every corridor-edge cell on thick PTS).
  * Cap 16 nodes per section, round-robin across Z floors (PathMaker 255).
  * 8-neighbour graph: closest node in each octant, max 384 units, that
    CGeoData::MoveStraight3 can walk (NSWE + end |ΔZ| ≤ 48). L2Server A*
    trusts stored edges with no geo check, so a wall-crossing link is a
    waypoint through the obstacle.
  * Link uses packed NSWE mmap grids, a shared section CSR, mmap extra
    layers (not pickle), and a worker pool with the same 80% CPU cap /
    2 GB free-RAM floor as ``generate``. Taichi is generate-only.

Zone grid is PathMaker-GF: X 10–29, Y 10–26. Index 0 in the bin is unused
(L2Server treats link 0 as “no edge”).
"""

from __future__ import annotations

import math
import mmap
import os
import shutil
import struct
import tempfile
from array import array
from collections import defaultdict

from .formats import (
    BLOCKS, PTS_HEADER, GeoError, dec_h, dec_nswe, pts_flat_surface,
    region_of, sniff_format,
)
from .ui import bold, dim, green, progress, red, yellow

RECORD = 44
REGION = 32768
CELL = 16
SECTION = 256
SEC_CELLS = SECTION // CELL          # 16
SECS = REGION // SECTION             # 128
CELLS = REGION // CELL               # 2048
RX0, RX1 = 10, 30                    # [10, 29]
RY0, RY1 = 10, 27                    # [10, 26]
MERGE_DIST = 48.0                    # ~3 cells; PathMaker's 7 kept T-junction spam
MAX_PER_SECTION = 16                 # official density is ~4 / section
FLOOR_Z = 64                         # |dz| below this = same floor
MAX_LINK = 384                       # 256 * sqrt(2) plus a little
MAX_STRAIGHT = 8192                  # CGeoData::MoveStraight3 cap in FindPath
END_DZ = 48                          # MoveStraight3 dest |ΔZ| fail (0x30)
LOADER_MAX_BYTES = 2147483647        # signed 32-bit file size Loader accepts
NSWE_N, NSWE_S, NSWE_W, NSWE_E = 8, 4, 2, 1
NCELL = CELLS * CELLS                # packed geo cells per region
NRX = RX1 - RX0
NRY = RY1 - RY0
NSEC = NRX * NRY * SECS * SECS       # CSR slots for the PathMaker-GF grid
NODE_I32 = 7                         # x y z rx ry sx sy
LINK_I32 = 8
PARALLEL_MIN_NODES = 80000           # below this, stay in-process (tests)
LINK_WORKER_RAM_GB = 0.35            # extra RSS per link worker (geo + CSR mmap)


def region_origin(rx, ry):
    return (rx - 20) * REGION, (ry - 18) * REGION


def pack_z(h):
    """Height stored on a node — PathMaker ``sar 1; and ~7`` of the cell word."""
    return (int(h) >> 3) << 3


def popcount4(nswe):
    n = nswe & 0xF
    return (n & 1) + ((n >> 1) & 1) + ((n >> 2) & 1) + ((n >> 3) & 1)


def octant(dx, dy):
    """0=E 1=NE 2=N 3=NW 4=W 5=SW 6=S 7=SE. None if coincident XY."""
    if dx == 0 and dy == 0:
        return None
    i = int(round(math.atan2(dy, dx) / (math.pi / 4.0))) % 8
    return i


def encode_record(x, y, z, links):
    ln = list(links)[:8] + [0] * 8
    return struct.pack('<11i', int(x), int(y), int(z), *ln[:8])


def decode_record(buf):
    t = struct.unpack_from('<11i', buf)
    return t[0], t[1], t[2], t[3:]


def parse_idx(text):
    """idx text → (total, { (rx,ry): [(ox,oy,count), ...] })."""
    total = 0
    zones = {}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith('Total'):
            total = int(line.split('=')[-1])
            continue
        if line.startswith('--- Zone'):
            inner = line[line.find('(') + 1: line.find(')')]
            a, b = inner.split(',')
            cur = (int(a), int(b))
            zones[cur] = []
            continue
        parts = line.split()
        if cur is not None and len(parts) == 3:
            zones[cur].append((int(parts[0]), int(parts[1]), int(parts[2])))
    return total, zones


def read_bin(path):
    with open(path, 'rb') as f:
        data = f.read()
    if len(data) % RECORD:
        raise GeoError(f'{path}: size {len(data)} is not a multiple of {RECORD}')
    n = len(data) // RECORD
    recs = [decode_record(data[i * RECORD:(i + 1) * RECORD]) for i in range(n)]
    return recs


def _listed_pts(geodir, regions=None):
    """Ordered (rx, ry, path) from geo_index.txt or a directory scan."""
    want = None
    if regions:
        want = set()
        for r in regions:
            a, b = r.replace('-', '_').split('_')[:2]
            want.add((int(a), int(b)))
    idx = os.path.join(geodir, 'geo_index.txt')
    out = []
    seen = set()
    if os.path.isfile(idx):
        with open(idx, encoding='utf-8', errors='replace') as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        names = lines[1:] if lines and lines[0].isdigit() else lines
        for name in names:
            if not name.endswith('.dat'):
                continue
            path = name if os.path.isabs(name) else os.path.join(geodir, os.path.basename(name))
            if not os.path.isfile(path):
                continue
            rx, ry = region_of(path)
            if want is not None and (rx, ry) not in want:
                continue
            if (rx, ry) in seen:
                continue
            seen.add((rx, ry))
            out.append((rx, ry, path))
    if not out:
        for fn in sorted(os.listdir(geodir)):
            if not fn.endswith('_conv.dat'):
                continue
            path = os.path.join(geodir, fn)
            rx, ry = region_of(path)
            if want is not None and (rx, ry) not in want:
                continue
            if (rx, ry) in seen:
                continue
            seen.add((rx, ry))
            out.append((rx, ry, path))
    return out


def _walk_pts(path):
    """Yield (gx, gy, layers) for every cell. layers = [(h, nswe), ...].

    Block and cell order match L2Server ``CGeoData`` / generate:
    file block ``b = bx * 256 + by``, cells ``i = cx * 8 + cy``.
    The swapped ``b = bx + by * 256`` walk planted nodes on the
    transposed cell (Pantheon plaza read as dirt 3k below the pawn).
    """
    fmt = sniff_format(path)
    if fmt != 'pts':
        raise GeoError(f'pathnode compiler wants PTS *_conv.dat, not {path}')
    with open(path, 'rb') as f:
        data = f.read()
    pos = PTS_HEADER
    unpack = struct.unpack_from
    for b in range(BLOCKS):
        bx, by = b >> 8, b & 255
        gx0, gy0 = bx * 8, by * 8
        (t,) = unpack('<H', data, pos)
        pos += 2
        if t == 0x0000:
            fa, fb = unpack('<hh', data, pos)
            pos += 4
            h = pts_flat_surface(fa, fb)
            layer = [(h, 15)]
            for lx in range(8):
                for ly in range(8):
                    yield gx0 + lx, gy0 + ly, layer
        elif t == 0x0040:
            cells = unpack('<64H', data, pos)
            pos += 128
            i = 0
            for lx in range(8):
                for ly in range(8):
                    v = cells[i]
                    i += 1
                    yield gx0 + lx, gy0 + ly, [(dec_h(v), dec_nswe(v))]
        else:
            for lx in range(8):
                for ly in range(8):
                    (nl,) = unpack('<H', data, pos)
                    pos += 2
                    if nl == 0 or nl > 125:
                        raise GeoError(f'{os.path.basename(path)} block {b}: '
                                       f'corrupt layer count {nl}')
                    ls = unpack(f'<{nl}H', data, pos)
                    pos += nl * 2
                    yield gx0 + lx, gy0 + ly, [(dec_h(v), dec_nswe(v)) for v in ls]


def _same_floor(z0, z1):
    return abs(z0 - z1) < FLOOR_Z


def _sec_slot(rx, ry, sx, sy):
    """CSR index for a PathMaker-GF section, or None if outside the grid."""
    if not (RX0 <= rx < RX1 and RY0 <= ry < RY1):
        return None
    if not (0 <= sx < SECS and 0 <= sy < SECS):
        return None
    return ((rx - RX0) * NRY + (ry - RY0)) * (SECS * SECS) + sx * SECS + sy


def _write_pack(pack_dir, rx, ry, h_arr, ns_arr, extra):
    """One region of packed surface + leftover layers for mmap linkers."""
    os.makedirs(pack_dir, exist_ok=True)
    with open(os.path.join(pack_dir, f'{rx}_{ry}.h16'), 'wb') as f:
        f.write(h_arr.tobytes())
    with open(os.path.join(pack_dir, f'{rx}_{ry}.nswe'), 'wb') as f:
        f.write(ns_arr.tobytes())
    if not extra:
        return
    off = array('i', [-1]) * NCELL
    blob = bytearray()
    for i, layers in extra.items():
        off[i] = len(blob)
        blob.append(len(layers) & 0xFF)
        for h, ns in layers:
            blob += struct.pack('<hB', int(h), int(ns) & 0xF)
    with open(os.path.join(pack_dir, f'{rx}_{ry}.exoff'), 'wb') as f:
        f.write(off.tobytes())
    with open(os.path.join(pack_dir, f'{rx}_{ry}.exdat'), 'wb') as f:
        f.write(blob)


def _seeds_for_region(path, rx, ry, pack_dir=None):
    """Section dict (sx,sy) → list of (x,y,z) before merge/cap."""
    west, north = region_origin(rx, ry)
    tjunct = defaultdict(list)
    centre = {}
    h_arr = ns_arr = extra = None
    if pack_dir is not None:
        h_arr = array('h', bytes(NCELL * 2))
        ns_arr = array('B', b'\x0f' * NCELL)
        extra = {}
    for gx, gy, layers in _walk_pts(path):
        if h_arr is not None:
            i = gy * CELLS + gx
            h_arr[i] = layers[0][0]
            ns_arr[i] = layers[0][1] & 0xF
            if len(layers) > 1:
                extra[i] = tuple(layers[1:])
        sx, sy = gx // SEC_CELLS, gy // SEC_CELLS
        if gx % SEC_CELLS == SEC_CELLS // 2 and gy % SEC_CELLS == SEC_CELLS // 2:
            centre[(sx, sy)] = layers
        wx8 = west + gx * CELL + CELL // 2
        wy8 = north + gy * CELL + CELL // 2
        for h, ns in layers:
            if popcount4(ns) == 3:
                tjunct[(sx, sy)].append((wx8, wy8, pack_z(h)))
    out = {}
    for sy in range(SECS):
        for sx in range(SECS):
            nodes = list(tjunct.get((sx, sy), ()))
            layers = centre.get((sx, sy), [])
            cx = west + sx * SECTION + SECTION // 2
            cy = north + sy * SECTION + SECTION // 2
            have_z = [n[2] for n in nodes]
            for h, ns in layers:
                if (ns & 0xF) == 0:
                    continue
                z = pack_z(h)
                if any(_same_floor(z, ez) for ez in have_z):
                    continue
                nodes.append((cx, cy, z))
                have_z.append(z)
            if not nodes and layers:
                nodes.append((cx, cy, pack_z(layers[0][0])))
            out[(sx, sy)] = nodes
    if pack_dir is not None:
        _write_pack(pack_dir, rx, ry, h_arr, ns_arr, extra)
    return out


def _cap_section(nodes):
    """Keep at most MAX_PER_SECTION, spreading across Z floors first."""
    if len(nodes) <= MAX_PER_SECTION:
        return nodes
    floors = defaultdict(list)
    for n in nodes:
        floors[n[2] // FLOOR_Z].append(n)
    out = []
    while len(out) < MAX_PER_SECTION and floors:
        empty = []
        for key, bucket in floors.items():
            if not bucket:
                empty.append(key)
                continue
            out.append(bucket.pop(0))
            if len(out) >= MAX_PER_SECTION:
                break
        for key in empty:
            del floors[key]
    return out


def _merge_section(nodes):
    """Keep the first of any pair closer than MERGE_DIST. Then cap."""
    kept = []
    limit2 = MERGE_DIST * MERGE_DIST
    for x, y, z in nodes:
        too_close = False
        for ox, oy, oz in kept:
            dx, dy, dz = x - ox, y - oy, z - oz
            if dx * dx + dy * dy + dz * dz < limit2:
                too_close = True
                break
        if not too_close:
            kept.append((x, y, z))
    return _cap_section(kept)


def compile_region(path, rx, ry):
    """(sx,sy) → merged [(x,y,z), ...] for one PTS file."""
    raw = _seeds_for_region(path, rx, ry)
    return {k: _merge_section(v) for k, v in raw.items() if v}


class _MmapWorld:
    """Packed PTS per region (int16 height + u8 NSWE + optional extra layers).

    Files are mmap'd so link workers share one copy via the page cache
    instead of each holding parse_region Python lists (~16 GB before).
    """

    def __init__(self, pack_dir):
        self.pack_dir = pack_dir
        self._cache = {}
        self._fps = []

    def close(self):
        for hit in self._cache.values():
            if not hit:
                continue
            for mm in hit:
                if mm is not None:
                    mm.close()
        self._cache.clear()
        for fp in self._fps:
            try:
                fp.close()
            except OSError:
                pass
        self._fps.clear()

    def _load(self, rx, ry):
        key = (rx, ry)
        if key in self._cache:
            return self._cache[key]
        hp = os.path.join(self.pack_dir, f'{rx}_{ry}.h16')
        np = os.path.join(self.pack_dir, f'{rx}_{ry}.nswe')
        if not (os.path.isfile(hp) and os.path.isfile(np)):
            self._cache[key] = None
            return None
        hf = open(hp, 'rb')
        nf = open(np, 'rb')
        self._fps.extend((hf, nf))
        h_mm = mmap.mmap(hf.fileno(), 0, access=mmap.ACCESS_READ)
        ns_mm = mmap.mmap(nf.fileno(), 0, access=mmap.ACCESS_READ)
        off_mm = dat_mm = None
        op = os.path.join(self.pack_dir, f'{rx}_{ry}.exoff')
        dp = os.path.join(self.pack_dir, f'{rx}_{ry}.exdat')
        if os.path.isfile(op) and os.path.isfile(dp):
            of = open(op, 'rb')
            df = open(dp, 'rb')
            self._fps.extend((of, df))
            off_mm = mmap.mmap(of.fileno(), 0, access=mmap.ACCESS_READ)
            dat_mm = mmap.mmap(df.fileno(), 0, access=mmap.ACCESS_READ)
        hit = (h_mm, ns_mm, off_mm, dat_mm)
        self._cache[key] = hit
        return hit

    def cell(self, gx_g, gy_g):
        rx = (gx_g // CELLS) + 10
        ry = (gy_g // CELLS) + 10
        pack = self._load(rx, ry)
        if pack is None:
            return None
        h_mm, ns_mm, off_mm, dat_mm = pack
        gx = gx_g - (rx - 10) * CELLS
        gy = gy_g - (ry - 10) * CELLS
        if not (0 <= gx < CELLS and 0 <= gy < CELLS):
            return None
        i = gy * CELLS + gx
        first = (struct.unpack_from('<h', h_mm, i * 2)[0], ns_mm[i] & 0xF)
        if off_mm is None:
            return (first,)
        o = struct.unpack_from('<i', off_mm, i * 4)[0]
        if o < 0:
            return (first,)
        n = dat_mm[o]
        more = []
        p = o + 1
        for _ in range(n):
            h, ns = struct.unpack_from('<hB', dat_mm, p)
            more.append((h, ns & 0xF))
            p += 3
        return (first,) + tuple(more)


def _layers_at(geo, gx_g, gy_g):
    """Global geo-cell → layer list, or None if the region is missing."""
    return geo.cell(gx_g, gy_g)


def _pick_layer(layers, z):
    best = layers[0]
    bd = abs(best[0] - z)
    for lay in layers[1:]:
        d = abs(lay[0] - z)
        if d < bd:
            best, bd = lay, d
    return best


def move_straight(geo, x0, y0, z0, x1, y1, z1):
    """True if CGeoData::MoveStraight3 would succeed (NSWE walk, |ΔZ|≤48).

    FindPath uses this for the click and then trusts pathnode edges with no
    further geo test — a link that fails here is a waypoint into a wall.
    """
    dx = float(x1 - x0)
    dy = float(y1 - y0)
    dist = math.hypot(dx, dy)
    gx = (int(x0) + 0x50000) >> 4
    gy = (int(y0) + 0x40000) >> 4
    layers = _layers_at(geo, gx, gy)
    if not layers:
        return False
    if dist < 1e-3:
        return True
    h, nswe = _pick_layer(layers, z0)
    z = float(h)
    ux, uy = dx / dist * CELL, dy / dist * CELL
    x, y = float(x0), float(y0)
    travelled = 0.0
    while travelled < dist and travelled < MAX_STRAIGHT:
        x += ux
        y += uy
        travelled += CELL
        ngx = (int(x) + 0x50000) >> 4
        ngy = (int(y) + 0x40000) >> 4
        if ngx == gx and ngy == gy:
            continue
        if ngx != gx:
            bit = NSWE_E if ngx > gx else NSWE_W
            if (nswe & bit) != bit:
                return False
        if ngy != gy:
            bit = NSWE_S if ngy > gy else NSWE_N
            if (nswe & bit) != bit:
                return False
        layers = _layers_at(geo, ngx, ngy)
        if not layers:
            return False
        h, nswe = _pick_layer(layers, z)
        z = float(h)
        gx, gy = ngx, ngy
    return abs(z - z1) <= END_DZ


def _link(nodes, buckets, geo=None, on_progress=None):
    """Fill nodes[i].links (8 ints, 0 = none). nodes[0] is the dummy.

    Closest node in each octant within MAX_LINK that MoveStraight3 can
    walk. Without the geo test L2Server A* routes through walls: it does
    not re-check NSWE on stored edges.
    """
    n = len(nodes)
    max2 = MAX_LINK * MAX_LINK
    cands = [[] for _ in range(8)]
    for i in range(1, n):
        x, y, z = nodes[i][0], nodes[i][1], nodes[i][2]
        rx, ry, sx, sy = nodes[i][3]
        for oc in cands:
            oc.clear()
        for nsx in (sx - 1, sx, sx + 1):
            for nsy in (sy - 1, sy, sy + 1):
                nrx, nry = rx, ry
                tsx, tsy = nsx, nsy
                if tsx < 0:
                    tsx += SECS
                    nrx -= 1
                elif tsx >= SECS:
                    tsx -= SECS
                    nrx += 1
                if tsy < 0:
                    tsy += SECS
                    nry -= 1
                elif tsy >= SECS:
                    tsy -= SECS
                    nry += 1
                for j in buckets.get((nrx, nry, tsx, tsy), ()):
                    if j == i:
                        continue
                    ox, oy, oz = nodes[j][0], nodes[j][1], nodes[j][2]
                    dx, dy = ox - x, oy - y
                    oc = octant(dx, dy)
                    if oc is None:
                        continue
                    d2 = dx * dx + dy * dy
                    if d2 > max2:
                        continue
                    cands[oc].append((d2, abs(oz - z), j))
        links = [0] * 8
        for oc, bucket in enumerate(cands):
            if not bucket:
                continue
            bucket.sort()
            for _d2, _adz, j in bucket:
                ox, oy, oz = nodes[j][0], nodes[j][1], nodes[j][2]
                if geo is None or move_straight(geo, x, y, z, ox, oy, oz):
                    links[oc] = j
                    break
        nodes[i] = (x, y, z, (rx, ry, sx, sy), links)
        if on_progress and i % 100000 == 0:
            on_progress(i, n - 1)


def _link_jobs(n_nodes, jobs, min_free_ram, max_cpu):
    """Worker count: same 80% CPU / 2 GB floor as generate."""
    from .generate import _avail_ram_gb, cpu_worker_cap
    if jobs is not None and jobs > 0:
        max_n = int(jobs)
    else:
        max_n = cpu_worker_cap(max_cpu)
    if n_nodes < PARALLEL_MIN_NODES:
        return 1
    avail = _avail_ram_gb()
    while max_n > 1 and avail is not None:
        if avail - max_n * LINK_WORKER_RAM_GB >= min_free_ram:
            break
        max_n -= 1
    return max(1, max_n)


def _write_secindex(pack_dir, nodes):
    """CSR starts[slot]..starts[slot+1] → node indices (append order = slot order)."""
    n = len(nodes)
    starts = array('i', [0]) * (NSEC + 1)
    i = 1
    for slot in range(NSEC):
        starts[slot] = i
        while i < n:
            sec = nodes[i][3]
            if sec is None or _sec_slot(*sec) != slot:
                break
            i += 1
    starts[NSEC] = n
    with open(os.path.join(pack_dir, 'secindex.bin'), 'wb') as f:
        f.write(starts.tobytes())


def _write_link_tables(pack_dir, nodes):
    """nodes.bin (7×i32) + zeroed links.bin (8×i32) + section CSR for mmap workers."""
    n = len(nodes)
    np = os.path.join(pack_dir, 'nodes.bin')
    lp = os.path.join(pack_dir, 'links.bin')
    with open(np, 'wb') as f:
        for i, rec in enumerate(nodes):
            if i == 0:
                f.write(struct.pack('<7i', 0, 0, 0, 0, 0, 0, 0))
            else:
                x, y, z, sec, _ln = rec
                rx, ry, sx, sy = sec
                f.write(struct.pack('<7i', x, y, z, rx, ry, sx, sy))
    with open(lp, 'wb') as f:
        f.write(b'\x00' * (n * LINK_I32 * 4))
    _write_secindex(pack_dir, nodes)
    return np, lp


def _read_links_into_nodes(pack_dir, nodes):
    lp = os.path.join(pack_dir, 'links.bin')
    with open(lp, 'rb') as f:
        raw = f.read()
    n = len(nodes)
    for i in range(1, n):
        ln = list(struct.unpack_from('<8i', raw, i * LINK_I32 * 4))
        x, y, z, sec, _old = nodes[i]
        nodes[i] = (x, y, z, sec, ln)


_LINK_ST = {}


def _link_worker_init(pack_dir):
    """Spawn initializer: mmap packed geo, node tables, and section CSR."""
    np = os.path.join(pack_dir, 'nodes.bin')
    lp = os.path.join(pack_dir, 'links.bin')
    sp = os.path.join(pack_dir, 'secindex.bin')
    nf = open(np, 'rb')
    lf = open(lp, 'r+b')
    sf = open(sp, 'rb')
    nmm = mmap.mmap(nf.fileno(), 0, access=mmap.ACCESS_READ)
    lmm = mmap.mmap(lf.fileno(), 0, access=mmap.ACCESS_WRITE)
    smm = mmap.mmap(sf.fileno(), 0, access=mmap.ACCESS_READ)
    n = len(nmm) // (NODE_I32 * 4)
    _LINK_ST['n'] = n
    _LINK_ST['nv'] = memoryview(nmm).cast('i')
    _LINK_ST['lv'] = memoryview(lmm).cast('i')
    _LINK_ST['sv'] = memoryview(smm).cast('i')
    _LINK_ST['geo'] = _MmapWorld(pack_dir)
    _LINK_ST['_fps'] = (nf, lf, sf, nmm, lmm, smm)


def _link_worker_range(span):
    i0, i1 = span
    n = _LINK_ST['n']
    nv = _LINK_ST['nv']
    lv = _LINK_ST['lv']
    sv = _LINK_ST['sv']
    geo = _LINK_ST['geo']
    max2 = MAX_LINK * MAX_LINK
    cands = [[] for _ in range(8)]
    for i in range(i0, min(i1, n)):
        base = i * NODE_I32
        x, y, z = nv[base], nv[base + 1], nv[base + 2]
        rx, ry, sx, sy = nv[base + 3], nv[base + 4], nv[base + 5], nv[base + 6]
        for oc in cands:
            oc.clear()
        for nsx in (sx - 1, sx, sx + 1):
            for nsy in (sy - 1, sy, sy + 1):
                nrx, nry = rx, ry
                tsx, tsy = nsx, nsy
                if tsx < 0:
                    tsx += SECS
                    nrx -= 1
                elif tsx >= SECS:
                    tsx -= SECS
                    nrx += 1
                if tsy < 0:
                    tsy += SECS
                    nry -= 1
                elif tsy >= SECS:
                    tsy -= SECS
                    nry += 1
                slot = _sec_slot(nrx, nry, tsx, tsy)
                if slot is None:
                    continue
                for j in range(sv[slot], sv[slot + 1]):
                    if j == i:
                        continue
                    jb = j * NODE_I32
                    ox, oy, oz = nv[jb], nv[jb + 1], nv[jb + 2]
                    dx, dy = ox - x, oy - y
                    oc = octant(dx, dy)
                    if oc is None:
                        continue
                    d2 = dx * dx + dy * dy
                    if d2 > max2:
                        continue
                    cands[oc].append((d2, abs(oz - z), j))
        lb = i * LINK_I32
        for oc in range(8):
            lv[lb + oc] = 0
        for oc, bucket in enumerate(cands):
            if not bucket:
                continue
            bucket.sort()
            for _d2, _adz, j in bucket:
                jb = j * NODE_I32
                if move_straight(geo, x, y, z, nv[jb], nv[jb + 1], nv[jb + 2]):
                    lv[lb + oc] = j
                    break
    return min(i1, n) - i0


def _link_parallel(nodes, pack_dir, jobs, min_free_ram, max_cpu):
    from .generate import apply_cpu_cap
    import multiprocessing as mp

    n = len(nodes)
    workers = _link_jobs(n - 1, jobs, min_free_ram, max_cpu)
    if workers == 1:
        geo = _MmapWorld(pack_dir)
        try:
            buckets = defaultdict(list)
            for i in range(1, n):
                rx, ry, sx, sy = nodes[i][3]
                buckets[(rx, ry, sx, sy)].append(i)

            def tick(i, total):
                progress(i, total, prefix='  link', suffix=f'{i:,}/{total:,}')

            _link(nodes, buckets, geo=geo, on_progress=tick)
        finally:
            geo.close()
        return workers

    if max_cpu < 100:
        apply_cpu_cap(max_cpu)
    _write_link_tables(pack_dir, nodes)
    import gc
    gc.collect()
    chunk = max(25000, (n - 1) // (workers * 4) or 1)
    spans = []
    i = 1
    while i < n:
        spans.append((i, min(i + chunk, n)))
        i += chunk
    ctx = mp.get_context('spawn')
    done = 0
    total = n - 1
    with ctx.Pool(workers, initializer=_link_worker_init, initargs=(pack_dir,)) as pool:
        for got in pool.imap_unordered(_link_worker_range, spans):
            done += got
            progress(done, total, prefix='  link',
                     suffix=f'{done:,}/{total:,}  j={workers}')
    _read_links_into_nodes(pack_dir, nodes)
    return workers


def build_nodes(geodir, regions=None, on_region=None, jobs=None,
                min_free_ram=None, max_cpu=None):
    """Dummy + every node as (x,y,z, (rx,ry,sx,sy), links)."""
    from .generate import MAX_CPU_PCT, MIN_FREE_RAM_GB
    if min_free_ram is None:
        min_free_ram = MIN_FREE_RAM_GB
    if max_cpu is None:
        max_cpu = MAX_CPU_PCT
    files = _listed_pts(geodir, regions)
    pack_dir = tempfile.mkdtemp(prefix='l2pn_geo_')
    try:
        by_zone = {}
        for i, (rx, ry, path) in enumerate(files, 1):
            if on_region:
                on_region(i, len(files), rx, ry)
            raw = _seeds_for_region(path, rx, ry, pack_dir=pack_dir)
            by_zone[(rx, ry)] = {k: _merge_section(v) for k, v in raw.items() if v}

        nodes = [(0, 0, 0, None, [0] * 8)]
        for rx in range(RX0, RX1):
            for ry in range(RY0, RY1):
                secs = by_zone.get((rx, ry), {})
                for sx in range(SECS):
                    for sy in range(SECS):
                        for x, y, z in secs.get((sx, sy), ()):
                            nodes.append((x, y, z, (rx, ry, sx, sy), [0] * 8))
        workers = _link_parallel(nodes, pack_dir, jobs, min_free_ram, max_cpu)
        return nodes, by_zone, files, workers
    finally:
        shutil.rmtree(pack_dir, ignore_errors=True)


def format_idx(nodes, by_zone):
    lines = [f'Total = {len(nodes) - 1}', '']
    for rx in range(RX0, RX1):
        for ry in range(RY0, RY1):
            secs = by_zone.get((rx, ry))
            has = 1 if secs is not None else 0
            lines.append(f'--- Zone({rx},{ry})[{has}] ---')
            lines.append('')
            if not secs:
                continue
            west, north = region_origin(rx, ry)
            for sx in range(SECS):
                for sy in range(SECS):
                    n = len(secs.get((sx, sy), ()))
                    if not n:
                        continue
                    ox = west + sx * SECTION
                    oy = north + sy * SECTION
                    lines.append(f'{ox} {oy} {n}')
                    lines.append('')
    return '\n'.join(lines) + '\n'


def format_txt(nodes):
    lines = [f'Total = {len(nodes) - 1}', '']
    for i in range(1, len(nodes)):
        x, y, z, _sec, links = nodes[i]
        used = [lk for lk in links if lk]
        bits = ' '.join(str(lk) for lk in used)
        lines.append(f'{i} : ({x} {y} {z}) ({len(used)}) - {bits}'.rstrip())
    return '\n'.join(lines) + '\n'


def write_bin(path, nodes):
    with open(path, 'wb') as f:
        for x, y, z, _sec, links in nodes:
            f.write(encode_record(x, y, z, links))


def cmd_pathnode(geodir, outdir=None, write_txt=False, regions=None,
                 jobs=None, min_free_ram=None, max_cpu=None):
    """Compile pathnode.bin/.idx from a PTS folder. 64-bit, no PathMaker."""
    from .generate import MAX_CPU_PCT, MIN_FREE_RAM_GB
    if min_free_ram is None:
        min_free_ram = MIN_FREE_RAM_GB
    if max_cpu is None:
        max_cpu = MAX_CPU_PCT
    geodir = os.path.abspath(geodir)
    if not os.path.isdir(geodir):
        print(red(f'  ✗ geodata folder not found: {geodir}'))
        return 1
    outdir = os.path.abspath(outdir or geodir)
    os.makedirs(outdir, exist_ok=True)

    files = _listed_pts(geodir, regions)
    if not files:
        print(red(f'  ✗ no *_conv.dat in {geodir}'))
        return 1

    print(f'  {bold("Pathnode")} {geodir}')
    how = 'auto' if jobs is None else str(jobs)
    print(dim(f'  regions {len(files)}  grid {RX0}-{RX1 - 1} x {RY0}-{RY1 - 1}  '
              f'merge {int(MERGE_DIST)}  cap {MAX_PER_SECTION}  '
              f'link LOS {MAX_LINK}u  workers {how}  '
              f'CPU≤{max_cpu:g}%  keep {min_free_ram:g} GB RAM'))

    def tick(i, n, rx, ry):
        progress(i, n, prefix='  compile', suffix=f'{rx}_{ry}')

    nodes, by_zone, _files, workers = build_nodes(
        geodir, regions, on_region=tick, jobs=jobs,
        min_free_ram=min_free_ram, max_cpu=max_cpu)
    n = len(nodes) - 1
    print(green(f'  {n} pathnodes  (link workers {workers})'))

    bin_p = os.path.join(outdir, 'pathnode.bin')
    idx_p = os.path.join(outdir, 'pathnode.idx')
    write_bin(bin_p, nodes)
    with open(idx_p, 'w', encoding='utf-8', newline='\n') as f:
        f.write(format_idx(nodes, by_zone))
    bin_sz = os.path.getsize(bin_p)
    print(dim(f'  wrote {os.path.basename(bin_p)}  {bin_sz:,} bytes'))
    print(dim(f'  wrote {os.path.basename(idx_p)}  {os.path.getsize(idx_p):,} bytes'))
    if bin_sz > LOADER_MAX_BYTES:
        print(red(f'  ✗ {os.path.basename(bin_p)} is {bin_sz:,} bytes — '
                  f'Loader rejects files larger than {LOADER_MAX_BYTES:,}'))
        return 1
    if write_txt:
        txt_p = os.path.join(outdir, 'pathnode.txt')
        print(yellow('  writing pathnode.txt (debug, large) …'))
        with open(txt_p, 'w', encoding='utf-8', newline='\n') as f:
            f.write(format_txt(nodes))
        print(dim(f'  wrote {os.path.basename(txt_p)}  {os.path.getsize(txt_p):,} bytes'))
    return 0
