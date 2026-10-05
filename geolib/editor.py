#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Geodata Editor Engine (adapted from HD GeoEditor DRiN's edition & l2mapconv).

Provides batch and cell-level editing operations:
  - Shift Z: Adjusts elevations with range safety and layer filtering.
  - Shift XY: Translates region blocks in 2D with boundary clamping and void filling.
  - Delete Z-Range: Removes unwanted multi-layer slabs (e.g. roofs, void ceilings) within [min_z, max_z].
  - Recalculate Slope (Z-Wizard): Sets directional passage flags based on slope climb threshold.
  - L2 Live Memory Scanner: Connects to L2.bin process to read real-time player coordinates.
"""

import copy
import math
import os
import struct
from typing import Any, Dict, List, Optional, Tuple, Union

from .formats import (
    BLOCKS, GeoError, dec_h, dec_nswe, enc_cell, parse_region, quant_h,
    region_of, sniff_format, L2GCodec, pack_pts_header, pts_flat_surface
)
from .convert import l2j2pts_bytes

# Movement direction bitmasks (Lineage 2 standard)
FLAG_EAST  = 0x01
FLAG_WEST  = 0x02
FLAG_SOUTH = 0x04
FLAG_NORTH = 0x08
FLAG_ALL   = 0x0F
FLAG_NONE  = 0x00

BLOCKS_PER_AXIS = 256
CELLS_PER_BLOCK = 8
CELLS_PER_AXIS = BLOCKS_PER_AXIS * CELLS_PER_BLOCK  # 2048


# =========================================================================
# 1. SHIFT Z OPERATION (Elevation adjustment)
# =========================================================================

def shift_z_blocks(
    blocks: List[Any],
    delta_z: int,
    layer_mode: str = "all",
    target_layer_idx: int = 0
) -> int:
    """Adds delta_z to cell elevations in blocks list in-place.
    
    Args:
        blocks: List of 65,536 blocks, each containing 64 cells with [(h, nswe), ...].
        delta_z: Height delta in world units.
        layer_mode: 'all' to shift all layers, or 'specific' for target_layer_idx.
        target_layer_idx: 0-based layer index if layer_mode == 'specific'.
        
    Returns:
        Number of modified layers.
    """
    if delta_z == 0:
        return 0
    
    modified_count = 0
    
    for b_idx in range(len(blocks)):
        block = blocks[b_idx]
        
        # Ensure deep mutable copy if block is flat singleton
        if len(block) == 64 and id(block[0]) == id(block[1]):
            block = [[(l[0], l[1]) for l in cell] for cell in block]
            blocks[b_idx] = block
            
        for c_idx in range(len(block)):
            cell = block[c_idx]
            new_layers = []
            
            for l_idx, (h, nswe) in enumerate(cell):
                if layer_mode == "all" or l_idx == target_layer_idx:
                    new_h = quant_h(h + delta_z)
                    new_layers.append((new_h, nswe))
                    modified_count += 1
                else:
                    new_layers.append((h, nswe))
                    
            block[c_idx] = new_layers
            
    return modified_count


# =========================================================================
# 2. SHIFT XY OPERATION (Horizontal coordinate translation)
# =========================================================================

def shift_xy_blocks(
    blocks: List[Any],
    delta_bx: int,
    delta_by: int,
    void_z: int = 0
) -> Dict[str, int]:
    """Translates the 256x256 block matrix by (delta_bx, delta_by).
    
    Args:
        blocks: List of 65,536 blocks (each 64 cells).
        delta_bx: Blocks to shift in X (-255 to 255).
        delta_by: Blocks to shift in Y (-255 to 255).
        void_z: Height for newly exposed void blocks (default 0).
        
    Returns:
        Dict with shifted_count and void_filled_count.
    """
    if delta_bx == 0 and delta_by == 0:
        return {"shifted_blocks": len(blocks), "void_filled": 0}
        
    # Default void flat block: all 64 cells single layer at void_z with NSWE=0
    void_block = [[(quant_h(void_z), FLAG_NONE)] for _ in range(64)]
    
    new_blocks = [void_block for _ in range(BLOCKS)]
    shifted_count = 0
    void_count = 0
    
    for bx in range(BLOCKS_PER_AXIS):
        src_bx = bx - delta_bx
        for by in range(BLOCKS_PER_AXIS):
            src_by = by - delta_by
            target_idx = (bx << 8) | by
            
            if 0 <= src_bx < BLOCKS_PER_AXIS and 0 <= src_by < BLOCKS_PER_AXIS:
                src_idx = (src_bx << 8) | src_by
                new_blocks[target_idx] = blocks[src_idx]
                shifted_count += 1
            else:
                void_count += 1
                
    # Copy back to input blocks in-place
    blocks[:] = new_blocks
    
    return {
        "shifted_blocks": shifted_count,
        "void_filled": void_count
    }


# =========================================================================
# 3. DELETE Z-RANGE OPERATION (Layer pruning / Void cleanup)
# =========================================================================

def delete_z_range_blocks(
    blocks: List[Any],
    min_z: int,
    max_z: int,
    layer_mode: str = "all",
    target_layer_idx: int = 0,
    keep_at_least_one: bool = True
) -> Dict[str, int]:
    """Deletes layers whose elevation falls within [min_z, max_z].
    
    Args:
        blocks: List of 65,536 blocks.
        min_z: Lower boundary (inclusive).
        max_z: Upper boundary (inclusive).
        layer_mode: 'all' or 'specific'.
        target_layer_idx: Layer index if layer_mode == 'specific'.
        keep_at_least_one: If True, prevents emptying a cell completely (preserves lowest).
        
    Returns:
        Dict with deleted_layers, touched_cells, converted_blocks.
    """
    if min_z > max_z:
        min_z, max_z = max_z, min_z
        
    deleted_layers = 0
    touched_cells = 0
    converted_blocks = 0
    
    for b_idx in range(len(blocks)):
        block = blocks[b_idx]
        block_modified = False
        
        # Check if block has any cells in range
        has_any = False
        for cell in block:
            for h, _ in cell:
                if min_z <= h <= max_z:
                    has_any = True
                    break
            if has_any:
                break
                
        if not has_any:
            continue
            
        # Ensure block is mutable copy
        if len(block) == 64 and id(block[0]) == id(block[1]):
            block = [[(l[0], l[1]) for l in cell] for cell in block]
            blocks[b_idx] = block
            
        for c_idx in range(len(block)):
            cell = block[c_idx]
            retained = []
            removed_here = 0
            
            for l_idx, (h, nswe) in enumerate(cell):
                matches = (min_z <= h <= max_z)
                if layer_mode == "specific" and l_idx != target_layer_idx:
                    matches = False
                    
                if matches:
                    removed_here += 1
                else:
                    retained.append((h, nswe))
                    
            if removed_here > 0:
                block_modified = True
                touched_cells += 1
                deleted_layers += removed_here
                
                if not retained and keep_at_least_one:
                    # Keep the lowest layer with flags set to NONE
                    lowest = min(cell, key=lambda x: x[0])
                    retained = [(lowest[0], FLAG_NONE)]
                    
                block[c_idx] = retained
                
        if block_modified:
            converted_blocks += 1
            
    return {
        "deleted_layers": deleted_layers,
        "touched_cells": touched_cells,
        "converted_blocks": converted_blocks
    }


# =========================================================================
# 4. RECALCULATE SLOPE FLAGS (Z-Wizard algorithm)
# =========================================================================

def recalculate_slope_flags(
    blocks: List[Any],
    max_climb_z: int = 24
) -> Dict[str, int]:
    """Recalculates NSWE directional borders based on elevation differences.
    
    If the height delta between cell A and neighboring cell B in direction D
    exceeds max_climb_z, the passage flag is cleared in both directions.
    
    Returns:
        Dict with sealed_passages, checked_boundaries.
    """
    sealed_passages = 0
    checked_boundaries = 0
    
    # Helper to get/set layers
    def get_cell(gx: int, gy: int) -> List[Tuple[int, int]]:
        bx = gx >> 3
        by = gy >> 3
        cx = gx & 7
        cy = gy & 7
        return blocks[(bx << 8) | by][(cx << 3) | cy]
        
    def set_cell(gx: int, gy: int, new_layers: List[Tuple[int, int]]):
        bx = gx >> 3
        by = gy >> 3
        cx = gx & 7
        cy = gy & 7
        b_idx = (bx << 8) | by
        c_idx = (cx << 3) | cy
        blk = blocks[b_idx]
        if len(blk) == 64 and id(blk[0]) == id(blk[1]):
            blocks[b_idx] = [[(l[0], l[1]) for l in cell] for cell in blk]
        blocks[b_idx][c_idx] = new_layers

    # Check horizontal (East-West)
    for gx in range(CELLS_PER_AXIS - 1):
        for gy in range(CELLS_PER_AXIS):
            checked_boundaries += 1
            layers_a = get_cell(gx, gy)
            layers_b = get_cell(gx + 1, gy)
            
            # Simple single-layer match
            if len(layers_a) == 1 and len(layers_b) == 1:
                ha, nswe_a = layers_a[0]
                hb, nswe_b = layers_b[0]
                
                if abs(ha - hb) > max_climb_z:
                    new_a = nswe_a & ~FLAG_EAST
                    new_b = nswe_b & ~FLAG_WEST
                    if new_a != nswe_a or new_b != nswe_b:
                        sealed_passages += 1
                        set_cell(gx, gy, [(ha, new_a)])
                        set_cell(gx + 1, gy, [(hb, new_b)])

    # Check vertical (South-North)
    for gx in range(CELLS_PER_AXIS):
        for gy in range(CELLS_PER_AXIS - 1):
            checked_boundaries += 1
            layers_a = get_cell(gx, gy)
            layers_b = get_cell(gx, gy + 1)
            
            if len(layers_a) == 1 and len(layers_b) == 1:
                ha, nswe_a = layers_a[0]
                hb, nswe_b = layers_b[0]
                
                if abs(ha - hb) > max_climb_z:
                    new_a = nswe_a & ~FLAG_SOUTH
                    new_b = nswe_b & ~FLAG_NORTH
                    if new_a != nswe_a or new_b != nswe_b:
                        sealed_passages += 1
                        set_cell(gx, gy, [(ha, new_a)])
                        set_cell(gx, gy + 1, [(hb, new_b)])

    return {
        "sealed_passages": sealed_passages,
        "checked_boundaries": checked_boundaries
    }


# =========================================================================
# 5. SERIALIZATION & FILE EXPORT
# =========================================================================

def encode_blocks_to_l2j(blocks: List[Any]) -> bytes:
    """Encodes blocks list to standard L2J binary geodata."""
    out = bytearray()
    for blk in blocks:
        # Check if flat
        is_flat = True
        first_h = blk[0][0][0]
        for cell in blk:
            if len(cell) != 1 or cell[0][1] != FLAG_ALL or cell[0][0] != first_h:
                is_flat = False
                break
                
        if is_flat:
            out.append(0)
            out.extend(struct.pack('<h', quant_h(first_h)))
        else:
            is_multi = any(len(c) > 1 for c in blk)
            if not is_multi:
                out.append(1)
                for c in blk:
                    h, nswe = c[0]
                    out.extend(struct.pack('<H', enc_cell(h, nswe)))
            else:
                out.append(2)
                for c in blk:
                    nl = min(125, len(c))
                    out.append(nl)
                    for h, nswe in c[:nl]:
                        out.extend(struct.pack('<H', enc_cell(h, nswe)))
                        
    return bytes(out)


def save_edited_region(
    blocks: List[Any],
    output_path: str,
    target_format: str = "l2j",
    rx: int = 20,
    ry: int = 18
) -> str:
    """Saves modified blocks to target format (.l2j, .l2g, or _conv.dat)."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    l2j_bytes = encode_blocks_to_l2j(blocks)
    
    fmt = target_format.lower()
    if fmt == "l2j":
        with open(output_path, "wb") as f:
            f.write(l2j_bytes)
    elif fmt == "l2g":
        encoded = L2GCodec.encode(l2j_bytes)
        with open(output_path, "wb") as f:
            f.write(encoded)
    elif fmt in ("pts", "conv.dat", "dat"):
        pts_data = l2j2pts_bytes(l2j_bytes, rx=rx, ry=ry)[0]
        with open(output_path, "wb") as f:
            f.write(pts_data)
    else:
        raise GeoError(f"Unsupported export format: {target_format}")
        
    return output_path


# =========================================================================
# 6. LIVE CLIENT MEMORY SCANNER (HD GeoEditor Scanner)
# =========================================================================

class L2ClientMemoryScanner:
    """Attaches to running Lineage II process and reads real-time coordinates.
    
    Reads player world position (X, Y, Z) and maps to region (rx, ry),
    block (bx, by), and cell (cx, cy) coordinates.
    """
    
    def __init__(self, stat_offset: int = 0x0012F0F8, var_pointer: int = 0x0012BFC8, var_offset: int = 0x1B0):
        self.stat_offset = stat_offset
        self.var_pointer = var_pointer
        self.var_offset = var_offset
        self.h_process = None
        self.pid = None
        self.base_address = 0
        
    def find_and_attach(self) -> bool:
        """Finds Lineage II (L2.bin) window/process and opens a read handle."""
        import sys
        if sys.platform != "win32":
            return False
            
        import ctypes
        from ctypes import wintypes
        
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        # Find window
        hwnd = user32.FindWindowA(None, b"Lineage II")
        if not hwnd:
            hwnd = user32.FindWindowA(b"LineageTwoClnt", None)
            
        if not hwnd:
            return False
            
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return False
            
        PROCESS_VM_READ = 0x0010
        PROCESS_QUERY_INFORMATION = 0x0400
        handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid.value)
        if not handle:
            return False
            
        self.h_process = handle
        self.pid = pid.value
        return True
        
    def read_player_coords(self, use_stat: bool = False) -> Optional[Tuple[float, float, float]]:
        """Reads world coordinates (x, y, z) from process memory."""
        if not self.h_process:
            if not self.find_and_attach():
                return None
                
        import ctypes
        kernel32 = ctypes.windll.kernel32
        
        if use_stat:
            buf = (ctypes.c_float * 3)()
            bytes_read = ctypes.c_size_t()
            success = kernel32.ReadProcessMemory(
                self.h_process, ctypes.c_void_p(self.stat_offset),
                ctypes.byref(buf), 12, ctypes.byref(bytes_read)
            )
            if success and bytes_read.value == 12:
                return (buf[0], buf[1], buf[2])
        else:
            ptr = ctypes.c_uint32()
            bytes_read = ctypes.c_size_t()
            success = kernel32.ReadProcessMemory(
                self.h_process, ctypes.c_void_p(self.var_pointer),
                ctypes.byref(ptr), 4, ctypes.byref(bytes_read)
            )
            if success and ptr.value:
                target_addr = ptr.value + self.var_offset
                buf = (ctypes.c_float * 3)()
                success2 = kernel32.ReadProcessMemory(
                    self.h_process, ctypes.c_void_p(target_addr),
                    ctypes.byref(buf), 12, ctypes.byref(bytes_read)
                )
                if success2 and bytes_read.value == 12:
                    return (buf[0], buf[1], buf[2])
                    
        return None
        
    def world_to_geo_coords(self, wx: float, wy: float, wz: float) -> Dict[str, int]:
        """Converts world floats to region and cell integers."""
        # Standard Lineage 2 Region formula
        rx = int(wx // 32768) + 20
        ry = int(wy // 32768) + 18
        
        # Sub-region coordinates
        min_x = (rx - 20) * 32768
        min_y = (ry - 18) * 32768
        
        gx = int(wx - min_x) >> 4
        gy = int(wy - min_y) >> 4
        
        gx = max(0, min(CELLS_PER_AXIS - 1, gx))
        gy = max(0, min(CELLS_PER_AXIS - 1, gy))
        
        bx = gx >> 3
        by = gy >> 3
        cx = gx & 7
        cy = gy & 7
        
        return {
            "rx": rx, "ry": ry,
            "gx": gx, "gy": gy,
            "bx": bx, "by": by,
            "cx": cx, "cy": cy,
            "z": int(wz)
        }
        
    def close(self):
        if self.h_process:
            import ctypes
            ctypes.windll.kernel32.CloseHandle(self.h_process)
            self.h_process = None
