"""
L2Geo Core Library
Lineage 2 Geodata Engine & Multi-Format Serialization
Supports: L2G (Lucera 2 encrypted), L2J (standard binary), PTS/L2Off (.dat / _conv.dat), JSON.

(c) fa1thDEV & L2GeoConverter Open Source Contributors
"""

import struct
import ctypes
import os
import json
from typing import List, Tuple, Dict, Any, Optional, Union

# ============================================================================
# CONSTANTS & FLAGS
# ============================================================================
BLOCKS_PER_AXIS = 256
BLOCKS_IN_MAP   = BLOCKS_PER_AXIS * BLOCKS_PER_AXIS # 65,536 blocks
CELLS_PER_BLOCK = 8
CELLS_PER_AXIS  = BLOCKS_PER_AXIS * CELLS_PER_BLOCK # 2,048 cells
REGION_SIZE     = 32768 # World units per region
CELL_SIZE       = 16    # World units per cell

BLOCK_FLAT        = 0
BLOCK_COMPLEX     = 1
BLOCK_MULTILAYER  = 2

# NSWE Movement Flags
FLAG_EAST  = 0x01 # 1
FLAG_WEST  = 0x02 # 2
FLAG_SOUTH = 0x04 # 4
FLAG_NORTH = 0x08 # 8
FLAG_ALL   = 0x0F # 15
FLAG_NONE  = 0x00 # 0

L2G_KEY_MAGIC = -2126429781 # 0x814467AB

# ============================================================================
# DATA STRUCTURES
# ============================================================================
class GeoCell:
    __slots__ = ('z', 'nswe')

    def __init__(self, z: int = 0, nswe: int = FLAG_ALL):
        self.z: int = int(z)
        self.nswe: int = int(nswe) & 0x0F

    @property
    def can_east(self) -> bool:
        return bool(self.nswe & FLAG_EAST)

    @property
    def can_west(self) -> bool:
        return bool(self.nswe & FLAG_WEST)

    @property
    def can_south(self) -> bool:
        return bool(self.nswe & FLAG_SOUTH)

    @property
    def can_north(self) -> bool:
        return bool(self.nswe & FLAG_NORTH)

    def to_dict(self) -> Dict[str, Any]:
        return {"z": self.z, "nswe": self.nswe}

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'GeoCell':
        return GeoCell(d.get("z", 0), d.get("nswe", FLAG_ALL))

    def __repr__(self) -> str:
        return f"GeoCell(z={self.z}, nswe={self.nswe})"


class GeoBlock:
    __slots__ = ('block_type', 'flat_z', 'cells')

    def __init__(self, block_type: int = BLOCK_FLAT, flat_z: int = 0):
        self.block_type: int = block_type
        self.flat_z: int = int(flat_z)
        # For COMPLEX: list of 64 GeoCell
        # For MULTILAYER: list of 64 list[GeoCell]
        self.cells: Optional[List[Any]] = None

    def get_cell_layers(self, cell_x: int, cell_y: int) -> List[GeoCell]:
        """Returns list of layers for the cell (cell_x: 0..7, cell_y: 0..7)."""
        idx = (cell_x << 3) + cell_y
        if self.block_type == BLOCK_FLAT:
            return [GeoCell(self.flat_z, FLAG_ALL)]
        elif self.block_type == BLOCK_COMPLEX:
            if not self.cells or idx >= len(self.cells):
                return [GeoCell(self.flat_z, FLAG_ALL)]
            return [self.cells[idx]]
        else: # MULTILAYER
            if not self.cells or idx >= len(self.cells):
                return [GeoCell(self.flat_z, FLAG_ALL)]
            return self.cells[idx]

    def get_height(self, cell_x: int, cell_y: int, target_z: Optional[int] = None) -> int:
        """Finds closest layer height at or below target_z (retail pathfinding logic)."""
        layers = self.get_cell_layers(cell_x, cell_y)
        if not layers:
            return self.flat_z
        if target_z is None or len(layers) == 1:
            return layers[0].z

        # In multilayer, find nearest layer
        best_z = layers[0].z
        min_diff = abs(layers[0].z - target_z)
        for layer in layers:
            diff = abs(layer.z - target_z)
            if diff < min_diff:
                min_diff = diff
                best_z = layer.z
        return best_z

    def get_nswe(self, cell_x: int, cell_y: int, target_z: Optional[int] = None) -> int:
        layers = self.get_cell_layers(cell_x, cell_y)
        if not layers:
            return FLAG_ALL
        if target_z is None or len(layers) == 1:
            return layers[0].nswe

        best_layer = layers[0]
        min_diff = abs(layers[0].z - target_z)
        for layer in layers:
            diff = abs(layer.z - target_z)
            if diff < min_diff:
                min_diff = diff
                best_layer = layer
        return best_layer.nswe

    def to_complex(self):
        """Converts FLAT block to COMPLEX block if not already."""
        if self.block_type == BLOCK_COMPLEX:
            return
        if self.block_type == BLOCK_FLAT:
            self.cells = [GeoCell(self.flat_z, FLAG_ALL) for _ in range(64)]
            self.block_type = BLOCK_COMPLEX
        elif self.block_type == BLOCK_MULTILAYER:
            # Flatten multi to first layer
            new_cells = []
            for cell_layers in self.cells:
                new_cells.append(cell_layers[0] if cell_layers else GeoCell(self.flat_z, FLAG_ALL))
            self.cells = new_cells
            self.block_type = BLOCK_COMPLEX

    def try_optimize_to_flat(self) -> bool:
        """If all 64 cells are identical with FLAG_ALL and 1 layer, converts to FLAT."""
        if self.block_type == BLOCK_FLAT:
            return True
        if self.block_type == BLOCK_COMPLEX:
            if not self.cells or len(self.cells) != 64:
                return False
            first_z = self.cells[0].z
            first_nswe = self.cells[0].nswe
            if first_nswe != FLAG_ALL:
                return False
            for c in self.cells:
                if c.z != first_z or c.nswe != FLAG_ALL:
                    return False
            self.flat_z = first_z
            self.cells = None
            self.block_type = BLOCK_FLAT
            return True
        elif self.block_type == BLOCK_MULTILAYER:
            if not self.cells or len(self.cells) != 64:
                return False
            for layers in self.cells:
                if len(layers) != 1:
                    return False
                if layers[0].nswe != FLAG_ALL:
                    return False
            first_z = self.cells[0][0].z
            for layers in self.cells:
                if layers[0].z != first_z:
                    return False
            self.flat_z = first_z
            self.cells = None
            self.block_type = BLOCK_FLAT
            return True
        return False


class GeoRegion:
    def __init__(self, region_x: int, region_y: int):
        self.region_x: int = region_x
        self.region_y: int = region_y
        # 2D array: blocks[bx][by] where 0 <= bx < 256 and 0 <= by < 256
        self.blocks: List[List[GeoBlock]] = [
            [GeoBlock(BLOCK_FLAT, 0) for _ in range(BLOCKS_PER_AXIS)]
            for _ in range(BLOCKS_PER_AXIS)
        ]

    # ------------------------------------------------------------------------
    # COORDINATE HELPERS
    # ------------------------------------------------------------------------
    @property
    def world_min_x(self) -> int:
        return (self.region_x - 20) * REGION_SIZE

    @property
    def world_max_x(self) -> int:
        return (self.region_x - 19) * REGION_SIZE

    @property
    def world_min_y(self) -> int:
        return (self.region_y - 18) * REGION_SIZE

    @property
    def world_max_y(self) -> int:
        return (self.region_y - 17) * REGION_SIZE

    def world_to_geo(self, world_x: int, world_y: int) -> Tuple[int, int]:
        gx = (world_x - self.world_min_x) >> 4
        gy = (world_y - self.world_min_y) >> 4
        return gx, gy

    def geo_to_world(self, geo_x: int, geo_y: int, z: int = 0) -> Tuple[int, int, int]:
        wx = self.world_min_x + (geo_x << 4) + 8
        wy = self.world_min_y + (geo_y << 4) + 8
        return wx, wy, z

    def get_block(self, block_x: int, block_y: int) -> GeoBlock:
        return self.blocks[block_x][block_y]

    def get_height(self, geo_x: int, geo_y: int, target_z: Optional[int] = None) -> int:
        bx = (geo_x >> 3) & 0xFF
        by = (geo_y >> 3) & 0xFF
        cx = geo_x & 7
        cy = geo_y & 7
        return self.blocks[bx][by].get_height(cx, cy, target_z)

    def get_nswe(self, geo_x: int, geo_y: int, target_z: Optional[int] = None) -> int:
        bx = (geo_x >> 3) & 0xFF
        by = (geo_y >> 3) & 0xFF
        cx = geo_x & 7
        cy = geo_y & 7
        return self.blocks[bx][by].get_nswe(cx, cy, target_z)

    # ------------------------------------------------------------------------
    # STATS & SUMMARY
    # ------------------------------------------------------------------------
    def count_blocks(self) -> Tuple[int, int, int]:
        flat = 0
        complex_ = 0
        multi = 0
        for bx in range(BLOCKS_PER_AXIS):
            for by in range(BLOCKS_PER_AXIS):
                b = self.blocks[bx][by]
                if b.block_type == BLOCK_FLAT: flat += 1
                elif b.block_type == BLOCK_COMPLEX: complex_ += 1
                elif b.block_type == BLOCK_MULTILAYER: multi += 1
        return flat, complex_, multi

    def optimize_all_blocks(self) -> int:
        """Converts redundant complex/multilayer blocks into flat blocks. Returns count optimized."""
        count = 0
        for bx in range(BLOCKS_PER_AXIS):
            for by in range(BLOCKS_PER_AXIS):
                b = self.blocks[bx][by]
                if b.block_type != BLOCK_FLAT and b.try_optimize_to_flat():
                    count += 1
        return count


# ============================================================================
# L2G ENCRYPTION / DECRYPTION ENGINE (Lucera 2 Compatible)
# ============================================================================
class L2GCodec:
    @staticmethod
    def decrypt(raw_bytes: bytes) -> bytes:
        if len(raw_bytes) < 4:
            raise ValueError("L2G buffer too short (must be >= 4 bytes)")
        key_raw = struct.unpack('<I', raw_bytes[:4])[0]
        data = bytearray(raw_bytes[4:])

        c_var7 = ctypes.c_int32(L2G_KEY_MAGIC ^ key_raw).value
        var9 = ((c_var7 >> 24) & 0xFF) ^ ((c_var7 >> 16) & 0xFF) ^ ((c_var7 >> 8) & 0xFF) ^ (c_var7 & 0xFF)
        var9 = ctypes.c_int8(var9).value

        payload = bytearray(len(data))
        check_var7 = c_var7
        for i in range(len(data)):
            b = data[i]
            dec = (b ^ var9) & 0xFF
            payload[i] = dec
            var9 = ctypes.c_int8(dec).value
            check_var7 = ctypes.c_int32(check_var7 - var9).value

        if check_var7 != 0:
            raise ValueError(f"L2G Checksum mismatch: remainder is {check_var7}, expected 0")
        return bytes(payload)

    @staticmethod
    def encrypt(payload: bytes) -> bytes:
        sum_bytes = 0
        for b in payload:
            sum_bytes = ctypes.c_int32(sum_bytes + ctypes.c_int8(b).value).value

        enc_key = ctypes.c_int32(L2G_KEY_MAGIC ^ sum_bytes).value
        initial_var7 = sum_bytes
        enc_var9 = ((initial_var7 >> 24) & 0xFF) ^ ((initial_var7 >> 16) & 0xFF) ^ ((initial_var7 >> 8) & 0xFF) ^ (initial_var7 & 0xFF)
        enc_var9 = ctypes.c_int8(enc_var9).value

        enc_data = bytearray(len(payload))
        for i in range(len(payload)):
            p = payload[i]
            enc_data[i] = (p ^ enc_var9) & 0xFF
            enc_var9 = ctypes.c_int8(p).value

        return struct.pack('<i', enc_key) + bytes(enc_data)


# ============================================================================
# SERIALIZERS & DESERIALIZERS
# ============================================================================

def parse_region_filename(filename: str) -> Tuple[int, int]:
    base = os.path.basename(filename)
    parts = base.split('.')[0].split('_')
    try:
        rx = int(parts[0])
        ry = int(parts[1])
        return rx, ry
    except Exception:
        raise ValueError(f"Cannot deduce region coordinates from filename '{filename}'. Expected format 'XX_YY.ext'.")


def load_l2j_payload(payload: bytes, region_x: int, region_y: int) -> GeoRegion:
    region = GeoRegion(region_x, region_y)
    offset = 0
    payload_len = len(payload)

    for bx in range(BLOCKS_PER_AXIS):
        for by in range(BLOCKS_PER_AXIS):
            if offset >= payload_len:
                raise ValueError(f"Truncated geodata payload at block ({bx}, {by}), offset {offset}")
            btype = payload[offset]
            offset += 1

            if btype == BLOCK_FLAT:
                if offset + 2 > payload_len:
                    raise ValueError(f"Truncated flat block at ({bx}, {by})")
                raw_z = struct.unpack('<h', payload[offset:offset+2])[0]
                offset += 2
                region.blocks[bx][by] = GeoBlock(BLOCK_FLAT, raw_z & 0xFFF0)

            elif btype == BLOCK_COMPLEX:
                if offset + 128 > payload_len:
                    raise ValueError(f"Truncated complex block at ({bx}, {by})")
                cells = []
                for _ in range(64):
                    raw_val = struct.unpack('<h', payload[offset:offset+2])[0]
                    offset += 2
                    z = (raw_val & 0xFFF0) >> 1
                    nswe = raw_val & 0x0F
                    cells.append(GeoCell(z, nswe))
                b = GeoBlock(BLOCK_COMPLEX)
                b.cells = cells
                region.blocks[bx][by] = b

            elif btype == BLOCK_MULTILAYER:
                cells = []
                for _ in range(64):
                    if offset >= payload_len:
                        raise ValueError(f"Truncated multilayer block cell count at ({bx}, {by})")
                    layer_count = payload[offset]
                    offset += 1
                    layers = []
                    for _ in range(layer_count):
                        if offset + 2 > payload_len:
                            raise ValueError(f"Truncated multilayer layer at ({bx}, {by})")
                        raw_val = struct.unpack('<h', payload[offset:offset+2])[0]
                        offset += 2
                        z = (raw_val & 0xFFF0) >> 1
                        nswe = raw_val & 0x0F
                        layers.append(GeoCell(z, nswe))
                    cells.append(layers)
                b = GeoBlock(BLOCK_MULTILAYER)
                b.cells = cells
                region.blocks[bx][by] = b
            else:
                raise ValueError(f"Invalid block type {btype} at block ({bx}, {by}), offset {offset-1}")

    return region


def build_l2j_payload(region: GeoRegion) -> bytes:
    out = bytearray()
    for bx in range(BLOCKS_PER_AXIS):
        for by in range(BLOCKS_PER_AXIS):
            b = region.blocks[bx][by]
            if b.block_type == BLOCK_FLAT:
                out.append(BLOCK_FLAT)
                z = max(-16384, min(16376, int(b.flat_z)))
                out.extend(struct.pack('<h', quant_h(z)))
            elif b.block_type == BLOCK_COMPLEX:
                out.append(BLOCK_COMPLEX)
                cells = b.cells or [GeoCell(b.flat_z, FLAG_ALL) for _ in range(64)]
                for c in cells:
                    raw_val = ((int(c.z) << 1) & 0xFFF0) | (int(c.nswe) & 0x0F)
                    out.extend(struct.pack('<H', raw_val & 0xFFFF))
            elif b.block_type == BLOCK_MULTILAYER:
                out.append(BLOCK_MULTILAYER)
                cells = b.cells or [[GeoCell(b.flat_z, FLAG_ALL)] for _ in range(64)]
                for layers in cells:
                    cnt = min(127, len(layers))
                    out.append(cnt)
                    for layer in layers[:cnt]:
                        raw_val = ((int(layer.z) << 1) & 0xFFF0) | (int(layer.nswe) & 0x0F)
                        out.extend(struct.pack('<H', raw_val & 0xFFFF))
    return bytes(out)


def load_pts_dat(filepath: str, region_x: Optional[int] = None, region_y: Optional[int] = None) -> GeoRegion:
    with open(filepath, 'rb') as f:
        header = f.read(18)
        if len(header) < 18:
            raise ValueError(f"File {filepath} is too small to be a valid PTS DAT geodata file.")
        rx, ry, unk1, unk2, total_cells, total_blocks, flat_blocks = struct.unpack('<BBHHIII', header)
        if region_x is None: region_x = rx
        if region_y is None: region_y = ry

        region = GeoRegion(region_x, region_y)
        data = f.read()

    offset = 0
    data_len = len(data)

    for bx in range(BLOCKS_PER_AXIS):
        for by in range(BLOCKS_PER_AXIS):
            if offset + 2 > data_len:
                raise ValueError(f"Truncated PTS DAT at block ({bx}, {by}), offset {offset+18}")
            btype = struct.unpack('<h', data[offset:offset+2])[0]
            offset += 2

            if btype == 0: # Flat
                if offset + 4 > data_len:
                    raise ValueError(f"Truncated PTS DAT flat block at ({bx}, {by})")
                raw_z = struct.unpack('<h', data[offset:offset+2])[0]
                offset += 4 # 2 shorts in PTS
                region.blocks[bx][by] = GeoBlock(BLOCK_FLAT, raw_z & 0xFFF0)

            elif btype == 64: # Complex
                if offset + 128 > data_len:
                    raise ValueError(f"Truncated PTS DAT complex block at ({bx}, {by})")
                cells = []
                for _ in range(64):
                    raw_val = struct.unpack('<h', data[offset:offset+2])[0]
                    offset += 2
                    z = (raw_val & 0xFFF0) >> 1
                    nswe = raw_val & 0x0F
                    cells.append(GeoCell(z, nswe))
                b = GeoBlock(BLOCK_COMPLEX)
                b.cells = cells
                region.blocks[bx][by] = b

            else: # Multilayer (> 64)
                cells = []
                for _ in range(64):
                    if offset + 2 > data_len:
                        raise ValueError(f"Truncated PTS DAT multilayer cell count at ({bx}, {by})")
                    layer_count = struct.unpack('<h', data[offset:offset+2])[0]
                    offset += 2
                    layers = []
                    for _ in range(layer_count):
                        if offset + 2 > data_len:
                            raise ValueError(f"Truncated PTS DAT multilayer layer at ({bx}, {by})")
                        raw_val = struct.unpack('<h', data[offset:offset+2])[0]
                        offset += 2
                        z = (raw_val & 0xFFF0) >> 1
                        nswe = raw_val & 0x0F
                        layers.append(GeoCell(z, nswe))
                    cells.append(layers)
                b = GeoBlock(BLOCK_MULTILAYER)
                b.cells = cells
                region.blocks[bx][by] = b

    return region


def save_pts_dat(region: GeoRegion, filepath: str):
    flat_cnt, complex_cnt, multi_cnt = region.count_blocks()
    total_cells = 0
    for bx in range(BLOCKS_PER_AXIS):
        for by in range(BLOCKS_PER_AXIS):
            b = region.blocks[bx][by]
            if b.block_type == BLOCK_FLAT:
                pass
            elif b.block_type == BLOCK_COMPLEX:
                total_cells += 64
            elif b.block_type == BLOCK_MULTILAYER:
                if b.cells:
                    for l in b.cells:
                        total_cells += len(l)

    body = bytearray()
    for bx in range(BLOCKS_PER_AXIS):
        for by in range(BLOCKS_PER_AXIS):
            b = region.blocks[bx][by]
            if b.block_type == BLOCK_FLAT:
                body.extend(struct.pack('<hhh', 0, int(b.flat_z) & 0xFFF0, int(b.flat_z) & 0xFFF0))
            elif b.block_type == BLOCK_COMPLEX:
                body.extend(struct.pack('<h', 64))
                cells = b.cells or [GeoCell(b.flat_z, FLAG_ALL) for _ in range(64)]
                for c in cells:
                    raw_val = ((int(c.z) << 1) & 0xFFF0) | (int(c.nswe) & 0x0F)
                    body.extend(struct.pack('<h', raw_val))
            elif b.block_type == BLOCK_MULTILAYER:
                cells = b.cells or [[GeoCell(b.flat_z, FLAG_ALL)] for _ in range(64)]
                extra_layers = sum(len(l) for l in cells)
                btype = 64 + extra_layers
                body.extend(struct.pack('<h', btype))
                for layers in cells:
                    cnt = min(127, len(layers))
                    body.extend(struct.pack('<h', cnt))
                    for layer in layers[:cnt]:
                        raw_val = ((int(layer.z) << 1) & 0xFFF0) | (int(layer.nswe) & 0x0F)
                        body.extend(struct.pack('<h', raw_val))

    header = struct.pack(
        '<BBHHIII',
        int(region.region_x),
        int(region.region_y),
        128, 16,
        total_cells,
        BLOCKS_IN_MAP,
        flat_cnt
    )

    with open(filepath, 'wb') as f:
        f.write(header)
        f.write(body)


def load_geodata(filepath: str, region_x: Optional[int] = None, region_y: Optional[int] = None) -> GeoRegion:
    """Universal geodata loader: auto-detects L2G, L2J, PTS .DAT, or JSON."""
    if region_x is None or region_y is None:
        try:
            rx, ry = parse_region_filename(filepath)
            if region_x is None: region_x = rx
            if region_y is None: region_y = ry
        except Exception:
            if region_x is None: region_x = 20
            if region_y is None: region_y = 20

    ext = os.path.splitext(filepath)[1].lower()

    if ext == '.l2g':
        with open(filepath, 'rb') as f:
            raw = f.read()
        payload = L2GCodec.decrypt(raw)
        return load_l2j_payload(payload, region_x, region_y)

    elif ext == '.l2j':
        with open(filepath, 'rb') as f:
            payload = f.read()
        return load_l2j_payload(payload, region_x, region_y)

    elif ext == '.json':
        with open(filepath, 'r', encoding='utf-8') as f:
            d = json.load(f)
        return region_from_dict(d)

    elif ext in ('.dat', '.geo'):
        # Check if PTS 18-byte header or raw L2J format
        with open(filepath, 'rb') as f:
            head = f.read(18)
        if len(head) >= 18:
            rx, ry, unk1, unk2 = struct.unpack('<BBHH', head[:6])
            if unk1 == 128 and unk2 == 16:
                return load_pts_dat(filepath, region_x, region_y)
        # Fallback to L2J raw
        with open(filepath, 'rb') as f:
            payload = f.read()
        return load_l2j_payload(payload, region_x, region_y)

    else:
        # Default try L2J
        with open(filepath, 'rb') as f:
            payload = f.read()
        return load_l2j_payload(payload, region_x, region_y)


def save_geodata(region: GeoRegion, filepath: str, out_format: Optional[str] = None):
    """Universal geodata saver: format can be 'l2g', 'l2j', 'dat' (PTS), or 'json'."""
    if out_format is None:
        ext = os.path.splitext(filepath)[1].lower()
        if ext == '.l2g': out_format = 'l2g'
        elif ext == '.l2j': out_format = 'l2j'
        elif ext in ('.dat', '.geo'): out_format = 'dat'
        elif ext == '.json': out_format = 'json'
        else: out_format = 'l2j'

    out_format = out_format.lower().strip('.')

    if out_format == 'l2g':
        payload = build_l2j_payload(region)
        encrypted = L2GCodec.encrypt(payload)
        with open(filepath, 'wb') as f:
            f.write(encrypted)

    elif out_format == 'l2j':
        payload = build_l2j_payload(region)
        with open(filepath, 'wb') as f:
            f.write(payload)

    elif out_format in ('dat', 'pts'):
        save_pts_dat(region, filepath)

    elif out_format == 'json':
        d = region_to_dict(region)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(d, f, indent=2)

    else:
        raise ValueError(f"Unknown output format '{out_format}'. Supported: l2g, l2j, dat, json.")


# ----------------------------------------------------------------------------
# JSON SERIALIZATION / EXPORT
# ----------------------------------------------------------------------------
def region_to_dict(region: GeoRegion, include_blocks: bool = True) -> Dict[str, Any]:
    flat, complex_, multi = region.count_blocks()
    d = {
        "region_x": region.region_x,
        "region_y": region.region_y,
        "world_bounds": {
            "min_x": region.world_min_x,
            "max_x": region.world_max_x,
            "min_y": region.world_min_y,
            "max_y": region.world_max_y
        },
        "stats": {
            "flat_blocks": flat,
            "complex_blocks": complex_,
            "multilayer_blocks": multi,
            "total_blocks": BLOCKS_IN_MAP
        }
    }
    if include_blocks:
        blocks_data = []
        for bx in range(BLOCKS_PER_AXIS):
            for by in range(BLOCKS_PER_AXIS):
                b = region.blocks[bx][by]
                if b.block_type == BLOCK_FLAT:
                    blocks_data.append({"bx": bx, "by": by, "t": 0, "z": b.flat_z})
                elif b.block_type == BLOCK_COMPLEX:
                    c_list = [c.to_dict() for c in b.cells]
                    blocks_data.append({"bx": bx, "by": by, "t": 1, "cells": c_list})
                elif b.block_type == BLOCK_MULTILAYER:
                    m_list = [[layer.to_dict() for layer in c] for c in b.cells]
                    blocks_data.append({"bx": bx, "by": by, "t": 2, "layers": m_list})
        d["blocks"] = blocks_data
    return d


def region_from_dict(d: Dict[str, Any]) -> GeoRegion:
    rx = d.get("region_x", 20)
    ry = d.get("region_y", 20)
    region = GeoRegion(rx, ry)
    blocks_data = d.get("blocks", [])

    for bdata in blocks_data:
        bx = bdata["bx"]
        by = bdata["by"]
        t = bdata["t"]
        if t == BLOCK_FLAT:
            region.blocks[bx][by] = GeoBlock(BLOCK_FLAT, bdata["z"])
        elif t == BLOCK_COMPLEX:
            b = GeoBlock(BLOCK_COMPLEX)
            b.cells = [GeoCell.from_dict(c) for c in bdata["cells"]]
            region.blocks[bx][by] = b
        elif t == BLOCK_MULTILAYER:
            b = GeoBlock(BLOCK_MULTILAYER)
            b.cells = [[GeoCell.from_dict(layer) for layer in cell_layers] for cell_layers in bdata["layers"]]
            region.blocks[bx][by] = b
    return region
