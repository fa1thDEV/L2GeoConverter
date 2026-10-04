#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reading Unreal Engine 2 packages from the Lineage 2 client.

Decrypts the Lineage2VerNNN wrapper (111: XOR 0xAC; 121: XOR from the filename),
parses the package header, name/import/export tables, and object properties.
Enough for TerrainInfo/Texture/StaticMesh — a full UObject is not needed.
"""

import os
import struct

from .formats import GeoError


# ─────────────────────────── decryption ───────────────────────────

_XOR_TABLES = {}


def _xor_table(key):
    """Translation table b → b^key (cached by key)."""
    t = _XOR_TABLES.get(key)
    if t is None:
        t = bytes(i ^ key for i in range(256))
        _XOR_TABLES[key] = t
    return t


def decrypt(path):
    """Client file → decrypted UE2 package bytes."""
    raw = open(path, 'rb').read()
    if raw[:2] != b'L\x00':                      # no wrapper — already a raw package
        return raw
    header = raw[:28].decode('utf-16-le', 'ignore')
    if not header.startswith('Lineage2Ver'):
        return raw
    ver = header[11:14]
    body = raw[28:]
    if ver == '111':
        key = 0xAC
    elif ver == '121':
        # key — low byte of the sum of filename character codes (lowercase)
        key = sum(ord(c) for c in os.path.basename(path).lower()) & 0xFF
    else:
        raise GeoError(f'{os.path.basename(path)}: Ver{ver} encryption is not supported')
    # XOR the entire body with a constant key — via a translation table (C-speed,
    # ×100 vs a per-byte generator; the result is identical)
    data = body.translate(_xor_table(key))
    if data[:4] != b'\xc1\x83\x2a\x9e':
        raise GeoError(f'{os.path.basename(path)}: no UE package signature after decryption')
    return data


# ─────────────────────────── primitives ───────────────────────────

class Reader:
    __slots__ = ('d', 'p')

    def __init__(self, data, pos=0):
        self.d = data
        self.p = pos

    def u8(self):
        v = self.d[self.p]; self.p += 1
        return v

    def u16(self):
        v = struct.unpack_from('<H', self.d, self.p)[0]; self.p += 2
        return v

    def i32(self):
        v = struct.unpack_from('<i', self.d, self.p)[0]; self.p += 4
        return v

    def u32(self):
        v = struct.unpack_from('<I', self.d, self.p)[0]; self.p += 4
        return v

    def f32(self):
        v = struct.unpack_from('<f', self.d, self.p)[0]; self.p += 4
        return v

    def read(self, n):
        v = self.d[self.p:self.p + n]; self.p += n
        return v

    def ci(self):
        """FCompactIndex — signed variable-length integer."""
        b = self.u8()
        neg = b & 0x80
        v = b & 0x3F
        if b & 0x40:
            shift = 6
            while True:
                b = self.u8()
                v |= (b & 0x7F) << shift
                if not (b & 0x80):
                    break
                shift += 7
        return -v if neg else v

    def fstring(self):
        """FString: compact-index length (including NUL), then bytes."""
        n = self.ci()
        if n == 0:
            return ''
        if n > 0:
            s = self.read(n)
            return s[:-1].decode('latin-1', 'replace')
        s = self.read(-n * 2)                     # UTF-16
        return s[:-2].decode('utf-16-le', 'replace')


# ─────────────────────────── package ───────────────────────────

class Export:
    __slots__ = ('cls', 'super', 'group', 'name', 'flags', 'size', 'offset')


class Package:
    """UE2 package: names, imports, exports, access to object data."""

    def __init__(self, path):
        self.path = path
        self.data = decrypt(path)
        r = Reader(self.data)
        if r.u32() != 0x9E2A83C1:
            raise GeoError(f'{os.path.basename(path)}: not a UE package')
        self.version = r.u16()
        self.licensee = r.u16()
        r.u32()                                   # PackageFlags
        name_n, name_off = r.i32(), r.i32()
        exp_n, exp_off = r.i32(), r.i32()
        imp_n, imp_off = r.i32(), r.i32()

        r = Reader(self.data, name_off)
        self.names = []
        for _ in range(name_n):
            s = r.fstring()
            r.u32()                               # flags
            self.names.append(s)

        r = Reader(self.data, imp_off)
        self.imports = []                         # (class_package, class_name, package_ref, name)
        for _ in range(imp_n):
            cpkg = self.names[r.ci()]
            cname = self.names[r.ci()]
            pref = r.i32()
            nm = self.names[r.ci()]
            self.imports.append((cpkg, cname, pref, nm))

        r = Reader(self.data, exp_off)
        self.exports = []
        for _ in range(exp_n):
            e = Export()
            e.cls = r.ci()
            e.super = r.ci()
            e.group = r.i32()
            e.name = self.names[r.ci()]
            e.flags = r.u32()
            e.size = r.ci()
            e.offset = r.ci() if e.size > 0 else 0
            self.exports.append(e)

    def obj_name(self, ref):
        """Name from an object reference: >0 export, <0 import, 0 — None."""
        if ref > 0:
            return self.exports[ref - 1].name
        if ref < 0:
            return self.imports[-ref - 1][3]
        return None

    def import_package(self, ref):
        """Name of the top-level Package in the object-reference import chain (or None).
        For a heightmap texture this yields the utx package that actually holds the data —
        a map may reference a heightmap from another/main region."""
        if not isinstance(ref, int) or ref >= 0:
            return None
        idx = -ref - 1
        last_pkg = None
        seen = 0
        while 0 <= idx < len(self.imports) and seen < 64:
            _cpkg, cname, pref, nm = self.imports[idx]
            if cname == 'Package':
                last_pkg = nm                     # top file-package (last in the chain)
            if pref >= 0:
                break
            idx = -pref - 1
            seen += 1
        return last_pkg

    def class_name(self, e):
        return self.obj_name(e.cls) or 'Class'

    def find_exports(self, class_name):
        return [e for e in self.exports if self.class_name(e) == class_name]

    def reader(self, e):
        return Reader(self.data, e.offset)


# ─────────────────────────── object properties ───────────────────────────

RF_HAS_STACK = 0x02000000

# sizes from the SizeType field in the info byte
_PROP_SIZES = {0: 1, 1: 2, 2: 4, 3: 12, 4: 16}


def _read_prop_list(pkg, r):
    """Nested property list (element of a DynamicArray struct)."""
    out = {}
    while True:
        name = pkg.names[r.ci()]
        if name == 'None':
            return out
        info = r.u8()
        ptype = info & 0x0F
        size_bits = (info >> 4) & 0x07
        is_array = bool(info & 0x80)
        struct_name = None
        if ptype == 0x0A:
            struct_name = pkg.names[r.ci()]
        if size_bits in _PROP_SIZES:
            size = _PROP_SIZES[size_bits]
        elif size_bits == 5:
            size = r.u8()
        elif size_bits == 6:
            size = r.u16()
        else:
            size = r.u32()
        if ptype == 3:
            out[name] = is_array
            continue
        if is_array:
            idx = r.u8()
            if idx & 0x80:
                r.u8() if not (idx & 0x40) else r.read(3)
        start = r.p
        if ptype == 5:
            out[name] = r.ci()
        elif ptype == 1:
            out[name] = r.u8()
        elif ptype == 2:
            out[name] = r.i32()
        elif ptype == 4:
            out[name] = r.f32()
        elif ptype == 0x0A and struct_name == 'Vector':
            out[name] = (r.f32(), r.f32(), r.f32())
            r.p = start + size
        else:
            r.read(size)
            continue
        r.p = max(r.p, start + size) if ptype != 5 else r.p
    return out


def read_properties(pkg, e):
    """Export object properties → dict name → value (or a list for arrays).

    Understands the types needed for TerrainInfo/Texture/Actor: byte, int, bool,
    float, object, name, struct (Vector/Rotator raw bytes → tuple),
    fixed-size arrays. Unknown types are skipped by size.
    """
    r = pkg.reader(e)
    if e.flags & RF_HAS_STACK:
        r.ci(); r.ci()                            # StateFrame: node, stateNode
        r.read(8)                                 # probe mask
        r.i32()                                   # latent action
        r.ci()                                    # offset in the script (node != None)
    props = {}
    while True:
        name = pkg.names[r.ci()]
        if name == 'None':
            break
        info = r.u8()
        ptype = info & 0x0F
        size_bits = (info >> 4) & 0x07
        is_array = bool(info & 0x80)
        struct_name = None
        if ptype == 0x0A:
            struct_name = pkg.names[r.ci()]
        if size_bits in _PROP_SIZES:
            size = _PROP_SIZES[size_bits]
        elif size_bits == 5:
            size = r.u8()
        elif size_bits == 6:
            size = r.u16()
        else:
            size = r.u32()
        if ptype == 3:                            # bool: value lives in the array bit
            val = is_array
            props.setdefault(name, val)
            continue
        idx = 0
        if is_array:
            idx = r.u8()
            if idx & 0x80:
                if idx & 0x40:
                    idx = ((idx & 0x3F) << 24) | (r.u8() << 16) | (r.u8() << 8) | r.u8()
                else:
                    idx = ((idx & 0x7F) << 8) | r.u8()
        start = r.p
        if ptype == 1:
            val = r.u8()
        elif ptype == 2:
            val = r.i32()
        elif ptype == 4:
            val = r.f32()
        elif ptype in (5, 6):                     # object / name
            ref = r.ci()
            val = pkg.obj_name(ref) if ptype == 6 or ptype == 5 else ref
            if ptype == 5:
                val = ref                          # object reference as a number
        elif ptype == 0x0A and struct_name in ('Vector', 'Rotator'):
            if struct_name == 'Vector':
                val = (r.f32(), r.f32(), r.f32())
            else:
                val = (r.i32(), r.i32(), r.i32())
        elif ptype == 9 and name == 'Materials':
            # DynamicArray of structs: CI count + nested property lists
            end_pos = r.p + size
            n_el = r.ci()
            val = []
            try:
                for _ in range(n_el):
                    val.append(_read_prop_list(pkg, r))
            except (IndexError, KeyError):
                val = []
            r.p = end_pos
        else:
            val = r.read(size)                    # raw
        r.p = max(r.p, start + size) if ptype not in (5, 6) else r.p
        if is_array or idx or (name in props):
            cur = props.get(name)
            if not isinstance(cur, dict):
                props[name] = {} if cur is None else {0: cur}
            props[name][idx] = val
        else:
            props[name] = val
    props['__end__'] = r.p                        # position after properties (for the object body)
    return props


# ─────────────────────────── UModel (BSP) ───────────────────────────

PF_NOTSOLID = 0x08
PF_PORTAL = 0x04000000
PF_INVISIBLE = 0x01


def parse_model(pkg, e):
    """Model (BSP) export → [( (x,y,z)×3, poly_flags ), ...].

    UE2/L2-133 format: Primitive(box+sphere), vectors, points,
    nodes (fields with compact-indexes!), surfs
    [CI material][u32 flags][CI×6: pBase,vNormal,vTexU,vTexV,iBrushPoly,actor]
    [plane 16B][tail 8B], verts (CI pairs). The surf layout was derived
    by a brute-force solver and confirmed on all large models of client 286.
    """
    props = read_properties(pkg, e)
    r = Reader(pkg.data, props['__end__'])
    r.read(25)                                    # FBox + valid
    r.read(16)                                    # FSphere
    n = r.ci()                                    # vectors
    r.read(12 * n)
    n = r.ci()                                    # points
    points = list(struct.iter_unpack('<fff', r.read(12 * n)))
    n_nodes = r.ci()
    nodes = []
    for _ in range(n_nodes):
        r.read(25)                                # plane + zone_mask + flags
        vpool = r.ci()
        surf = r.ci()
        r.ci(); r.ci(); r.ci(); r.ci(); r.ci()    # back/front/plane/collision/render
        r.read(12)                                # point
        r.i32()                                   # id
        r.read(16)                                # connectivity + visibility
        r.ci(); r.ci()                            # zones
        vcount = r.u8()
        r.read(8)                                 # leaves
        r.read(12)                                # 3 pointers
        nodes.append((vpool, surf, vcount))
    n_surfs = r.ci()
    surf_flags = []
    for _ in range(n_surfs):
        r.ci()                                    # material
        flags = r.u32()
        for _ in range(6):                        # pBase, vNormal, vTexU, vTexV, iBrushPoly, actor
            r.ci()
        r.read(16)                                # plane
        r.read(8)                                 # LightMapScale + auxiliary
        surf_flags.append(flags)
    n_verts = r.ci()
    verts = []
    for _ in range(n_verts):
        verts.append(r.ci())                      # point index
        r.ci()                                    # side index
    tris = []
    for vpool, surf, vcount in nodes:
        if vcount < 3 or not (0 <= surf < n_surfs):
            continue
        flags = surf_flags[surf]
        try:
            pts = [points[verts[vpool + i]] for i in range(vcount)]
        except IndexError:
            continue
        for i in range(1, vcount - 1):
            tris.append(((pts[0], pts[i], pts[i + 1]), flags))
    return tris


def parse_scale(pkg, raw):
    """Scale property: nested property list {Scale=Vector, SheerRate…}."""
    if isinstance(raw, tuple) and len(raw) == 3:
        return raw
    if isinstance(raw, (bytes, bytearray)) and raw:
        try:
            d = _read_prop_list(pkg, Reader(bytes(raw)))
            v = d.get('Scale')
            if isinstance(v, tuple) and len(v) == 3:
                return v
        except (IndexError, KeyError, struct.error):
            pass
    return (1.0, 1.0, 1.0)


def parse_polys(pkg, e):
    """Polys export → [(vertices [(x,y,z)...], poly_flags), ...] (local)."""
    props = read_properties(pkg, e)
    r = Reader(pkg.data, props['__end__'])
    num = r.i32()
    r.i32()                                       # max
    out = []
    obj_end = e.offset + e.size
    for _ in range(num):
        if r.p >= obj_end:
            break
        nv = r.ci()
        if not (3 <= nv <= 64):
            break
        r.read(48)                                # Base, Normal, TextureU, TextureV
        verts = [struct.unpack_from('<fff', pkg.data, r.p + i * 12) for i in range(nv)]
        r.read(12 * nv)
        flags = r.u32()
        for _ in range(5):                        # actor, texture, item, ilink, ibrushpoly
            r.ci()
        r.read(8)                                 # pan U/V + licensee field
        out.append((verts, flags))
    return out


def model_points(pkg, e, limit=16):
    """First geometry points of a Model (for matching against Polys)."""
    props = read_properties(pkg, e)
    r = Reader(pkg.data, props['__end__'])
    r.read(25); r.read(16)
    n = r.ci(); r.read(12 * n)                    # vectors
    n = r.ci()
    pts = []
    for i in range(min(n, limit)):
        pts.append(struct.unpack_from('<fff', pkg.data, r.p + i * 12))
    return pts


def model_polys(pkg, model_ref):
    """Polys belonging to a Model: neighboring Polys-class export (window ±4),
    then search by group."""
    if not (0 < model_ref <= len(pkg.exports)):
        return None
    n = len(pkg.exports)
    for delta in (0, 1, -1, 2, -2, 3, -3, 4, -4):
        i = model_ref - 1 + delta
        if 0 <= i < n:
            pe = pkg.exports[i]
            if pe.name.startswith('Polys') and pkg.class_name(pe) == 'Polys':
                return pe
    for pe in pkg.exports:
        if pe.group == model_ref and pe.name.startswith('Polys'):
            return pe
    return None
