#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pack UNR collision meshes + BSP for the 3D viewer overlay."""

import os
import struct

from .formats import GeoError
from .generate import REGION_UNITS, Z_CALIBRATION, _region_id, gather_collision_triangles, map_path
from .meshes import VIEW_BLOCKING_VOLUME_CLASSES, volume_triangles
from .unreal import Package

MAGIC = b'L2U1'
HEADER = struct.Struct('<4sIffIIII')  # magic ntri zmin zmax nmesh nbsp nblk skipped
KIND_MESH, KIND_BSP, KIND_BLOCK = 0, 1, 2
MAX_TRIS = 220_000
MAX_BSP = 120_000
MAX_MESH = 140_000
MAX_BLOCK = 20_000


def client_dirs(client_dir):
    maps_dir = os.path.join(client_dir, 'Maps')
    if not os.path.isdir(maps_dir):
        maps_dir = os.path.join(client_dir, 'MAPS')
    usx_dir = os.path.join(client_dir, 'StaticMeshes')
    if not os.path.isdir(usx_dir):
        usx_dir = os.path.join(client_dir, 'staticmeshes')
    return maps_dir, usx_dir if os.path.isdir(usx_dir) else None


def guess_client(geodata_dir):
    """Parent of a geodata folder is usually the L2 client (Maps + StaticMeshes)."""
    cand = os.path.abspath(os.path.join(geodata_dir, os.pardir))
    maps_dir, _ = client_dirs(cand)
    if os.path.isdir(maps_dir):
        return cand
    return None


def _area2(tri):
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
    abx, aby, abz = bx - ax, by - ay, bz - az
    acx, acy, acz = cx - ax, cy - ay, cz - az
    crx = aby * acz - abz * acy
    cry = abz * acx - abx * acz
    crz = abx * acy - aby * acx
    return crx * crx + cry * cry + crz * crz


def _in_region(tri, west, north, pad=4096):
    hi_x, hi_y = west + REGION_UNITS + pad, north + REGION_UNITS + pad
    lo_x, lo_y = west - pad, north - pad
    for x, y, _z in tri:
        if lo_x <= x <= hi_x and lo_y <= y <= hi_y:
            return True
    return False


def _shift(tri, zc):
    return tuple((x, y, z + zc) for x, y, z in tri)


def _pick(tris, kind, cap):
    if len(tris) <= cap:
        return [(t, kind) for t in tris]
    scored = [(_area2(t), t) for t in tris]
    scored.sort(key=lambda x: -x[0])
    return [(t, kind) for _a, t in scored[:cap]]


def pack_region_unr(client_dir, map_name, mesh_lib=None):
    """Return (bytes, meta) for GET /api/unr/<region>.

    Binary: 32-byte header + ntri×9 float32 (wx,wy,wz per vertex) + ntri uint8 kinds.
    Kind 0 = static mesh, 1 = BSP interior, 2 = BlockingVolume.
    Z uses the same +43.35 calibration as generate."""
    maps_dir, usx_dir = client_dirs(client_dir)
    if not os.path.isdir(maps_dir):
        raise GeoError(f'no Maps folder in {client_dir}')
    region = _region_id(map_name)
    rx, ry = map(int, region.split('_'))
    west, north = (rx - 20) * REGION_UNITS, (ry - 18) * REGION_UNITS
    skipped = 0
    mesh_tris, solid, blocking = [], [], []
    if usx_dir:
        mesh_tris, solid, blocking, skipped = gather_collision_triangles(
            maps_dir, usx_dir, map_name, west, north, lib=mesh_lib)
    else:
        from .meshes import level_extra_triangles
        solid, blocking = level_extra_triangles(Package(map_path(maps_dir, map_name)))
    # Generate omits BlockingVolume (official PathMaker leaves them open).
    # The overlay still draws the brushes so they can be compared to geo.
    if VIEW_BLOCKING_VOLUME_CLASSES:
        blocking = volume_triangles(
            Package(map_path(maps_dir, map_name)), VIEW_BLOCKING_VOLUME_CLASSES)
    zc = Z_CALIBRATION
    mesh_w = [_shift(t, zc) for t in mesh_tris if _in_region(t, west, north)]
    bsp_w = [_shift(t, zc) for t in solid if _in_region(t, west, north)]
    blk_w = [_shift(t, zc) for t in blocking if _in_region(t, west, north)]
    picked = (
        _pick(bsp_w, KIND_BSP, MAX_BSP)
        + _pick(blk_w, KIND_BLOCK, MAX_BLOCK)
        + _pick(mesh_w, KIND_MESH, MAX_MESH)
    )
    if len(picked) > MAX_TRIS:
        picked = picked[:MAX_TRIS]
    ntri = len(picked)
    nmesh = sum(1 for _t, k in picked if k == KIND_MESH)
    nbsp = sum(1 for _t, k in picked if k == KIND_BSP)
    nblk = sum(1 for _t, k in picked if k == KIND_BLOCK)
    zmin, zmax = 0.0, 0.0
    pos = bytearray(ntri * 9 * 4)
    kinds = bytearray(ntri)
    off = 0
    for i, (tri, kind) in enumerate(picked):
        kinds[i] = kind
        for x, y, z in tri:
            struct.pack_into('<fff', pos, off, x, y, z)
            off += 12
            if off == 12:
                zmin = zmax = z
            else:
                if z < zmin:
                    zmin = z
                if z > zmax:
                    zmax = z
    body = HEADER.pack(MAGIC, ntri, float(zmin), float(zmax),
                       nmesh, nbsp, nblk, int(skipped)) + bytes(pos) + bytes(kinds)
    meta = {
        'ntri': ntri, 'nmesh': nmesh, 'nbsp': nbsp, 'nblk': nblk,
        'skipped': skipped, 'zmin': zmin, 'zmax': zmax,
    }
    return body, meta
