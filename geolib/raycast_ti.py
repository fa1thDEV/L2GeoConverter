#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-vendor GPU/CPU raycast backend on Taichi (CUDA/Vulkan/Metal/CPU).

Optional: if Taichi is not installed, the caller falls back to
pure Python. Taichi requires Python ≤3.13; the same code runs on any
supported card (NVIDIA/AMD/Intel/Apple).

Data is prepared in Python (the same _prep_geometry faces), then rays are
computed in parallel over cells/edges on the device. The result (floors/ceilings
per cell, walls per edge-layer) is returned to Python for L2J assembly.
"""

_TI = None            # taichi module after init (or None)
_ARCH = None          # selected backend (for reporting)
CELLS = 2048


def available():
    """Whether Taichi is installed (without initializing a device)."""
    try:
        import taichi  # noqa: F401
        return True
    except Exception:
        return False


def init(prefer_gpu=True):
    """Initialize Taichi with MANDATORY f64 — the result must match the
    CPU reference byte-for-byte regardless of hardware. GPU is used ONLY if it
    supports f64 (CUDA/some Vulkan). A device without f64 (Metal/Apple) is not
    suitable for GPU — fall back to Taichi-CPU (also f64, native multithreaded code,
    identical result). Returns the backend name, or None if Taichi is unavailable."""
    global _TI, _ARCH
    if _TI is not None:
        return _ARCH
    try:
        import taichi as ti
    except Exception:
        return None
    ok = False
    if prefer_gpu:
        try:                                          # GPU only with f64
            # fast_math=False is MANDATORY: otherwise the backend/LLVM may fold a*b+c
            # into FMA and reassociate → 1 ULP divergence → flip of boundary
            # comparisons in rays → different bytes. Determinism matters more than micro-speed.
            ti.init(arch=ti.gpu, default_fp=ti.f64, fast_math=False,
                    offline_cache=True, log_level=ti.ERROR)
            # probe f64 kernel: Metal will fail here ("f64 not supported")
            _probe_f64(ti)
            ok = True
        except Exception:
            ok = False
    if not ok:                                        # CPU f64 backend (available everywhere)
        ti.init(arch=ti.cpu, default_fp=ti.f64, fast_math=False,
                log_level=ti.ERROR)
        _probe_f64(ti)
    _TI = ti
    _ARCH = str(ti.lang.impl.current_cfg().arch).rsplit('.', 1)[-1]
    return _ARCH


def _probe_f64(ti):
    """Compile an f64 kernel REPRESENTATIVE of real rays (division,
    comparisons, cast) — fails on devices without full f64 (Metal, some
    Vulkan/MoltenVK, where simple multiply compiles but division does not)."""
    a = ti.ndarray(ti.f64, shape=(4,))

    @ti.kernel
    def k(a: ti.types.ndarray()):
        for i in range(4):
            x = a[i] * 2.0 + 1.0
            f = 1.0 / (x + 3.0)                 # f64 division (kills incomplete f64)
            s = 0.0
            if f > 0.0 and f <= 1.0:            # f64 comparisons
                s = f * (x - a[i])
            a[i] = s + ti.cast(f > 0.5, ti.f64)
    k(a)
    ti.sync()


def zray_columns(fc, fc_grid, west, north, cells_order, walk_nz):
    """Z-ray on the device: for each cell cells_order[i] with faces fc_grid —
    intersections of the center vertical with floor/ceiling faces fc.
    Returns (out_z[n,max_hits], out_isfloor[n,max_hits], out_cnt[n]) as numpy,
    where max_hits = maximum cell degree (no layer truncation).
    fc[i] = (is_floor, ax,ay,az, ux,uy,uz, vx,vy,vz, d00,d01,d11, inv)."""
    ti = _TI
    import numpy as np
    n = len(cells_order)
    # CSR layout of faces by cells in cells_order
    offs = np.zeros(n + 1, dtype=np.int32)
    flat = []
    for i, cell in enumerate(cells_order):
        idxs = fc_grid.get(cell, ())
        flat.extend(idxs)
        offs[i + 1] = len(flat)
    flat = np.asarray(flat, dtype=np.int32)
    # number of vertical intersections in a cell ≤ its face count → allocate exactly
    # the maximum degree (no layer truncation, unlike a fixed limit).
    max_hits = int(np.max(offs[1:] - offs[:-1])) if n else 1
    max_hits = max(max_hits, 1)
    fc_arr = np.asarray(fc, dtype=np.float64)                 # (N_fc, 14) — f64!
    cellxy = np.empty((n, 2), dtype=np.int32)
    for i, cell in enumerate(cells_order):
        cellxy[i, 0] = cell % CELLS
        cellxy[i, 1] = cell // CELLS

    f_fc = ti.ndarray(ti.f64, shape=fc_arr.shape)
    f_flat = ti.ndarray(ti.i32, shape=flat.shape if flat.size else (1,))
    f_off = ti.ndarray(ti.i32, shape=offs.shape)
    f_cxy = ti.ndarray(ti.i32, shape=(n, 2))
    o_z = ti.ndarray(ti.f64, shape=(n, max_hits))
    o_fl = ti.ndarray(ti.i32, shape=(n, max_hits))
    o_cnt = ti.ndarray(ti.i32, shape=(n,))
    f_fc.from_numpy(fc_arr)
    if flat.size:
        f_flat.from_numpy(flat)
    f_off.from_numpy(offs)
    f_cxy.from_numpy(cellxy)

    @ti.kernel
    def zray(f_fc: ti.types.ndarray(), f_flat: ti.types.ndarray(),
             f_off: ti.types.ndarray(), f_cxy: ti.types.ndarray(),
             o_z: ti.types.ndarray(), o_fl: ti.types.ndarray(),
             o_cnt: ti.types.ndarray(), west: ti.f64, north: ti.f64):
        for i in range(n):
            px = west + f_cxy[i, 0] * 16 + 8
            py = north + f_cxy[i, 1] * 16 + 8
            cnt = 0
            for k in range(f_off[i], f_off[i + 1]):
                fi = f_flat[k]
                ax = f_fc[fi, 1]
                ay = f_fc[fi, 2]
                az = f_fc[fi, 3]
                ux = f_fc[fi, 4]
                uy = f_fc[fi, 5]
                uz = f_fc[fi, 6]
                vx = f_fc[fi, 7]
                vy = f_fc[fi, 8]
                vz = f_fc[fi, 9]
                d00 = f_fc[fi, 10]
                d01 = f_fc[fi, 11]
                d11 = f_fc[fi, 12]
                inv = f_fc[fi, 13]
                pxr = px - ax
                pyr = py - ay
                d02 = vx * pxr + vy * pyr
                d12 = ux * pxr + uy * pyr
                u = (d11 * d02 - d01 * d12) * inv
                v = (d00 * d12 - d01 * d02) * inv
                if u >= -0.02 and v >= -0.02 and u + v <= 1.02:
                    z = az + u * vz + v * uz
                    if z >= -16384.0 and z <= 16376.0 and cnt < max_hits:
                        o_z[i, cnt] = z
                        o_fl[i, cnt] = ti.cast(f_fc[fi, 0] > 0.5, ti.i32)
                        cnt += 1
            o_cnt[i] = cnt

    zray(f_fc, f_flat, f_off, f_cxy, o_z, o_fl, o_cnt, float(west), float(north))
    ti.sync()
    return o_z.to_numpy(), o_fl.to_numpy(), o_cnt.to_numpy()


def nswe_grid(cell_layers, hcell, walls, w_grid, blocked, west, north,
              up_step, down_step, ray_offs, lat_offs, blk_lo, blk_hi):
    """NSWE of all layers of the entire grid on the device (hot assembly loop). For each
    2048² cell and each of its z layers, computes 4 walkability bits N,S,W,E with the same
    logic as Python build_l2j_ray: height delta to neighbor layers (_step_ok),
    blocking edges blocked (dict key → (zlo, zhi), block only a layer
    whose body window blk_lo..blk_hi intersects their z-range) and body wall —
    X/Y rays seg_hit against faces of the cell AND the neighbor: heights ray_offs above the floor ×
    lateral offsets lat_offs, ANY hit = wall (chest window).
    Plus anti-deaf. A wall is counted for ANY cell with neighboring wall-faces
    (including terrain cells without floor layers).

    Returns (nswe_flat, l_off): nswe_flat[l_off[cell]+j] — nswe of the j-th layer.
    Layers are laid out in CSR; most cells have 1 terrain layer, multilayers
    are rare. hcell — list[C][C] (terrain, [gy][gx])."""
    ti = _TI
    import numpy as np
    C = CELLS
    N = C * C
    hc_flat = np.asarray(hcell, dtype=np.float64).reshape(-1)   # cell = gy*C+gx

    # ── CSR of layers: counts=1 (terrain) or len(ls) for cells with geometry ──
    counts = np.ones(N, dtype=np.int64)
    for cell, ls in cell_layers.items():
        counts[cell] = len(ls)
    l_off = np.zeros(N + 1, dtype=np.int64)
    np.cumsum(counts, out=l_off[1:])
    total = int(l_off[-1])
    l_z = np.empty(total, dtype=np.float64)
    base_pos = l_off[:N]                                        # offset of the cell's layer-0
    l_z[base_pos] = hc_flat                                     # terrain by default
    for cell, ls in cell_layers.items():                       # multilayers on top
        o = int(l_off[cell])
        for j, z in enumerate(ls):
            l_z[o + j] = z

    # ── CSR of walls over all grid cells (sparse, off[c]==off[c+1] if empty) ──
    w_counts = np.zeros(N, dtype=np.int64)
    for cell, idxs in w_grid.items():
        w_counts[cell] = len(idxs)
    w_off = np.zeros(N + 1, dtype=np.int64)
    np.cumsum(w_counts, out=w_off[1:])
    w_total = int(w_off[-1])
    w_flat = np.empty(max(w_total, 1), dtype=np.int32)
    for cell, idxs in w_grid.items():
        o = int(w_off[cell])
        w_flat[o:o + len(idxs)] = idxs
    walls_arr = np.asarray(walls, dtype=np.float64) if walls else \
        np.zeros((1, 9), dtype=np.float64)

    # ── blocking edges into grid arrays of z-ranges ──
    # sentinel (lo=+1e30 > hi=-1e30) — edges with no volume: the window does not intersect
    blk_y_lo = np.full(N, 1e30)          # ('y', gx, gy): N edge of cell (gx,gy)
    blk_y_hi = np.full(N, -1e30)
    blk_x_lo = np.full(N, 1e30)          # ('x', gx, gy): W edge of cell (gx,gy)
    blk_x_hi = np.full(N, -1e30)
    for (kind, gx, gy), (zlo, zhi) in blocked.items():
        if 0 <= gx < C and 0 <= gy < C:
            i = gy * C + gx
            if kind == 'y':
                blk_y_lo[i], blk_y_hi[i] = zlo, zhi
            else:
                blk_x_lo[i], blk_x_hi[i] = zlo, zhi

    l_off32 = l_off.astype(np.int32)
    f_off = ti.ndarray(ti.i32, shape=(N + 1,))
    f_z = ti.ndarray(ti.f64, shape=(max(total, 1),))
    f_woff = ti.ndarray(ti.i32, shape=(N + 1,))
    f_wflat = ti.ndarray(ti.i32, shape=(max(w_total, 1),))
    f_walls = ti.ndarray(ti.f64, shape=walls_arr.shape)
    f_bylo = ti.ndarray(ti.f64, shape=(N,))
    f_byhi = ti.ndarray(ti.f64, shape=(N,))
    f_bxlo = ti.ndarray(ti.f64, shape=(N,))
    f_bxhi = ti.ndarray(ti.f64, shape=(N,))
    o_nswe = ti.ndarray(ti.i32, shape=(max(total, 1),))
    f_off.from_numpy(l_off32)
    f_z.from_numpy(l_z if total else np.zeros(1, np.float64))
    f_woff.from_numpy(w_off.astype(np.int32))
    f_wflat.from_numpy(w_flat)
    f_walls.from_numpy(walls_arr)
    f_bylo.from_numpy(blk_y_lo)
    f_byhi.from_numpy(blk_y_hi)
    f_bxlo.from_numpy(blk_x_lo)
    f_bxhi.from_numpy(blk_x_hi)

    @ti.func
    def seg_hit(px, py, pz, npx, npy, ax, ay, az,
                e1x, e1y, e1z, e2x, e2y, e2z) -> ti.i32:
        dx = npx - px
        dy = npy - py
        hx = dy * e2z
        hy = -dx * e2z
        hz = dx * e2y - dy * e2x
        a = e1x * hx + e1y * hy + e1z * hz
        res = 0
        if a >= 1e-9 or a <= -1e-9:                  # == Python `not (-1e-9 < a < 1e-9)`
            f = 1.0 / a
            sx = px - ax
            sy = py - ay
            sz = pz - az
            u = f * (sx * hx + sy * hy + sz * hz)
            if u >= 0.0 and u <= 1.0:
                qx = sy * e1z - sz * e1y
                qy = sz * e1x - sx * e1z
                qz = sx * e1y - sy * e1x
                vv = f * (dx * qx + dy * qy)
                if vv >= 0.0 and u + vv <= 1.0:
                    t = f * (e2x * qx + e2y * qy + e2z * qz)
                    if t >= 0.0 and t <= 1.0:
                        res = 1
        return res

    @ti.func
    def wall_any(px, py, z, npx, npy, lx, ly,
                 ax, ay, az, e1x, e1y, e1z, e2x, e2y, e2z) -> ti.i32:
        # chest window: rays ray_offs above the floor × parallel lines
        # lat_offs across the travel direction; ANY hit = wall (== Python
        # _wall_between, order does not matter — any-hit)
        res = 0
        for li in ti.static(range(len(lat_offs))):
            for ri in ti.static(range(len(ray_offs))):
                if res == 0:
                    if seg_hit(px + lx * lat_offs[li], py + ly * lat_offs[li],
                               z + ray_offs[ri],
                               npx + lx * lat_offs[li], npy + ly * lat_offs[li],
                               ax, ay, az, e1x, e1y, e1z, e2x, e2y, e2z) == 1:
                        res = 1
        return res

    @ti.kernel
    def nk(f_off: ti.types.ndarray(), f_z: ti.types.ndarray(),
           f_woff: ti.types.ndarray(), f_wflat: ti.types.ndarray(),
           f_walls: ti.types.ndarray(), f_bylo: ti.types.ndarray(),
           f_byhi: ti.types.ndarray(), f_bxlo: ti.types.ndarray(),
           f_bxhi: ti.types.ndarray(), o_nswe: ti.types.ndarray(),
           west: ti.f64, north: ti.f64, up: ti.f64, down: ti.f64,
           blo: ti.f64, bhi: ti.f64):
        for cell in range(N):
            gx = cell % C
            gy = cell // C
            px = west + gx * 16 + 8
            py = north + gy * 16 + 8
            for k in range(f_off[cell], f_off[cell + 1]):
                z = f_z[k]
                nswe = 15
                wall_bits = 0                            # walls/decor
                block_bits = 0                           # BlockingVolume
                for d in ti.static(range(4)):
                    bit = 8 >> d                        # N=8,S=4,W=2,E=1
                    ngx = gx + (0 if d < 2 else (-1 if d == 2 else 1))
                    ngy = gy + (-1 if d == 0 else (1 if d == 1 else 0))
                    if 0 <= ngx < C and 0 <= ngy < C:
                        ncell = ngy * C + ngx
                        # height_ok: whether the neighbor has a layer within the height step
                        hok = 0
                        for kk in range(f_off[ncell], f_off[ncell + 1]):
                            dz = f_z[kk] - z
                            if dz >= -down and dz <= up:
                                hok = 1
                        # blocking edge of direction d: volume z-range
                        blk_zlo = 1e30
                        blk_zhi = -1e30
                        if ti.static(d == 0):
                            blk_zlo = f_bylo[cell]
                            blk_zhi = f_byhi[cell]
                        elif ti.static(d == 1):
                            blk_zlo = f_bylo[ncell]
                            blk_zhi = f_byhi[ncell]
                        elif ti.static(d == 2):
                            blk_zlo = f_bxlo[cell]
                            blk_zhi = f_bxhi[cell]
                        else:
                            blk_zlo = f_bxlo[ncell]
                            blk_zhi = f_bxhi[ncell]
                        # blocks only if the range intersects the layer's
                        # body window (a volume on a bridge does not lock the floor beneath it)
                        if blk_zlo < z + bhi and blk_zhi > z + blo:
                            nswe &= ~bit
                            if hok == 1:
                                block_bits |= bit
                        elif hok == 0:
                            nswe &= ~bit
                        else:
                            # X/Y wall rays (chest window, any-hit) against faces
                            # of this cell AND the neighbor
                            npx = west + ngx * 16 + 8
                            npy = north + ngy * 16 + 8
                            lxs = 1.0 if d < 2 else 0.0    # across the travel direction
                            lys = 0.0 if d < 2 else 1.0
                            hitw = 0
                            for kk in range(f_woff[cell], f_woff[cell + 1]):
                                if hitw == 0:
                                    wi = f_wflat[kk]
                                    hitw = wall_any(
                                        px, py, z, npx, npy, lxs, lys,
                                        f_walls[wi, 0], f_walls[wi, 1], f_walls[wi, 2],
                                        f_walls[wi, 3], f_walls[wi, 4], f_walls[wi, 5],
                                        f_walls[wi, 6], f_walls[wi, 7], f_walls[wi, 8])
                            for kk in range(f_woff[ncell], f_woff[ncell + 1]):
                                if hitw == 0:
                                    wi = f_wflat[kk]
                                    hitw = wall_any(
                                        px, py, z, npx, npy, lxs, lys,
                                        f_walls[wi, 0], f_walls[wi, 1], f_walls[wi, 2],
                                        f_walls[wi, 3], f_walls[wi, 4], f_walls[wi, 5],
                                        f_walls[wi, 6], f_walls[wi, 7], f_walls[wi, 8])
                            if hitw == 1:
                                nswe &= ~bit
                                wall_bits |= bit
                # anti-deaf: restore a passable side, but keep a through-going
                # BlockingVolume barrier (N-S axis=12 or W-E=3) closed
                if nswe == 0 and (wall_bits != 0 or block_bits != 0):
                    give = wall_bits | block_bits
                    if (block_bits & 12) == 12:
                        give &= ~12
                    if (block_bits & 3) == 3:
                        give &= ~3
                    nswe = give
                o_nswe[k] = nswe

    nk(f_off, f_z, f_woff, f_wflat, f_walls, f_bylo, f_byhi, f_bxlo, f_bxhi,
       o_nswe, float(west), float(north), float(up_step), float(down_step),
       float(blk_lo), float(blk_hi))
    ti.sync()
    nswe_np = o_nswe.to_numpy()
    # nswe_np[l_off[cell]+j] = nswe of the j-th layer of cell (terrain = layer 0).
    # Layer order matches ls in build_l2j_ray → O(1) access without dictionaries.
    return nswe_np, l_off32
