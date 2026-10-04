#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parsing UStaticMesh from .usx (UE2 / Lineage 2) and actor transforms."""

import math
import os
import struct

from .formats import GeoError
from .unreal import Package, Reader, read_properties, PF_NOTSOLID, PF_PORTAL

# BSP faces this wide on an XY edge are skybox/backdrop, not pawn collision.
BSP_SKYBOX_EDGE = 16384
BSP_WORLD_CUBE_Z = 16376

# UNR collision ingest vs official Glory Days (OTHER_SUPERPOINT/GLORY_DAYS).
# Census of all 219 Maps/*.unr (25 Aug 2026): every export class that holds a
# StaticMesh import is listed below. Generate keeps only StaticMeshActor.
# PathMaker does not bake the omitted classes (actor XY on official maps is
# NSWE=15, or the mesh is sky/particles/a moving door).
MESH_ACTOR_CLASSES = ('StaticMeshActor',)
OMIT_MESH_ACTOR_CLASSES = (
    'Mover',                       # doors/gates; DoorData closes them at runtime
    'MovableStaticMeshActor',      # 338 default-collide on official maps; 78% NSWE=15
    'L2MovableStaticMeshActor',    # 550; 83% NSWE=15; flying ice / orbis / Harnak
    'CustomizableStaticMeshActor', # monuments; 21 Aug match without them
    'SkyMeshActor',                # sky dome (L2sky_*)
    'MeshEmitter',                 # particle meshes
)
# Volume brushes: BlockingVolume 25 Aug (~92% inner walls NSWE=15 official);
# ServerBlockingVolume 21 Aug (extra NSWE only). Water/Music/Ambient/Camera
# volumes are engine triggers, not pawn walls.
BLOCKING_VOLUME_CLASSES = ()
# Viewer overlay still draws client BlockingVolumes (not baked into geo).
VIEW_BLOCKING_VOLUME_CLASSES = ('BlockingVolume',)
ZONE_HULL_XY = 4096


def is_zone_hull(tris):
    """True if the volume's XY AABB is a zone box (large in both axes)."""
    if not tris:
        return False
    xs = [p[0] for t in tris for p in t]
    ys = [p[1] for t in tris for p in t]
    return (max(xs) - min(xs) > ZONE_HULL_XY
            and max(ys) - min(ys) > ZONE_HULL_XY)


def _exports(pkg, class_names):
    out = []
    for name in class_names:
        out.extend(pkg.find_exports(name))
    return out


def bsp_face_collides(tri, flags):
    """Whether a BSP triangle is pawn collision — same rule generate uses.

    Skip PF_NotSolid (water/haze/walk-through sheets) and portals. Skip
    skybox-scale XY edges and world-cube Z planes. Large dungeon floors
    without those flags are kept (size alone is not a reason to drop).
    """
    if flags & (PF_PORTAL | PF_NOTSOLID):
        return False
    (ax, ay, az), (bx, by, bz), (cx, cy, cz) = tri
    if max(abs(ax - bx), abs(ay - by), abs(bx - cx), abs(by - cy),
           abs(cx - ax), abs(cy - ay)) > BSP_SKYBOX_EDGE:
        return False
    if min(az, bz, cz) >= BSP_WORLD_CUBE_Z or max(az, bz, cz) <= -BSP_WORLD_CUBE_Z:
        return False
    return True


def parse_staticmesh(pkg, e):
    """StaticMesh export → (verts, tris) — collision sections only.

    Collision in L2 is set per-material (Materials[i].EnableCollision);
    mesh section i uses material i (tree canopies have no collision)."""
    props = read_properties(pkg, e)
    materials = props.get('Materials') or []
    r = Reader(pkg.data, props['__end__'])
    obj_end = e.offset + e.size
    # UPrimitive: FBox + FSphere
    r.read(25)
    r.read(16)                                    # sphere
    # sections: u32, first_index u16, min_v u16, max_v u16, tri_count u16, tri_max u16
    n_sec = r.ci()
    if not (0 < n_sec < 1000):
        raise GeoError(f'{e.name}: suspicious section count {n_sec}')
    sections = []
    for si in range(n_sec):
        _u, first_index, _mn, _mx, tri_count, _tm = struct.unpack_from(
            '<IHHHHH', pkg.data, r.p + 14 * si)
        coll = True
        if si < len(materials):
            coll = bool(materials[si].get('EnableCollision', True))
        sections.append((first_index, tri_count, coll))
    r.read(14 * n_sec)
    # vertex-stream FBox
    r.read(24); r.u8()
    # vertices: pos + normal
    n_v = r.ci()
    if not (0 < n_v < 2_000_000):
        raise GeoError(f'{e.name}: suspicious vertex count {n_v}')
    verts = []
    d = pkg.data
    p0 = r.p
    for i in range(n_v):
        off = p0 + i * 24
        verts.append(struct.unpack_from('<fff', d, off))
    r.p = p0 + n_v * 24
    r.i32()                                       # revision
    # color and alpha streams: TArray<FColor> + rev
    for _ in range(2):
        n = r.ci()
        r.read(4 * n); r.i32()
    # UV streams: count, each TArray<8b> + f10 + rev
    n_uv = r.ci()
    if not (0 <= n_uv < 16):
        raise GeoError(f'{e.name}: suspicious UV-stream count {n_uv}')
    for _ in range(n_uv):
        n = r.ci()
        r.read(8 * n); r.i32(); r.i32()
    # index buffer
    n_i = r.ci()
    if not (0 < n_i < 6_000_000) or r.p + n_i * 2 > obj_end:
        raise GeoError(f'{e.name}: suspicious index buffer {n_i}')
    idx = struct.unpack_from(f'<{n_i}H', d, r.p)
    tris = []
    if any(c for _, _, c in sections):
        for first_index, tri_count, coll in sections:
            if not coll:
                continue
            for t in range(tri_count):
                base = first_index + t * 3
                if base + 2 < n_i:
                    tris.append((idx[base], idx[base + 1], idx[base + 2]))
    # tail (wireframe, collision, kDOP) is not needed
    if not tris:
        return [], []
    lo = min(min(v) for v in verts)
    hi = max(max(v) for v in verts)
    if not (-600000 < lo and hi < 600000):
        raise GeoError(f'{e.name}: vertices outside a reasonable range')
    return verts, tris


_ANG = math.pi / 32768.0


def actor_matrix(rot, scale, scale3d):
    """Actor rotation+scale matrix (UE2: Roll(X) first, then Pitch(Y), Yaw(Z))."""
    if rot is None:
        rot = (0, 0, 0)
    pitch, yaw, roll = rot[0] * _ANG, rot[1] * _ANG, rot[2] * _ANG
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    cr, sr = math.cos(roll), math.sin(roll)
    # UE2 FRotationMatrix
    m = [
        [cp * cy, cp * sy, sp],
        [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
        [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp],
    ]
    s = scale if scale else 1.0
    s3 = scale3d if scale3d else (1.0, 1.0, 1.0)
    return [[m[c][r_] * s * s3[c] for c in range(3)] for r_ in range(3)]


def transform(verts, mtx, loc):
    lx, ly, lz = loc
    out = []
    for x, y, z in verts:
        out.append((
            x * mtx[0][0] + y * mtx[0][1] + z * mtx[0][2] + lx,
            x * mtx[1][0] + y * mtx[1][1] + z * mtx[1][2] + ly,
            x * mtx[2][0] + y * mtx[2][1] + z * mtx[2][2] + lz,
        ))
    return out


class MeshLibrary:
    """Cache of parsed meshes keyed by (package, name).

    Raw USX packages (the whole file in memory) are bounded by an LRU limit —
    otherwise a city region balloons every worker by gigabytes."""

    MAX_PACKAGES = 6

    def __init__(self, usx_dir):
        import collections
        self.usx_dir = usx_dir
        self.packages = collections.OrderedDict()  # LRU: most recent at the end
        self.meshes = {}
        self.failed = {}

    def get(self, pkg_name, mesh_name):
        key = (pkg_name.lower(), mesh_name)
        if key in self.meshes:
            return self.meshes[key]
        if key in self.failed:
            return None
        try:
            low = pkg_name.lower()
            pkg = self.packages.get(low)
            if pkg is not None:
                self.packages.move_to_end(low)     # refresh recency
            if pkg is None:
                path = os.path.join(self.usx_dir, pkg_name + '.usx')
                if not os.path.exists(path):
                    # case-insensitive search
                    low = (pkg_name + '.usx').lower()
                    cand = [f for f in os.listdir(self.usx_dir) if f.lower() == low]
                    if not cand:
                        raise GeoError(f'no package {pkg_name}.usx')
                    path = os.path.join(self.usx_dir, cand[0])
                pkg = Package(path)
                while len(self.packages) >= self.MAX_PACKAGES:
                    self.packages.popitem(last=False)  # evict the oldest
                self.packages[low] = pkg
            ex = [x for x in pkg.find_exports('StaticMesh') if x.name == mesh_name]
            if not ex:
                raise GeoError(f'{pkg_name}.usx: no mesh {mesh_name}')
            res = parse_staticmesh(pkg, ex[0])
            self.meshes[key] = res
            return res
        except (GeoError, struct.error, IndexError, ValueError) as err:
            self.failed[key] = str(err)
            return None


def _xy_aabb(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _aabb_overlaps(aabb, clip):
    """clip = (x0, y0, x1, y1)."""
    return aabb[0] < clip[2] and aabb[2] > clip[0] and aabb[1] < clip[3] and aabb[3] > clip[1]


def region_mesh_triangles(unr_path, usx_dir, progress_cb=None, lib=None, pkg=None,
                          clip_xy=None, actor_classes=None):
    """All static-mesh triangles of the map in world coordinates.

    Returns (tris, skipped): tris — list of ((x,y,z)×3), skipped — count of
    actors whose meshes could not be parsed.
    clip_xy (x0,y0,x1,y1) — keep only actors whose world XY AABB overlaps
    (used when pulling overhanging meshes from a neighboring map)."""
    pkg = pkg or Package(unr_path)
    lib = lib or MeshLibrary(usx_dir)
    tris_out = []
    skipped = 0
    # Movers (doors / gates / animated fences) are omitted on purpose.
    # Official PathMaker geo leaves those doorways NSWE-open; the server
    # applies DoorData when the door is closed. Baking Mover collision
    # would seal an open gate.
    actors = _exports(pkg, actor_classes or MESH_ACTOR_CLASSES)
    for i, e in enumerate(actors):
        props = read_properties(pkg, e)
        sm = props.get('StaticMesh')
        loc = props.get('Location', (0.0, 0.0, 0.0))
        if not isinstance(sm, int) or sm >= 0:
            skipped += 1
            continue
        # actor without collision is skipped (bCollideActors/bBlockActors/bBlockPlayers)
        if (props.get('bCollideActors') is False or props.get('bBlockActors') is False
                or props.get('bBlockPlayers') is False):
            continue
        # import chain: mesh name and usx-package name
        idx = -sm - 1
        _, cname, pref, mesh_name = pkg.imports[idx]
        pkg_name = None
        for _hop in range(64):                    # cycle guard for broken packages
            if pref >= 0:
                break
            _, cname2, pref, nm = pkg.imports[-pref - 1]
            if cname2 == 'Package':
                pkg_name = nm
        if pkg_name is None:
            skipped += 1
            continue
        mesh = lib.get(pkg_name, mesh_name)
        if mesh is None:
            skipped += 1
            continue
        verts, tris = mesh
        mtx = actor_matrix(props.get('Rotation'), props.get('DrawScale'),
                           props.get('DrawScale3D'))
        pre = props.get('PrePivot')
        if pre:
            verts = [(x - pre[0], y - pre[1], z - pre[2]) for x, y, z in verts]
        if clip_xy and verts:
            lo = (min(v[0] for v in verts), min(v[1] for v in verts),
                  min(v[2] for v in verts))
            hi = (max(v[0] for v in verts), max(v[1] for v in verts),
                  max(v[2] for v in verts))
            corners = [(x, y, z)
                       for x in (lo[0], hi[0])
                       for y in (lo[1], hi[1])
                       for z in (lo[2], hi[2])]
            if not _aabb_overlaps(_xy_aabb(transform(corners, mtx, loc)), clip_xy):
                continue
        w = transform(verts, mtx, loc)
        for a, b, c in tris:
            tris_out.append((w[a], w[b], w[c]))
        if progress_cb and i % 200 == 0:
            progress_cb(i, len(actors))
    return tris_out, skipped


def brush_transform(pkg, props):
    """Brush-actor transform: (v−PrePivot)·MainScale → rotation →
    ·PostScale → +Location."""
    from .unreal import parse_scale
    pre = props.get('PrePivot') or (0.0, 0.0, 0.0)
    main = parse_scale(pkg, props.get('MainScale'))
    post = parse_scale(pkg, props.get('PostScale'))
    loc = props.get('Location') or (0.0, 0.0, 0.0)
    mtx = actor_matrix(props.get('Rotation'), None, None)
    def tf(v):
        x = (v[0] - pre[0]) * main[0]
        y = (v[1] - pre[1]) * main[1]
        z = (v[2] - pre[2]) * main[2]
        wx = x * mtx[0][0] + y * mtx[0][1] + z * mtx[0][2]
        wy = x * mtx[1][0] + y * mtx[1][1] + z * mtx[1][2]
        wz = x * mtx[2][0] + y * mtx[2][1] + z * mtx[2][2]
        return (wx * post[0] + loc[0], wy * post[1] + loc[1], wz * post[2] + loc[2])
    return tf


def volume_triangles(pkg, class_names):
    """World-space tris for brush-volume classes (BlockingVolume, …)."""
    from .unreal import parse_polys, model_polys, model_points, read_properties as rp
    blocking = []
    all_polys = []
    for pe in pkg.find_exports('Polys'):
        pl = parse_polys(pkg, pe)
        pts = {tuple(round(c, 1) for c in v) for verts, _f in pl[:3] for v in verts}
        all_polys.append((pe, pl, pts))

    def polys_for(mref):
        pe = model_polys(pkg, mref)
        if pe is not None:
            return parse_polys(pkg, pe)
        try:
            mpts = {tuple(round(c, 1) for c in v)
                    for v in model_points(pkg, pkg.exports[mref - 1])}
        except Exception:
            return []
        best, best_hits = None, 0
        for _pe, pl, pts in all_polys:
            hits = len(mpts & pts)
            if hits > best_hits:
                best, best_hits = pl, hits
        return best if best_hits >= 3 else []

    for e in _exports(pkg, class_names):
        props = rp(pkg, e)
        mref = props.get('Brush')
        if not isinstance(mref, int) or mref <= 0:
            continue
        tf = brush_transform(pkg, props)
        actor = []
        for verts, _flags in polys_for(mref):
            w = [tf(v) for v in verts]
            for i in range(1, len(w) - 1):
                actor.append((w[0], w[i], w[i + 1]))
        blocking.extend(actor)
    return blocking


def level_extra_triangles(pkg):
    """Map BSP geometry: (solid_tris, blocking_tris) in world coordinates.

    solid — the level's CSG brushes and the main BSP model (interiors);
    blocking — volume classes in BLOCKING_VOLUME_CLASSES (empty: official
    PathMaker geo does not bake BlockingVolume into NSWE)."""
    from .unreal import parse_model
    blocking = volume_triangles(pkg, BLOCKING_VOLUME_CLASSES)
    solid = []
    models = pkg.find_exports('Model')
    if models:
        main = max(models, key=lambda m: m.size)
        for tri, flags in parse_model(pkg, main):
            if bsp_face_collides(tri, flags):
                solid.append(tri)
    return solid, blocking
