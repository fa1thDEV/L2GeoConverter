#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate geodata from L2 client files (stage 1: terrain).

Sources: Maps/XX_YY.unr (TerrainInfo: position, scale, holes) and
Textures/T_XX_YY.utx (G16 heightmap 256×256, 128 units per texel).

Terrain vertex height (UE2): z = Location.z + (h16 − 32768) · Scale.z / 256.
Geodata cell is 16 units → 8×8 cells per texel; height is bilinear
interpolation of texel corners.
"""

import math
import os
import re
import struct
from collections import defaultdict

from .formats import (
    BLOCKS, PROTO_GD, GeoError, normalize_protocol, enc_cell, quant_h,
    complex_is_flat,
)
from .doors import find_doordata, load_region_doors, open_door_nswe
from .unreal import Package, Reader, read_properties

CELLS = 2048                       # cells per region along an axis
# Height convention calibration: the pure UE2 formula puts the surface ~43 units
# lower than typical generators (and than the server ecosystem expects).
# Empirical: client ocean (h16=0x4040, Scale.Z=76, Loc.Z=160.65) → UE2 −4684.35,
# typical generator −4641. Confirmed by retail spawns (7.6k points, 15 regions).
Z_CALIBRATION = 43.35
# Asymmetric step thresholds (calibrated by cell-by-cell comparison with a reference
# pack, 568k cells: 90.4% exact NSWE match):
# climb > UP_STEP is blocked, drop > DOWN_STEP is blocked (you can fall farther
# than you can jump up — as in the client).
UP_STEP = 16
DOWN_STEP = 96


def _step_ok(dz_up, up=UP_STEP, down=DOWN_STEP):
    """Whether a step is allowed for height delta dz_up = h_dest − h_src."""
    return -down <= dz_up <= up

HM = 256                           # heightmap texels along an axis
TEX_UNITS = 128.0                  # units per texel
REGION_UNITS = 32768


def _find_file(directory, names):
    """First existing file from names (case-insensitive)."""
    listing = {f.lower(): f for f in os.listdir(directory)}
    for n in names:
        hit = listing.get(n.lower())
        if hit:
            return os.path.join(directory, hit)
    return None


def map_path(maps_dir, map_name):
    """Path to a map by its Maps name as-is: XX_YY(.unr) or XX_YY_Classic."""
    p = _find_file(maps_dir, [f'{map_name}.unr'])
    if not p:
        raise GeoError(f'no map file {map_name}.unr')
    return p


def _region_id(map_name):
    """XX_YY (world coordinates) from map name: '20_25_Classic' → '20_25'."""
    m = re.match(r'(\d+_\d+)', map_name)
    return m.group(1) if m else map_name


def _map_parts(map_name):
    """('25_21_Classic') → (25, 21, '_Classic')."""
    m = re.match(r'^(\d+)_(\d+)(.*)$', map_name)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), m.group(3)


def neighbor_map_names(map_name):
    """8 adjacent Maps names, keeping the Classic/base suffix."""
    parts = _map_parts(map_name)
    if not parts:
        return []
    rx, ry, suffix = parts
    return [f'{rx + dx}_{ry + dy}{suffix}'
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if not (dx == 0 and dy == 0)]


def resolve_map_name(maps_dir, map_name):
    """Existing Maps name: exact file, or unsuffixed fallback for Classic."""
    if _find_file(maps_dir, [f'{map_name}.unr']):
        return map_name
    m = re.match(r'^(\d+_\d+)_Classic$', map_name, re.I)
    if m and _find_file(maps_dir, [f'{m.group(1)}.unr']):
        return m.group(1)
    return None


def _tri_xy_overlaps(tri, clip):
    xs = (tri[0][0], tri[1][0], tri[2][0])
    ys = (tri[0][1], tri[1][1], tri[2][1])
    return min(xs) < clip[2] and max(xs) > clip[0] and min(ys) < clip[3] and max(ys) > clip[1]


def load_neighbor_terrains(maps_dir, tex_dir, map_name):
    """(dx, dy) → (heights, holes, loc) for Maps that exist around map_name."""
    out = {}
    parts = _map_parts(map_name)
    if not parts:
        return out
    rx, ry, suffix = parts
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if dx == 0 and dy == 0:
                continue
            resolved = resolve_map_name(maps_dir, f'{rx + dx}_{ry + dy}{suffix}')
            if not resolved:
                continue
            try:
                out[(dx, dy)] = load_terrain(maps_dir, tex_dir, resolved)
            except GeoError:
                continue
    return out


def gather_collision_triangles(maps_dir, usx_dir, map_name, west, north, lib=None,
                              progress_cb=None):
    """Own map collision + neighbor meshes/BSP that overhang.

    Returns (mesh_tris, solid_tris, blocking_tris, skipped).
    blocking_tris is empty: official PathMaker geo does not bake
    BlockingVolume (see BLOCKING_VOLUME_CLASSES)."""
    from .meshes import MeshLibrary, level_extra_triangles, region_mesh_triangles
    clip = (west, north, west + REGION_UNITS, north + REGION_UNITS)
    lib = lib or MeshLibrary(usx_dir)
    unr = map_path(maps_dir, map_name)
    pkg = Package(unr)
    tris, skipped = region_mesh_triangles(unr, usx_dir, lib=lib, pkg=pkg,
                                          progress_cb=progress_cb)
    solid, blocking = level_extra_triangles(pkg)
    seen = {os.path.normcase(os.path.abspath(unr))}
    for nname in neighbor_map_names(map_name):
        resolved = resolve_map_name(maps_dir, nname)
        if not resolved:
            continue
        nunr = map_path(maps_dir, resolved)
        key = os.path.normcase(os.path.abspath(nunr))
        if key in seen:
            continue
        seen.add(key)
        t, s = region_mesh_triangles(nunr, usx_dir, lib=lib, clip_xy=clip)
        tris.extend(t)
        skipped += s
        npkg = Package(nunr)
        s2, b2 = level_extra_triangles(npkg)
        solid.extend(t for t in s2 if _tri_xy_overlaps(t, clip))
        blocking.extend(t for t in b2 if _tri_xy_overlaps(t, clip))
    return tris, solid, blocking, skipped


def load_terrain(maps_dir, tex_dir, map_name):
    """TerrainInfo + G16 → (heights[HM][HM] in world Z, holes set[(qx,qy)], loc)."""
    unr = map_path(maps_dir, map_name)
    region = _region_id(map_name)
    pkg = Package(unr)
    tis = pkg.find_exports('TerrainInfo')
    if not tis:
        raise GeoError(f'{region}: no TerrainInfo in map (region without terrain?)')
    # some maps have several TerrainInfo — pick the one whose heightmap
    # belongs to this region
    props = None
    for cand in tis:
        pr = read_properties(pkg, cand)
        tm = pr.get('TerrainMap')
        if isinstance(tm, int) and pkg.obj_name(tm) == region:
            props = pr
            break
    if props is None:
        props = read_properties(pkg, tis[0])
    loc = props.get('Location', (0.0, 0.0, 0.0))
    scale = props.get('TerrainScale', (128.0, 128.0, 64.0))
    if abs(scale[0] - TEX_UNITS) > 0.01 or abs(scale[1] - TEX_UNITS) > 0.01:
        raise GeoError(f'{region}: TerrainScale {scale[:2]} ≠ 128 — not supported')
    tm_ref = props.get('TerrainMap')
    tm_name = pkg.obj_name(tm_ref) if isinstance(tm_ref, int) else region

    # utx package that actually holds the heightmap: the map names it in the
    # TerrainMap import (classic zones often reuse the main/other region's
    # heightmap). It goes first, then the usual candidates by region name.
    is_classic = '_classic' in os.path.basename(unr).lower()
    imp_pkg = pkg.import_package(tm_ref)
    utx_names = []
    if imp_pkg:
        utx_names.append(imp_pkg + '.utx')
    utx_names += ([f'T_{region}_Classic.utx', f'T_{region}.utx'] if is_classic
                  else [f'T_{region}.utx'])
    # find the first utx that has the required G16 heightmap texture
    tpkg = tex = None
    for name in utx_names:
        cand = _find_file(tex_dir, [name])
        if not cand:
            continue
        cp = Package(cand)
        hit = [e for e in cp.find_exports('Texture')
               if e.name == tm_name
               and read_properties(cp, e).get('Format') == 10]
        if hit:
            tpkg, tex = cp, hit
            break
    if not tex:
        raise GeoError(f'no heightmap {tm_name} '
                       f'(searched in {", ".join(utx_names)})')
    e = tex[0]
    tprops = read_properties(tpkg, e)
    usize, vsize = tprops.get('USize', HM), tprops.get('VSize', HM)
    if (usize, vsize) != (HM, HM):
        raise GeoError(f'{region}: heightmap {usize}x{vsize}, expected {HM}x{HM}')
    obj_end = e.offset + e.size
    size = usize * vsize * 2
    data_start = obj_end - 10 - size
    # compact-index mip-size signature immediately before the data («40 80 10»)
    r = Reader(tpkg.data, data_start - 3)
    if r.ci() != size:
        raise GeoError(f'{region}: heightmap mip signature not found')
    hm16 = struct.unpack_from(f'<{usize * vsize}H', tpkg.data, data_start)

    lz, sz = loc[2] + Z_CALIBRATION, scale[2]
    heights = [[lz + (hm16[ty * usize + tx] - 32768) * sz / 256.0
                for tx in range(usize)] for ty in range(vsize)]

    holes = set()
    qvb = props.get('QuadVisibilityBitmap')
    words = None
    if isinstance(qvb, (bytes, bytearray)) and len(qvb) > 4:
        # raw ArrayProperty: CI word count + n×u32
        rq = Reader(bytes(qvb))
        n_words = rq.ci()
        if 0 < n_words <= (len(qvb) - rq.p) // 4:
            words = struct.unpack_from(f'<{n_words}I', qvb, rq.p)
    elif isinstance(qvb, dict):
        n_words = max(qvb) + 1 if qvb else 0
        words = [int.from_bytes(w[:4], 'little') if isinstance(w, bytes) else w
                 for w in (qvb.get(i, 0xFFFFFFFF) for i in range(n_words))]
    if words:
        # bit=0 → quad invisible → hole in terrain (dungeon entrance)
        for idx in range(min(usize * vsize, len(words) * 32)):
            if not (words[idx // 32] >> (idx % 32)) & 1:
                holes.add((idx % usize, idx // usize))
    return heights, holes, loc


def terrain_cells(region, heights, holes, loc, neighbors=None):
    """2048×2048 cell heights (int) + hole mask. Indexed [cy][cx].

    neighbors: optional {(dx,dy): (heights, holes, loc)} for bilinear samples
    past this heightmap's last texel — without it, edge cells clamp and the
    square joint becomes a 16-unit step (invisible wall when ΔZ > UP_STEP)."""
    rx, ry = map(int, region.split('_'))
    west = (rx - 20) * REGION_UNITS
    north = (ry - 18) * REGION_UNITS
    ox = loc[0] - HM / 2 * TEX_UNITS              # world X of vertex tx=0
    oy = loc[1] - HM / 2 * TEX_UNITS
    neigh = neighbors or {}

    def texel(tx, ty):
        if 0 <= tx < HM and 0 <= ty < HM:
            return heights[ty][tx], (tx, ty) in holes
        wx = ox + tx * TEX_UNITS
        wy = oy + ty * TEX_UNITS
        for heights_n, holes_n, loc_n in neigh.values():
            nox = loc_n[0] - HM / 2 * TEX_UNITS
            noy = loc_n[1] - HM / 2 * TEX_UNITS
            ntx = int(round((wx - nox) / TEX_UNITS))
            nty = int(round((wy - noy) / TEX_UNITS))
            if 0 <= ntx < HM and 0 <= nty < HM:
                return heights_n[nty][ntx], (ntx, nty) in holes_n
        ctx, cty = min(max(tx, 0), HM - 1), min(max(ty, 0), HM - 1)
        return heights[cty][ctx], (ctx, cty) in holes

    hcell = [[0] * CELLS for _ in range(CELLS)]
    hole_cell = [[False] * CELLS for _ in range(CELLS)]
    for cy in range(CELLS):
        wy = north + cy * 16 + 8                  # cell center
        fy = (wy - oy) / TEX_UNITS
        ty = int(fy)
        ry_ = fy - ty
        hrow, mrow = hcell[cy], hole_cell[cy]
        interior_y = 0 <= ty < HM - 1
        for cx in range(CELLS):
            wx = west + cx * 16 + 8
            fx = (wx - ox) / TEX_UNITS
            tx = int(fx)
            rx_ = fx - tx
            if interior_y and 0 <= tx < HM - 1:
                z00 = heights[ty][tx]
                z10 = heights[ty][tx + 1]
                z01 = heights[ty + 1][tx]
                z11 = heights[ty + 1][tx + 1]
                hole = (tx, ty) in holes
            else:
                z00, h00 = texel(tx, ty)
                z10, _h10 = texel(tx + 1, ty)
                z01, _h01 = texel(tx, ty + 1)
                z11, _h11 = texel(tx + 1, ty + 1)
                hole = h00
            h = (z00 * (1 - rx_) * (1 - ry_) + z10 * rx_ * (1 - ry_) +
                 z01 * (1 - rx_) * ry_ + z11 * rx_ * ry_)
            hrow[cx] = int(round(h))
            if hole:
                mrow[cx] = True
    _relax_bilinear_lumps(hcell)
    return hcell, hole_cell


def _relax_bilinear_lumps(hcell, up=UP_STEP):
    """Pull 24u (up+8) neighbor pairs 8u closer.

    Bilinear heightmap sampling on a gentle slope often lands one extra
    8-unit quant step between cells (24u). CGeoData CanMove and NSWE both
    treat climb > UP_STEP as a wall, so SuperPoint NPCs freeze on that
    lump ('stuck going upstairs'). Real cliffs (32u+) stay closed."""
    lump = up + 8
    ny = len(hcell)
    nx = len(hcell[0]) if ny else 0
    for _ in range(8):
        changed = False
        for gy in range(ny):
            row = hcell[gy]
            for gx in range(nx):
                h = row[gx]
                if gx + 1 < nx:
                    d = row[gx + 1] - h
                    if d == lump:
                        row[gx + 1] = h + up
                        changed = True
                    elif d == -lump:
                        row[gx] = row[gx + 1] + up
                        changed = True
                if gy + 1 < ny:
                    d = hcell[gy + 1][gx] - h
                    if d == lump:
                        hcell[gy + 1][gx] = h + up
                        changed = True
                    elif d == -lump:
                        row[gx] = hcell[gy + 1][gx] + up
                        changed = True
        if not changed:
            break
    return hcell


def build_l2j(hcell, hole_cell, max_step=UP_STEP):
    """Cells → l2j bytes. NSWE: a direction is blocked if the delta to the neighbor
    exceeds max_step (slope steepness threshold)."""
    out = bytearray()
    for bx in range(256):
        for by in range(256):
            cells = []
            for cx in range(8):
                gx = bx * 8 + cx
                for cy in range(8):
                    gy = by * 8 + cy
                    h = hcell[gy][gx]
                    nswe = 15
                    if hole_cell[gy][gx]:
                        nswe = 0
                    else:
                        # N: -y, S: +y, W: -x, E: +x (asymmetric climb/drop)
                        if gy > 0 and not _step_ok(hcell[gy - 1][gx] - h, max_step):
                            nswe &= ~8
                        if gy < CELLS - 1 and not _step_ok(hcell[gy + 1][gx] - h, max_step):
                            nswe &= ~4
                        if gx > 0 and not _step_ok(hcell[gy][gx - 1] - h, max_step):
                            nswe &= ~2
                        if gx < CELLS - 1 and not _step_ok(hcell[gy][gx + 1] - h, max_step):
                            nswe &= ~1
                    cells.append([(h, nswe)])
            out += pack_l2j_block(cells)
    return bytes(out)


def generate_region(client_dir, map_name, max_step=UP_STEP):
    """Client → l2j bytes for a map by its Maps name (stage 1: terrain only)."""
    maps_dir = os.path.join(client_dir, 'Maps')
    tex_dir = os.path.join(client_dir, 'Textures')
    if not os.path.isdir(maps_dir):
        maps_dir = os.path.join(client_dir, 'MAPS')
    heights, holes, loc = load_terrain(maps_dir, tex_dir, map_name)
    neigh = load_neighbor_terrains(maps_dir, tex_dir, map_name)
    hcell, hole_cell = terrain_cells(_region_id(map_name), heights, holes, loc, neigh)
    return build_l2j(hcell, hole_cell, max_step)


def _enc_layer(z, n):
    return enc_cell(max(-16384, min(16376, int(z))), n)


def pack_l2j_block(cells):
    """64 cells (each a list of (z, nswe)) → one L2J block.

    Type-0 only when every cell is one layer, NSWE=15, and all quantized
    heights are equal (L2J has a single i16). Span 8..32 stays complex so
    l2j2pts can write official PTS (high, low).
    """
    if any(len(c) > 1 for c in cells):
        out = bytearray([2])
        for lay in cells:
            out.append(len(lay))
            for z, n in lay:
                out += struct.pack('<H', _enc_layer(z, n))
        return bytes(out)
    qs = [quant_h(c[0][0]) for c in cells]
    ns = [c[0][1] for c in cells]
    if complex_is_flat(qs, ns) and max(qs) == min(qs):
        return b'\x00' + struct.pack('<h', qs[0])
    out = bytearray([1])
    for c in cells:
        out += struct.pack('<H', _enc_layer(*c[0]))
    return bytes(out)


# ─────────────────────────── stage 2: static meshes ───────────────────────────

# ─────────────────────── raycast kernel (voxel XYZ) ───────────────────────
# Instead of rasterizing triangles — rays in cells: a downward Z-ray yields floors/ceilings
# (a stack of surfaces), an X/Y-ray at body height yields walls. Floors/ceilings are by
# face-normal angle; walls are by whether a
# horizontal ray intersects (a vault overhead does not block — the ray is at chest height).
WALK_NZ = 0.766        # |nz|/|n| ≥ cos(40°) → floor (slope ≤40°). Normal sign does NOT
                       # matter: UE2 collision is two-sided, winding in L2 meshes is
                       # random (~66% of shallow faces "point down"; on toh_Stair02
                       # the whole stair is like that) — the angle is unsigned
LAYER_MERGE = 24       # floors closer than 24u — one layer (height rounding artifact)
AGENT_HEIGHT = 128     # clearance: above a floor need ≥ this empty space to the nearest
                       # surface above, or you cannot stand there (culls mesh "bottoms")
# Wall window "at chest height" (a hit 10..32 above the floor =
# wall; below — you step over, above — you walk under). Any hit blocks the
# direction (OR), unlike the old AND(low, high) which produced both false
# walls (curb+cornice from different faces) and holes (parapet 30..45 with no low/high).
WALL_RAY_OFFS = (12.0, 20.0, 28.0)   # ray heights above the floor inside the window (10,32)
WALL_LAT_OFFS = (-7.0, 0.0, 7.0)     # 3 parallel lines across the direction of travel
                                     # — catch columns/walls
                                     # offset from the center
BLOCK_WIN_LO = 10      # BlockingVolume bars a layer only if the z-range of its
BLOCK_WIN_HI = 32      # steep faces intersects the window (floor+10 … floor+32)
STAIR_MAX_RISE = 16    # a lone steep face this tall is a riser/curb (stepped
                       # over). Stacked strips in the same cell that merge
                       # taller than this (tent/building walls tessellated
                       # into 16u bands) stay walls — see _prep_geometry.
ZONE_PLANE = 16384     # BlockingVolume only: a barrier this wide on either axis
                       # is a location border around a zone, not an inner wall.


def _max_merged_span(intervals, gap=2.0):
    """Longest contiguous Z span after merging intervals that touch within gap."""
    if not intervals:
        return 0.0
    iv = sorted(intervals)
    lo, hi = iv[0]
    best = hi - lo
    for a, b in iv[1:]:
        if a <= hi + gap:
            hi = max(hi, b)
        else:
            best = max(best, hi - lo)
            lo, hi = a, b
    return max(best, hi - lo)


def _add_wall(walls, w_grid, wt, gx0, gx1, gy0, gy1):
    wi = len(walls)
    walls.append(wt)
    for gy in range(gy0, gy1 + 1):
        row = gy * CELLS
        for gx in range(gx0, gx1 + 1):
            w_grid.setdefault(row + gx, []).append(wi)


def _prep_geometry(tris, west, north):
    """Classify triangles and precompute ray data. Returns
    (fc, fc_grid, walls, w_grid):
      fc[i]    — floor/ceiling face with precomputed barycentric for the Z-ray;
      fc_grid  — index (cell → fc indices), coverage by XY-bbox;
      walls[i] — steep face with precomputed edges e1,e2 for the segment test;
      w_grid   — index (cell → walls indices).
    Normals, slope, barycentric, and edges are computed here ONCE, not on every
    ray — ray results are identical, only speed changes.

    Short steep faces (Z span ≤ STAIR_MAX_RISE) are risers/curbs and are
    dropped, unless other short strips in the same cell stack into a taller
    wall (L2 tents/buildings are often tessellated into 16-unit bands)."""
    fc = []
    walls = []
    fc_grid = {}
    w_grid = {}
    pending = []
    for (ax, ay, az), (bx, by, bz), (cx, cy, cz) in tris:
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        ln2 = nx * nx + ny * ny + nz * nz
        if ln2 <= 0:
            continue
        gx0 = max(0, int((min(ax, bx, cx) - west) // 16))
        gx1 = min(CELLS - 1, int((max(ax, bx, cx) - west) // 16))
        gy0 = max(0, int((min(ay, by, cy) - north) // 16))
        gy1 = min(CELLS - 1, int((max(ay, by, cy) - north) // 16))
        if gx1 < gx0 or gy1 < gy0:
            continue
        if abs(nz) < WALK_NZ * math.sqrt(ln2):        # steep → wall
            zlo, zhi = min(az, bz, cz), max(az, bz, cz)
            wt = (ax, ay, az, ux, uy, uz, vx, vy, vz)  # e1=(u), e2=(v)
            if zhi - zlo <= STAIR_MAX_RISE:
                pending.append((zlo, zhi, gx0, gx1, gy0, gy1, wt))
                continue
            _add_wall(walls, w_grid, wt, gx0, gx1, gy0, gy1)
            continue
        d00 = vx * vx + vy * vy                        # shallow → floor (two-sided)
        d01 = vx * ux + vy * uy
        d11 = ux * ux + uy * uy
        den = d00 * d11 - d01 * d01
        if abs(den) < 1e-9:
            continue
        fi = len(fc)
        # is_floor is always True: the normal sign cannot tell floor from
        # ceiling (winding is random). Ceiling role in clearance is played by
        # the same floor-candidates above; the underside of a thin slab merges
        # via LAYER_MERGE, a thick one is culled by clearance from its own top.
        # Disconnected standable floors (roofs, dungeon slabs) are kept.
        fc.append((True, ax, ay, az, ux, uy, uz, vx, vy, vz,
                   d00, d01, d11, 1.0 / den))
        for gy in range(gy0, gy1 + 1):
            row = gy * CELLS
            for gx in range(gx0, gx1 + 1):
                fc_grid.setdefault(row + gx, []).append(fi)
    cell_iv = defaultdict(list)
    for zlo, zhi, gx0, gx1, gy0, gy1, _wt in pending:
        for gy in range(gy0, gy1 + 1):
            row = gy * CELLS
            for gx in range(gx0, gx1 + 1):
                cell_iv[row + gx].append((zlo, zhi))
    tall = {c for c, iv in cell_iv.items()
            if _max_merged_span(iv) > STAIR_MAX_RISE}
    for zlo, zhi, gx0, gx1, gy0, gy1, wt in pending:
        keep = False
        for gy in range(gy0, gy1 + 1):
            row = gy * CELLS
            for gx in range(gx0, gx1 + 1):
                if row + gx in tall:
                    keep = True
                    break
            if keep:
                break
        if keep:
            _add_wall(walls, w_grid, wt, gx0, gx1, gy0, gy1)
    return fc, fc_grid, walls, w_grid


def _column(px, py, fc_idx, fc):
    """Downward Z-ray at (px, py): intersections of the vertical with precomputed
    floor/ceiling faces of the cell → (floors, ceils). Barycentric is already in fc[i]."""
    floors = []
    ceils = []
    for fi in fc_idx:
        (is_floor, ax, ay, az, ux, uy, uz, vx, vy, vz,
         d00, d01, d11, inv) = fc[fi]
        pxr = px - ax
        pyr = py - ay
        d02 = vx * pxr + vy * pyr
        d12 = ux * pxr + uy * pyr
        u = (d11 * d02 - d01 * d12) * inv
        v = (d00 * d12 - d01 * d02) * inv
        if u < -0.02 or v < -0.02 or u + v > 1.02:
            continue
        z = az + u * vz + v * uz
        if not (-16384 <= z <= 16376):
            continue
        (floors if is_floor else ceils).append(int(z))
    return floors, ceils


def _wall_between(px, py, npx, npy, z, w_idx, walls):
    """X/Y-ray: passage is blocked if a steep face intersects the horizontal
    segment [center→neighbor] in the body window (window 10..32 above the floor): rays
    at heights WALL_RAY_OFFS, 3 parallel lines with WALL_LAT_OFFS offsets
    across the direction of travel. ANY hit = wall: a curb below the window is stepped over,
    a vault/cornice above — walked under. Stair risers are already filtered in
    _prep_geometry (z-span ≤ STAIR_MAX_RISE). Edges e1,e2 are precomputed;
    Möller–Trumbore for the segment."""
    dx = npx - px
    dy = npy - py
    lx, ly = (1.0, 0.0) if dx == 0 else (0.0, 1.0)   # across the direction of travel
    for wi in w_idx:
        ax, ay, az, e1x, e1y, e1z, e2x, e2y, e2z = walls[wi]
        # h = d × e2, d = (dx, dy, 0)  (horizontal segment → dz = 0)
        hx = dy * e2z
        hy = -dx * e2z
        hz = dx * e2y - dy * e2x
        a = e1x * hx + e1y * hy + e1z * hz
        if -1e-9 < a < 1e-9:
            continue
        f = 1.0 / a
        for lat in WALL_LAT_OFFS:
            sx = px + lx * lat - ax
            sy = py + ly * lat - ay
            for hoff in WALL_RAY_OFFS:
                sz = z + hoff - az
                uu = f * (sx * hx + sy * hy + sz * hz)
                if uu < 0.0 or uu > 1.0:
                    continue
                qx = sy * e1z - sz * e1y
                qy = sz * e1x - sx * e1z
                qz = sx * e1y - sy * e1x
                vv = f * (dx * qx + dy * qy)
                if vv < 0.0 or uu + vv > 1.0:
                    continue
                t = f * (e2x * qx + e2y * qy + e2z * qz)
                if 0.0 <= t <= 1.0:
                    return True
    return False


def _span_layers(floor_zs, ceil_zs, base):
    """Cell spans → walkable layers (top to bottom), with a clearance check.

    Floor candidates are mesh floor-spans plus terrain (base). Clearance is checked
    ONLY for mesh floors: a mesh layer is walkable if the gap above it to the nearest
    surface (a ceiling-span or the next floor above) is ≥ AGENT_HEIGHT —
    otherwise you cannot stand under overhanging geometry (this is how a volumetric
    mesh "bottom" is culled: it is a ceiling-span, never becomes a floor, and the
    mesh shelf under it is suppressed).
    Terrain (base) is not suppressed by CEILINGS (a boulder/canopy underside over ground
    does not burn holes in the field — ground under a canopy/arch is walkable), but is
    suppressed by an accepted FLOOR closer than AGENT_HEIGHT above it: you still cannot
    stand between them, and a ghost ground layer under a floor/stair would catch edge
    walls — a strip of deaf cells at the
    foot (in classic geodata terrain does not exist as a separate layer at all). Nearby
    floors (<LAYER_MERGE) merge — height rounding artifact."""
    terrain = base[0] if base else None
    cand = sorted(set(list(floor_zs) + list(base)), reverse=True)
    ceils = sorted(set(ceil_zs))
    out = []
    for z in cand:
        # merge window: terrain suppresses any accepted floor within clearance,
        # mesh floors merge only when flush (height rounding)
        if out and out[-1] - z < (AGENT_HEIGHT if z == terrain else LAYER_MERGE):
            continue
        if z != terrain:                          # mesh ceilings/bottoms do not suppress terrain
            # nearest surface STRICTLY above z: a ceiling or another floor-candidate
            above = None
            for c in ceils:                        # ceils ascending
                if c > z + LAYER_MERGE:
                    above = c
                    break
            for f in reversed(cand):               # cand descending → reversed ascending
                if f > z + LAYER_MERGE:
                    if above is None or f < above:
                        above = f
                    break
            if above is not None and (above - z) < AGENT_HEIGHT:
                continue                           # cannot stand under an overhanging surface
        out.append(z)
    return out[:120]


def _cell_range(lo, hi, origin):
    """Inclusive cell indices whose [origin+g*16, origin+(g+1)*16) overlaps [lo, hi]."""
    if hi < lo:
        lo, hi = hi, lo
    g0 = int(math.floor((lo - origin) / 16))
    g1 = int(math.floor((hi - origin - 1e-9) / 16))
    return g0, g1


def _boundary_indices(lo, hi, origin):
    """Grid-line indices k with origin+k*16 in [lo, hi]. Snap to nearest if none."""
    if hi < lo:
        lo, hi = hi, lo
    first = int(math.ceil((lo - origin) / 16 - 1e-9))
    last = int(math.floor((hi - origin) / 16 + 1e-9))
    if first <= last:
        return range(first, last + 1)
    mid = 0.5 * (lo + hi)
    return (int(round((mid - origin) / 16)),)


def _tri_axis_span(tri, axis, value):
    """Min/max of the other horizontal coord of triangle ∩ plane coord[axis]=value.

    axis 0 → span in Y; axis 1 → span in X. None if the plane misses.
    """
    u = 1 if axis == 0 else 0
    pts = []
    for i in range(3):
        p, q = tri[i], tri[(i + 1) % 3]
        if abs(p[axis] - value) <= 1e-6:
            pts.append(p[u])
        da = q[axis] - p[axis]
        if abs(da) < 1e-12:
            continue
        t = (value - p[axis]) / da
        if -1e-9 <= t <= 1.0 + 1e-9:
            t = max(0.0, min(1.0, t))
            pts.append(p[u] + (q[u] - p[u]) * t)
    if len(pts) < 2:
        return None
    return min(pts), max(pts)


def _blocking_edges(blocking, west, north):
    """BlockingVolume faces → closed cell edges (barrier walls of the
    level: playable-zone border, blocked roads). Returns a dict
    key → (zlo, zhi): ('x', gx, gy) — edge between (gx-1,gy) and (gx,gy);
    ('y', gx, gy) — between (gx,gy-1) and (gx,gy); (zlo, zhi) — z-range of the volume's
    faces on that edge (bars only layers whose body window
    BLOCK_WIN_LO..HI it intersects — a volume on a bridge does not lock the floor under it).
    Only STEEP faces are taken: horizontal volume lids are not walls; their
    diagonals would draw strips of deaf cells across the floor. Faces huge in
    either axis (>ZONE_PLANE, half a region) are a barrier volume AROUND a
    zone, not an inner wall: rasterizing them would lock the zone from inside.

    Rasterization follows the face normal, not the triangle-edge walk.
    An east-west wall (normal ±Y) closes N/S (`y` keys) along its length.
    Walking the long edges used to stamp `x` keys instead — a 10k-wide
    Talking Island zone face then sealed the Pantheon floor east-west."""
    blocked = {}

    def _add(key, zlo, zhi):
        old = blocked.get(key)
        if old is not None:
            zlo, zhi = min(old[0], zlo), max(old[1], zhi)
        blocked[key] = (zlo, zhi)

    def _mark_x(gx, ylo, yhi, zlo, zhi):
        if not (0 <= gx <= CELLS):
            return
        gy0, gy1 = _cell_range(ylo, yhi, north)
        for gy in range(gy0, gy1 + 1):
            if 0 <= gy < CELLS:
                _add(('x', gx, gy), zlo, zhi)

    def _mark_y(gy, xlo, xhi, zlo, zhi):
        if not (0 <= gy <= CELLS):
            return
        gx0, gx1 = _cell_range(xlo, xhi, west)
        for gx in range(gx0, gx1 + 1):
            if 0 <= gx < CELLS:
                _add(('y', gx, gy), zlo, zhi)

    for tri in blocking:
        xs = (tri[0][0], tri[1][0], tri[2][0])
        ys = (tri[0][1], tri[1][1], tri[2][1])
        if max(xs) - min(xs) > ZONE_PLANE or max(ys) - min(ys) > ZONE_PLANE:
            continue                               # location border, not a wall
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        ln2 = nx * nx + ny * ny + nz * nz
        if ln2 <= 0 or abs(nz) >= WALK_NZ * math.sqrt(ln2):
            continue                               # shallow lid/bottom — not a wall
        zlo, zhi = min(az, bz, cz), max(az, bz, cz)
        xlo, xhi = min(xs), max(xs)
        ylo, yhi = min(ys), max(ys)
        if abs(nx) >= abs(ny):
            for gx in _boundary_indices(xlo, xhi, west):
                span = _tri_axis_span(tri, 0, west + gx * 16)
                if span is None:
                    span = (ylo, yhi)
                _mark_x(gx, span[0], span[1], zlo, zhi)
        else:
            for gy in _boundary_indices(ylo, yhi, north):
                span = _tri_axis_span(tri, 1, north + gy * 16)
                if span is None:
                    span = (xlo, xhi)
                _mark_y(gy, span[0], span[1], zlo, zhi)
    return blocked


def _shift_progress(cb, start, end, total=256):
    """Map a 0..t tick onto start..end of a 0..total bar (phase + pack)."""
    if not cb:
        return None
    span = end - start

    def inner(d, t):
        if t <= 0:
            cb(end, total)
            return
        cb(start + int(d * span / t), total)
    return inner


def _raycast_backend(fc, fc_grid, walls, w_grid, hcell, hole_cell, west, north,
                     max_step, blocked, progress_cb=None):
    """Full ray+NSWE assembly pipeline on GPU/CPU via Taichi, if it is
    installed and working: Z-ray (layers) → X/Y-ray (walls) → NSWE of all
    grid layers. Returns (cell_layers, nswe_flat, l_off) — ready to pack in
    build_l2j_ray, or (None, None, None) → build will compute in pure Python.
    Result matches Python byte-for-byte (f64); any Taichi failure is a silent
    fallback."""
    if not fc_grid:                                    # region with no geometry —
        return None, None, None                        # terrain alone, Taichi not needed
    try:
        from . import raycast_ti as RT
        if not RT.available() or RT.init() is None:    # init inside try: Taichi/LLVM
            return None, None, None                    # failure → silent fallback
    except Exception:
        return None, None, None
    try:
        if progress_cb:
            progress_cb(40, 256)                       # Taichi init / upload
        cells = list(fc_grid)
        oz, ofl, ocnt = RT.zray_columns(fc, fc_grid, west, north, cells, WALK_NZ)
        if progress_cb:
            progress_cb(110, 256)                      # Z-ray done
        cell_layers = {}
        for i, cell in enumerate(cells):
            gy, gx = divmod(cell, CELLS)
            fl = [int(oz[i, k]) for k in range(ocnt[i]) if ofl[i, k] == 1]
            ce = [int(oz[i, k]) for k in range(ocnt[i]) if ofl[i, k] == 0]
            ls = _span_layers(fl, ce, [hcell[gy][gx]])
            if ls:
                cell_layers[cell] = ls
        if progress_cb:
            progress_cb(140, 256)                      # layers ready
        # NSWE of all grid layers on device (Z-ray layers ready; walls via X/Y-ray
        # and height/blocked/anti-deaf — all in one kernel)
        nswe_flat, l_off = RT.nswe_grid(cell_layers, hcell, walls, w_grid, blocked,
                                        west, north, max_step, DOWN_STEP,
                                        WALL_RAY_OFFS, WALL_LAT_OFFS,
                                        BLOCK_WIN_LO, BLOCK_WIN_HI)
        if progress_cb:
            progress_cb(196, 256)                      # NSWE kernel done
        return cell_layers, nswe_flat, l_off
    except Exception:
        return None, None, None                        # failure → pure Python


def _pack_layers(hcell, cell_layers, nswe_flat, l_off, progress_cb=None,
                 doors=None):
    """Pack ready layers+NSWE (computed on device) into L2J bytes.
    nswe_flat[l_off[cell]+j] — nswe of the cell's j-th layer; layer order matches ls
    (terrain is layer 0, or cell_layers). Serialization is identical to build_l2j_ray."""
    doors = doors or {}
    out = bytearray()
    for bx in range(256):
        if progress_cb:
            progress_cb(bx, 256)
        for by in range(256):
            cells = []
            for cx in range(8):
                gx = bx * 8 + cx
                for cy in range(8):
                    gy = by * 8 + cy
                    cell = gy * CELLS + gx
                    ls = cell_layers.get(cell)
                    if ls is None:
                        ls = (hcell[gy][gx],)
                    o = int(l_off[cell])
                    lay = [(z, open_door_nswe(int(nswe_flat[o + j]), gx, gy, z, doors))
                           for j, z in enumerate(ls)]
                    cells.append(lay)
            out += pack_l2j_block(cells)
    if progress_cb:
        progress_cb(256, 256)
    return bytes(out)


def build_l2j_ray(hcell, hole_cell, fc, fc_grid, walls, w_grid, west, north,
                  max_step=UP_STEP, blocked=(), progress_cb=None,
                  cell_layers=None, nswe_flat=None, l_off=None, doors=None):
    """Terrain + mesh raycast → l2j with multilayer. Layers are via Z-ray at cell center
    (floors/ceilings/clearance); NSWE is by neighbor height delta AND an X/Y-ray at
    body height (walls). Two modes: (1) ready NSWE from the Taichi backend (nswe_flat/
    l_off) — pack bytes only; (2) pure Python — Z-ray + NSWE +
    pack on the fly, byte-for-byte identical. Raycast only in cells with geometry;
    open field and holes — terrain directly."""
    blocked = blocked or {}
    doors = doors or {}
    # ── mode 1: NSWE computed on device, only packing remains ──
    if nswe_flat is not None:
        return _pack_layers(hcell, cell_layers, nswe_flat, l_off, progress_cb,
                            doors)

    # ── mode 2: everything in pure Python ──
    if cell_layers is None:                             # pure Python Z-ray
        cell_layers = {}
        for cell, fc_idx in fc_grid.items():
            gy, gx = divmod(cell, CELLS)
            px = west + gx * 16 + 8
            py = north + gy * 16 + 8
            fl, ce = _column(px, py, fc_idx, fc)
            ls = _span_layers(fl, ce, [hcell[gy][gx]])
            if ls:
                cell_layers[cell] = ls

    def layers_at(gx, gy):
        ls = cell_layers.get(gy * CELLS + gx)
        return ls if ls is not None else (hcell[gy][gx],)

    out = bytearray()
    for bx in range(256):
        if progress_cb:                              # progress on every block (256 rows) —
            progress_cb(bx, 256)                     # frequent ticks so it does not look "hung"
        for by in range(256):
            cells = []
            for cx in range(8):
                gx = bx * 8 + cx
                for cy in range(8):
                    gy = by * 8 + cy
                    cell = gy * CELLS + gx
                    ls = layers_at(gx, gy) or (hcell[gy][gx],)
                    px = west + gx * 16 + 8
                    py = north + gy * 16 + 8
                    wti = w_grid.get(cell)              # wall faces of the cell
                    lay = []
                    for z in ls:
                        nswe = 15
                        wall_bits = 0                   # closed by wall/decor
                        block_bits = 0                  # closed by BlockingVolume
                        for di, (bit, ngx, ngy, bkey) in enumerate((
                                (8, gx, gy - 1, ('y', gx, gy)),
                                (4, gx, gy + 1, ('y', gx, gy + 1)),
                                (2, gx - 1, gy, ('x', gx, gy)),
                                (1, gx + 1, gy, ('x', gx + 1, gy)))):
                            if not (0 <= ngx < CELLS and 0 <= ngy < CELLS):
                                continue
                            nls = layers_at(ngx, ngy)
                            height_ok = any(_step_ok(nz - z, max_step) for nz in nls)
                            rng = blocked.get(bkey)      # BlockingVolume: bars
                            if rng is not None and (     # only if its z-range
                                    rng[0] < z + BLOCK_WIN_HI    # intersects the
                                    and rng[1] > z + BLOCK_WIN_LO):  # layer's body window
                                nswe &= ~bit
                                if height_ok:
                                    block_bits |= bit
                                continue
                            if not height_ok:
                                nswe &= ~bit             # height delta (slope/cliff)
                                continue
                            # X/Y-ray: wall between floors at body height
                            nwti = w_grid.get(ngy * CELLS + ngx)
                            is_wall = False
                            if wti or nwti:
                                seg_w = (wti or []) + (nwti or [])
                                npx = west + ngx * 16 + 8
                                npy = north + ngy * 16 + 8
                                is_wall = _wall_between(px, py, npx, npy, z, seg_w, walls)
                            if is_wall:
                                nswe &= ~bit
                                wall_bits |= bit
                        # anti-deaf: a thin object (trunk/pillar) must not lock
                        # a walkable cell on all sides — restore a bypass
                        # side. BUT a through BlockingVolume barrier (both sides
                        # of the N-S=12 or W-E=3 axis closed by the volume) stays closed,
                        # otherwise the barrier "leaks" in a 1-cell-wide passage.
                        if nswe == 0 and (wall_bits or block_bits):
                            give = wall_bits | block_bits
                            if (block_bits & 12) == 12:   # through N-S axis
                                give &= ~12
                            if (block_bits & 3) == 3:     # through W-E axis
                                give &= ~3
                            nswe = give
                        nswe = open_door_nswe(nswe, gx, gy, z, doors)
                        lay.append((z, nswe))
                    cells.append(lay)
            out += pack_l2j_block(cells)
    if progress_cb:
        progress_cb(256, 256)
    return bytes(out)


def prepare_generate_geometry(client_dir, map_name, lib=None, progress_cb=None):
    """Terrain + collision faces for one Maps square, including neighbors.

    Same inputs generate_region_full raycasts. Returns a dict used by generate
    and by the viewer mismatch overlay."""
    from .meshes import MeshLibrary
    maps_dir = os.path.join(client_dir, 'Maps')
    if not os.path.isdir(maps_dir):
        maps_dir = os.path.join(client_dir, 'MAPS')
    tex_dir = os.path.join(client_dir, 'Textures')
    usx_dir = os.path.join(client_dir, 'StaticMeshes')
    region = _region_id(map_name)
    if progress_cb:
        progress_cb(2, 256)
    heights, holes, loc = load_terrain(maps_dir, tex_dir, map_name)
    neigh = load_neighbor_terrains(maps_dir, tex_dir, map_name)
    if progress_cb:
        progress_cb(6, 256)
    hcell, hole_cell = terrain_cells(region, heights, holes, loc, neigh)
    rx, ry = map(int, region.split('_'))
    west, north = (rx - 20) * REGION_UNITS, (ry - 18) * REGION_UNITS
    lib = lib or MeshLibrary(usx_dir)
    tris, solid, blocking, skipped = gather_collision_triangles(
        maps_dir, usx_dir, map_name, west, north, lib=lib,
        progress_cb=_shift_progress(progress_cb, 6, 22))
    if progress_cb:
        progress_cb(22, 256)
    zc = Z_CALIBRATION
    allt = [tuple((x, y, z + zc) for x, y, z in t) for t in (tris + solid)]
    fc, fc_grid, walls, w_grid = _prep_geometry(allt, west, north)
    blocked = _blocking_edges(blocking, west, north)
    return {
        'hcell': hcell, 'hole_cell': hole_cell,
        'west': west, 'north': north,
        'fc': fc, 'fc_grid': fc_grid, 'walls': walls, 'w_grid': w_grid,
        'blocked': blocked, 'skipped': skipped, 'ntris': len(allt),
    }


def generate_region_full(client_dir, map_name, max_step=UP_STEP, progress_cb=None,
                         doordata=None):
    """Client → l2j by map name in Maps: terrain + static meshes and BSP model
    (floors/ceilings into spans). BlockingVolume is not ingested — official
    Glory Days PathMaker geo leaves those brushes as NSWE=15.
    Heightfield kernel, NSWE by height. Neighbor maps contribute overhanging
    collision and the extra heightmap texel at the square joint.
    DoorData footprints (if found) force NSWE=15 after wall/step bits."""
    if progress_cb:
        progress_cb(0, 256)                            # named bar appears immediately
    g = prepare_generate_geometry(client_dir, map_name, progress_cb=progress_cb)
    if progress_cb:
        progress_cb(24, 256)                           # UNR / meshes / BSP loaded
    door_path = find_doordata(client_dir, doordata)
    doors = load_region_doors(door_path, g['west'], g['north']) if door_path else {}
    cell_layers, nswe_flat, l_off = _raycast_backend(
        g['fc'], g['fc_grid'], g['walls'], g['w_grid'],
        g['hcell'], g['hole_cell'], g['west'], g['north'], max_step, g['blocked'],
        progress_cb)
    pack_cb = (_shift_progress(progress_cb, 200, 256)
               if nswe_flat is not None else progress_cb)
    data = build_l2j_ray(
        g['hcell'], g['hole_cell'], g['fc'], g['fc_grid'], g['walls'], g['w_grid'],
        g['west'], g['north'], max_step, g['blocked'], pack_cb,
        cell_layers, nswe_flat, l_off, doors)
    return data, g['ntris'], g['skipped']


# ─────────────────────────── generate command ───────────────────────────

_PROGRESS_Q = None    # worker progress-tick queue → main process


def _drain_progress(pq, active):
    """Drain all ticks from the queue into active: map_name → (done,total);
    'done' removes the map from the active set."""
    import queue as _q
    while True:
        try:
            name, d = pq.get_nowait()[:2]
        except (_q.Empty, Exception):
            return
        if d == 'done':
            active.pop(name, None)
        else:
            active[name] = (d, 256)


def _init_worker(q):
    """Pool process initializer: remembers the progress queue and SILENCES
    the worker's stdout/stderr for its entire lifetime.

    Why: Taichi prints a banner on init («[Taichi] version …»,
    «Starting on arch=cuda») straight to the console, bypassing sys.stdout and log_level.
    In the pool this cuts into the main process's \\r-progress bar and looks like
    progress is printed again. The worker does not need a console: progress goes through
    queue q, errors return as a tuple from _worker. Redirection MUST
    be permanent (not temporary): Taichi flushes the banner lazily, and if the
    fd were restored it would still leak through."""
    global _PROGRESS_Q
    _PROGRESS_Q = q
    try:
        dn = os.open(os.devnull, os.O_WRONLY)
        os.dup2(dn, 1)                                # stdout → devnull
        os.dup2(dn, 2)                                # stderr → devnull
        os.close(dn)
    except Exception:
        pass                                          # failed — not critical


def _out_name(map_name, out_fmt):
    """XX_YY.l2j or XX_YY_conv.dat (Classic suffix stays in the stem)."""
    return map_name + ('_conv.dat' if out_fmt == 'pts' else '.l2j')


def _encode_generated(l2j_bytes, map_name, out_fmt, protocol=PROTO_GD):
    """Validate L2J bytes and optionally recode to PTS in memory."""
    from .convert import validate_l2j_bytes, l2j2pts_bytes, validate_pts_bytes
    validate_l2j_bytes(l2j_bytes)
    if out_fmt != 'pts':
        return l2j_bytes
    parts = _map_parts(map_name)
    if not parts:
        raise GeoError(f'cannot derive region xy from {map_name}')
    rx, ry, _ = parts
    pts, _nf, _nc, _nm = l2j2pts_bytes(l2j_bytes, rx, ry, protocol)
    validate_pts_bytes(pts)
    return pts


def _worker(job):
    """One map (for the process pool).

    Atomic write: first to a temp file, validate, then
    os.replace → the canonical file appears only whole and verified.
    Interrupting (Ctrl+C/terminate) during the write leaves at most a .tmp,
    never a truncated or invalid geodata file.
    Raycast progress is sent to _PROGRESS_Q as ticks (map_name, done, total),
    completion — (map_name, 'done')."""
    client_dir, map_name, out_path, max_step, terrain_only, out_fmt, protocol, doordata = job
    tmp = out_path + '.tmp'
    q = _PROGRESS_Q
    cb = (lambda d, t: q.put((map_name, d, t))) if q is not None else None
    if q is not None:
        q.put((map_name, 0, 256))                      # show the map name before load
    try:
        if terrain_only:
            data = generate_region(client_dir, map_name, max_step)
        else:
            data, _n, _s = generate_region_full(client_dir, map_name, max_step, cb,
                                                doordata)
        data = _encode_generated(data, map_name, out_fmt, protocol)
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, out_path)                 # atomic replace
        if q is not None:
            q.put((map_name, 'done'))
        return (map_name, None)
    except BaseException as e:                     # incl. KeyboardInterrupt/SystemExit
        if os.path.exists(tmp):
            os.remove(tmp)
        if q is not None:
            q.put((map_name, 'done'))
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
        return (map_name, f'{type(e).__name__}: {e}')


def _process_main(job, pq, rq, run_id=0):
    """Process entry for auto-scaled workers (not a fixed Pool)."""
    import signal
    try:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
    except Exception:
        pass
    _init_worker(pq)
    try:
        name, err = _worker(job)
        rq.put((run_id, name, err))
    except BaseException as e:
        name = job[1] if len(job) > 1 else '?'
        rq.put((run_id, name, f'{type(e).__name__}: {e}'))


def _cleanup_geo_tmps(out_dir):
    import glob as _g2
    for t in _g2.glob(os.path.join(out_dir, '*.l2j.tmp')) + \
             _g2.glob(os.path.join(out_dir, '*_conv.dat.tmp')):
        try:
            os.remove(t)
        except OSError:
            pass


def _pool_status_lines(completed, total, active, extra='', elapsed=0.0,
                       map_elapsed=None, max_maps=None):
    """Header bar + one in-place bar per live map (same format as sequential)."""
    from .ui import bar_line, dim, fmt_dur, term_height
    eta = ''
    if completed and elapsed > 1 and completed < total:
        eta = '  ~' + fmt_dur(elapsed / completed * (total - completed))
    if extra:
        eta += extra if extra.startswith(' ') else '  ' + extra
    lines = [bar_line('generate', completed, total, eta)]
    items = sorted((n, d, t) for n, (d, t) in active.items() if t)
    if max_maps is None:
        max_maps = max(1, term_height() - 8)
    overflow = len(items) - max_maps
    if overflow > 0:
        items = items[:max_maps]
    map_elapsed = map_elapsed or {}
    for name, d, t in items:
        tail = ''
        ran = map_elapsed.get(name, 0.0)
        if 1 <= d < t and ran > 0.3:
            tail = '  ~' + fmt_dur(ran / d * (t - d))
        lines.append(bar_line(name, d, t, tail))
    if overflow > 0:
        lines.append(dim(f'  … +{overflow} more'))
    elif completed < total and not items:
        lines.append(dim('  starting workers'))
    return lines



def _taichi_available():
    """Whether Taichi is installed — for the status line on the parallel path. Via
    find_spec, WITHOUT importing: import taichi itself prints a version banner, and in the
    main process it is not needed here (init and its banner are the workers' job, silenced there)."""
    try:
        import importlib.util
        return importlib.util.find_spec('taichi') is not None
    except Exception:
        return False


def _prewarm_taichi():
    """Initialize Taichi in the CURRENT process ahead of time (sequential path):
    the startup banner is printed once BEFORE the progress bars, instead of cutting into them,
    and the first map does not pay for init on the fly. Returns the backend name
    ('cuda'/'cpu'/…) or None (no Taichi / failure)."""
    try:
        from . import raycast_ti as RT
        if RT.available():
            return RT.init()
    except Exception:
        pass
    return None


from .resources import (  # noqa: E402
    MIN_FREE_RAM_GB, MAX_CPU_PCT, _avail_ram_gb, _total_ram_gb, apply_cpu_cap,
    cpu_worker_cap, want_worker_delta,
)


def cmd_generate(client_dir, out_dir, maps=None, max_step=UP_STEP,
                 terrain_only=False, jobs=None, out_fmt='l2j', protocol=PROTO_GD,
                 doordata=None, min_free_ram=MIN_FREE_RAM_GB, max_cpu=MAX_CPU_PCT,
                 stop_event=None):
    """Generate from the client: each Maps map as-is → out/<name>.l2j
    (or out/<name>_conv.dat when out_fmt='pts').

    Square name = map file name: XX_YY (from XX_YY.unr) and XX_YY_Classic
    (from XX_YY_Classic.unr) are separate squares. Only the selected ones are generated;
    maps is a list of names (None → all maps matching XX_YY*.unr).
    PTS is encoded in memory from the L2J body — no intermediate .l2j file.
    `protocol` only affects the PTS 18-byte header (gd = official L2OFF
    layer-sum used by Glory Days / Interlude / HF / Epilogue; 286 =
    official protocol 286 cell count).
    """
    import multiprocessing as mp
    import re as _re
    import time as _t
    from .ui import LiveBlock, bold, dim, green, progress, red, yellow
    maps_dir = os.path.join(client_dir, 'Maps')
    if not os.path.isdir(maps_dir):
        maps_dir = os.path.join(client_dir, 'MAPS')
    if not os.path.isdir(maps_dir):
        print(red(f'  ✗ Maps folder not found in {client_dir}'))
        return 1
    listing = os.listdir(maps_dir)
    all_maps = sorted(m.group(1) for f in listing
                      for m in [_re.match(r'^(\d+_\d+.*?)\.unr$', f, _re.IGNORECASE)] if m)
    names = [n for n in all_maps if n in maps] if maps else all_maps
    if out_fmt not in ('l2j', 'pts'):
        print(red(f'  ✗ unknown generate format {out_fmt!r} (l2j or pts)'))
        return 1
    try:
        proto = normalize_protocol(protocol)
    except GeoError as e:
        print(red(f'  ✗ {e}'))
        return 1
    door_path = None if terrain_only else find_doordata(client_dir, doordata)
    tasks = [(client_dir, n, os.path.join(out_dir, _out_name(n, out_fmt)),
              max_step, terrain_only, out_fmt, proto, door_path)
             for n in names]
    if not tasks:
        print(red('  ✗ no matching maps (XX_YY*.unr) in Maps'))
        return 1
    os.makedirs(out_dir, exist_ok=True)
    max_cpu = max(1.0, min(100.0, float(max_cpu)))
    n_cpu = os.cpu_count() or 4
    max_n = cpu_worker_cap(max_cpu, n_cpu=n_cpu)
    cpu_capped = apply_cpu_cap(max_cpu)
    ram = _total_ram_gb()
    avail0 = _avail_ram_gb()
    cpu_txt = (f'CPU ≤{max_cpu:g}%'
               + ('' if cpu_capped or max_cpu >= 100 else ' (worker cap only)'))
    fixed_jobs = jobs if (jobs is not None and int(jobs) >= 1) else None
    if fixed_jobs:
        nproc = fixed_jobs
        how = f'set via -j · {cpu_txt}'
        workers_txt = f'{nproc} processes'
    else:
        nproc = None
        how = (f'auto: keep ≥{min_free_ram:g} GB RAM free, max {max_n} workers'
               + (f' · {ram:.0f} GB installed' if ram else ''))
        if max_cpu < 100:
            how += f' · {cpu_txt} of {n_cpu} CPUs'
        workers_txt = 'dynamic workers'
        if avail0 is not None:
            how += f' · {avail0:.1f} GB free now'
    print(f'  {bold("Generate")}: {len(names)} maps'
          f' → {out_dir} ({out_fmt}'
          + (f', protocol {proto}' if out_fmt == 'pts' else '')
          + f') · {workers_txt} ({how})'
          f'{" · terrain only" if terrain_only else ""}\n')
    print(dim('  (Ctrl+C — interrupt; completed files are kept)\n'))
    if terrain_only:
        pass
    elif door_path:
        print(dim(f'  DoorData: {door_path}\n'))
    else:
        print(dim('  DoorData: not found — gate cells keep wall NSWE\n'))
    total = len(tasks)
    # accelerator status line. On the sequential path (≤3) raycast runs in this
    # same process — prewarm Taichi so its banner lands above, not
    # cutting into the bars. In the pool workers init it themselves silently (their
    # output is silenced in _init_worker), so here we only check availability.
    if total <= 3:
        _arch = _prewarm_taichi()
        _acc = f'Taichi arch={_arch}' if _arch else 'none (pure Python, CPU)'
    else:
        _acc = 'Taichi (GPU/CPU in workers)' if _taichi_available() \
            else 'none (pure Python, CPU)'
    print(dim(f'  Accelerator: {_acc}\n'))
    t0 = _t.time()
    ok, errors, done = 0, [], 0
    aborted = False
    if total <= 3:
        # few squares → sequential, with intra-map ETA progress (by
        # blocks): you see how much is left until the square finishes, not only 0→100%.
        try:
            for i, (cl, name, out_path, ms, terr, fmt, proto, doors) in enumerate(tasks, 1):
                if stop_event and stop_event.is_set():
                    aborted = True
                    print(dim(f'\n  generation stopped at {done}/{total} — {ok} completed files kept.'))
                    break
                def cb(d, t, _n=name):
                    progress(d, t, _n)               # bar_line will align the label
                tmp = out_path + '.tmp'
                try:
                    if terr:
                        data = generate_region(cl, name, ms)
                        cb(256, 256)
                    else:
                        data, _n, _s = generate_region_full(cl, name, ms, cb, doors)
                    data = _encode_generated(data, name, fmt, proto)
                    with open(tmp, 'wb') as f:
                        f.write(data)
                    os.replace(tmp, out_path)
                    ok += 1
                except KeyboardInterrupt:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    raise
                except BaseException as e:
                    if os.path.exists(tmp):
                        os.remove(tmp)
                    errors.append((name, f'{type(e).__name__}: {e}'))
                done = i
                if i < total:
                    print()                          # blank line between bars
        except KeyboardInterrupt:
            aborted = True
            print(dim(f'\n  interrupted at {done}/{total} — {ok} completed files kept.'))
    else:
        # workers ignore SIGINT — only the main process catches interrupt.
        import signal
        import time as _tt
        from collections import deque
        mgr = mp.Manager()
        pq = mgr.Queue()
        active = {}
        t0b = _tt.monotonic()
        bars = LiveBlock()
        map_t0 = {}

        def _status(completed, extra=''):
            now = _tt.monotonic()
            for name in list(map_t0):
                if name not in active:
                    map_t0.pop(name, None)
            elapsed_maps = {}
            for name in active:
                map_t0.setdefault(name, now)
                elapsed_maps[name] = now - map_t0[name]
            bars.render(_pool_status_lines(
                completed, total, active, extra=extra,
                elapsed=now - t0b, map_elapsed=elapsed_maps))

        def _finish_bars(completed):
            bars.render(_pool_status_lines(
                completed, total, {}, elapsed=_tt.monotonic() - t0b))
            bars.stop()

        if fixed_jobs:
            orig = signal.signal(signal.SIGINT, signal.SIG_IGN)
            pool = mp.Pool(fixed_jobs, _init_worker, (pq,))
            signal.signal(signal.SIGINT, orig)
            asyncs = [pool.apply_async(_worker, (job,)) for job in tasks]
            try:
                while True:
                    if stop_event and stop_event.is_set():
                        aborted = True
                        pool.terminate()
                        bars.stop()
                        print(dim(f'\n  generation stopped at {done}/{total} — {ok} completed files kept.'))
                        break
                    _drain_progress(pq, active)
                    completed = sum(1 for a in asyncs if a.ready())
                    _status(completed)
                    if completed >= total:
                        break
                    _tt.sleep(0.5)
                _finish_bars(total)
                for a in asyncs:
                    name, err = a.get()
                    done += 1
                    if err is None:
                        ok += 1
                    else:
                        errors.append((name, err))
            except KeyboardInterrupt:
                aborted = True
                pool.terminate()
                bars.stop()
                print(dim(f'\n  interrupted at {done}/{total} — {ok} completed files kept.'))
            else:
                pool.close()
            finally:
                pool.join()
                _cleanup_geo_tmps(out_dir)
        else:
            import queue as _queue
            ctx = mp.get_context('spawn')
            rq = mgr.Queue()
            pending = deque(tasks)
            live = []
            last_spawn = 0.0
            run_seq = 0
            live_ids = set()
            try:
                while pending or live:
                    if stop_event and stop_event.is_set():
                        aborted = True
                        for rec in live:
                            rec['proc'].terminate()
                        bars.stop()
                        print(dim(f'\n  generation stopped at {done}/{total} — {ok} completed files kept.'))
                        break
                    _drain_progress(pq, active)
                    dead = []
                    still = []
                    for rec in live:
                        if rec['proc'].is_alive():
                            still.append(rec)
                        else:
                            rec['proc'].join()
                            dead.append(rec)
                    live = still
                    while True:
                        try:
                            run_id, name, err = rq.get_nowait()
                        except _queue.Empty:
                            break
                        if run_id not in live_ids:
                            continue
                        live_ids.discard(run_id)
                        done += 1
                        if err is None:
                            ok += 1
                        else:
                            errors.append((name, err))
                    for rec in dead:
                        if rec['run_id'] not in live_ids:
                            continue
                        live_ids.discard(rec['run_id'])
                        done += 1
                        errors.append((rec['job'][1], 'worker exited with no result'))
                    avail = _avail_ram_gb()
                    delta = want_worker_delta(
                        len(live), bool(pending), avail, min_free_ram, max_n)
                    now = _tt.monotonic()
                    if delta > 0 and pending and (now - last_spawn) >= 0.8:
                        job = pending.popleft()
                        run_seq += 1
                        proc = ctx.Process(target=_process_main,
                                           args=(job, pq, rq, run_seq))
                        proc.start()
                        live.append({'proc': proc, 'job': job, 'run_id': run_seq})
                        live_ids.add(run_seq)
                        last_spawn = now
                    elif delta < 0 and live and (now - last_spawn) >= 2.0:
                        rec = live.pop()
                        live_ids.discard(rec['run_id'])
                        rec['proc'].terminate()
                        rec['proc'].join(5)
                        if rec['proc'].is_alive():
                            rec['proc'].kill()
                            rec['proc'].join(2)
                        pending.appendleft(rec['job'])
                        tmp = rec['job'][2] + '.tmp'
                        if os.path.exists(tmp):
                            os.remove(tmp)
                        active.pop(rec['job'][1], None)
                        last_spawn = now
                    extra = f'  j={len(live)}'
                    if avail is not None:
                        extra += f'  {avail:.1f}GB free'
                    _status(done, extra)
                    if pending or live:
                        _tt.sleep(0.5)
                _finish_bars(done)
            except KeyboardInterrupt:
                aborted = True
                for rec in live:
                    rec['proc'].terminate()
                for rec in live:
                    rec['proc'].join(3)
                bars.stop()
                print(dim(f'\n  interrupted at {done}/{total} — {ok} completed files kept.'))
            finally:
                _cleanup_geo_tmps(out_dir)
    if aborted:
        return 130
    print(f'\n  {bold("Summary")} in {(_t.time() - t0) / 60:.1f} min:'
          f' {green(f"✓ {ok}")}' + (f' · {red(f"✗ {len(errors)}")}' if errors else ''))
    for name, why in errors[:10]:
        print(f'    {red("✗")} {name}: {why}')
    if errors:
        print(dim('    (maps with no heightmap in the client were skipped — nothing'
                  ' to generate there)'))
    if not terrain_only:
        print(f'\n  {bold("What next:")}')
        if out_fmt == 'pts':
            print(f'    • {out_dir}/ — one <name>_conv.dat per map (PTS protocol {proto},'
                  ' ready for the server).')
            print(dim('      Encoded in memory from the L2J body; no intermediate .l2j was written.'))
        else:
            print(f'    • {out_dir}/ — one <name>.l2j file per map. Name = map name'
                  ' in Maps (XX_YY and XX_YY_Classic are separate files).')
            print(dim('      For a classic server the square from XX_YY_Classic.l2j is placed'
                      ' under the name XX_YY.l2j (replaces the base).'))
            print(dim('      PTS for the server: geotool.py l2j2pts ' + out_dir
                      + ' -o <pts_dir>  — or generate with --format pts next time.'))
        print(f'\n  {yellow("Check before installing:")}')
        print(f'    geotool.py view {out_dir}   — inspect the map/cities/layers in a browser')
        print('    geotool.py diff <your_geodata> ' + out_dir
              + '   — compare with current (heights and walkability)')
        print(dim('    …and walk the key zones in-game — generation'
                  ' does not check them itself.'))
    return 0 if not errors else 2
