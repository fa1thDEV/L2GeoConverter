#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Geodata Diagnostics and Repair Engine
Detects pathfinding anomalies, cliff drops, asymmetric movement flags, and layer traps.
Auto-repairs issues and exports JSON reports.

(c) fa1thDEV & L2GeoConverter Contributors
"""

import json
import os
import struct
from typing import Dict, Any, List, Tuple, Optional

from .formats import (
    BLOCKS, dec_h, dec_nswe, enc_cell, parse_region, region_of,
    sniff_format, L2GCodec, GeoError, pack_pts_header, pack_pts_flat_heights,
    complex_is_flat, pts_flat_surface, quant_h, PROTO_GD
)
from .convert import l2j2pts_bytes
from .ui import bold, cyan, dim, green, red, yellow, progress

# Movement flags
FLAG_NONE  = 0x00
FLAG_EAST  = 0x01
FLAG_WEST  = 0x02
FLAG_SOUTH = 0x04
FLAG_NORTH = 0x08
FLAG_ALL   = 0x0F

CELLS_PER_BLOCK = 8
BLOCKS_PER_AXIS = 256
CELLS_PER_AXIS  = BLOCKS_PER_AXIS * CELLS_PER_BLOCK # 2048
REGION_WORLD_SIZE = 32768 # World units per region

# (dx, dy, flag toward neighbour, neighbour's flag back, name)
DIRECTIONS = (
    (1, 0, FLAG_EAST, FLAG_WEST, "EAST"),
    (-1, 0, FLAG_WEST, FLAG_EAST, "WEST"),
    (0, 1, FLAG_SOUTH, FLAG_NORTH, "SOUTH"),
    (0, -1, FLAG_NORTH, FLAG_SOUTH, "NORTH"),
)
# Pairs of opposite directions; repair walks each cell boundary once.
FORWARD_DIRECTIONS = (DIRECTIONS[0], DIRECTIONS[2])

def geo_to_world(rx: int, ry: int, gx: int, gy: int, z: int = 0) -> Tuple[int, int, int]:
    wx = (rx - 20) * REGION_WORLD_SIZE + (gx << 4) + 8
    wy = (ry - 18) * REGION_WORLD_SIZE + (gy << 4) + 8
    return wx, wy, z


def world_to_geo(rx: int, ry: int, wx: int, wy: int) -> Tuple[int, int]:
    min_x = (rx - 20) * REGION_WORLD_SIZE
    min_y = (ry - 18) * REGION_WORLD_SIZE
    gx = (wx - min_x) >> 4
    gy = (wy - min_y) >> 4
    return gx, gy


def get_cell_layers(blocks: List[Any], gx: int, gy: int) -> List[Tuple[int, int]]:
    """Returns list of (h, nswe) for (gx, gy) where gx in 0..2047, gy in 0..2047."""
    bx = gx >> 3
    by = gy >> 3
    cx = gx & 7
    cy = gy & 7
    b_idx = (bx << 8) | by
    c_idx = (cx << 3) | cy
    return blocks[b_idx][c_idx]


def set_cell_layers(blocks: List[Any], gx: int, gy: int, layers: List[Tuple[int, int]]):
    bx = gx >> 3
    by = gy >> 3
    cx = gx & 7
    cy = gy & 7
    b_idx = (bx << 8) | by
    c_idx = (cx << 3) | cy
    # Make sure cell is mutable copy
    block = blocks[b_idx]
    if len(block) == 64 and id(block[0]) == id(block[1]):
        # Flat block copy
        blocks[b_idx] = [[(l[0], l[1]) for l in cell] for cell in block]
    blocks[b_idx][c_idx] = layers


class GeoDiagnosticEngine:
    def __init__(self, cliff_threshold: int = 48, min_clearance: int = 32,
                 max_step: int = 32):
        self.cliff_threshold = cliff_threshold
        self.min_clearance = min_clearance
        self.max_step = max_step

    def analyze(self, path: str, max_issues: int = 100, stop_event=None) -> Dict[str, Any]:
        rx, ry = region_of(path)
        blocks = parse_region(path)
        stats = {
            "file": os.path.basename(path),
            "region": f"{rx}_{ry}",
            "format": sniff_format(path),
            "total_blocks": len(blocks),
            "asymmetry_errors": 0,
            "cliff_errors": 0,
            "layer_squeeze_errors": 0,
            "out_of_bounds_errors": 0
        }
        issues: List[Dict[str, Any]] = []

        for gx in range(CELLS_PER_AXIS):
            if stop_event and stop_event.is_set():
                break
            for gy in range(CELLS_PER_AXIS):
                layers = get_cell_layers(blocks, gx, gy)

                # Check Multilayer Squeezes
                if len(layers) > 1:
                    for i in range(len(layers) - 1):
                        diff = abs(layers[i][0] - layers[i+1][0])
                        if diff < self.min_clearance:
                            stats["layer_squeeze_errors"] += 1
                            if len(issues) < max_issues:
                                wx, wy, _ = geo_to_world(rx, ry, gx, gy)
                                issues.append({
                                    "severity": "WARNING",
                                    "type": "LAYER_SQUEEZE",
                                    "geo": [gx, gy],
                                    "world": [wx, wy],
                                    "msg": f"Layer clearance too small ({diff} < {self.min_clearance}u) between Z={layers[i][0]} and Z={layers[i+1][0]}",
                                    "details": {"z1": layers[i][0], "z2": layers[i+1][0], "clearance": diff}
                                })

                for h, nswe in layers:
                    if h < -16384 or h > 16384:
                        stats["out_of_bounds_errors"] += 1
                        if len(issues) < max_issues:
                            wx, wy, _ = geo_to_world(rx, ry, gx, gy)
                            issues.append({
                                "severity": "CRITICAL",
                                "type": "OUT_OF_BOUNDS_Z",
                                "geo": [gx, gy],
                                "world": [wx, wy],
                                "msg": f"Extreme height Z={h} outside valid coordinate range",
                                "details": {"z": h}
                            })

                    # Every open flag is checked from its own side, so a drop
                    # or one-way passage toward W/N is reported as well.
                    for dx, dy, flag, back, dname in DIRECTIONS:
                        nx, ny = gx + dx, gy + dy
                        if not (nswe & flag) or not (0 <= nx < CELLS_PER_AXIS and 0 <= ny < CELLS_PER_AXIS):
                            continue
                        n_layer = self._closest(h, get_cell_layers(blocks, nx, ny))
                        if not n_layer:
                            continue
                        nh, nnswe = n_layer
                        if not (nnswe & back):
                            stats["asymmetry_errors"] += 1
                            if len(issues) < max_issues:
                                wx, wy, _ = geo_to_world(rx, ry, gx, gy)
                                issues.append({
                                    "severity": "WARNING",
                                    "type": "NSWE_ASYMMETRY",
                                    "geo": [gx, gy],
                                    "world": [wx, wy],
                                    "msg": f"One-way {dname.title()} passage to ({nx},{ny}) but neighbor denies return",
                                    "details": {"dir": dname, "target_geo": [nx, ny]}
                                })
                        h_diff = abs(h - nh)
                        if h_diff > self.cliff_threshold and h > nh:
                            stats["cliff_errors"] += 1
                            if len(issues) < max_issues:
                                wx, wy, _ = geo_to_world(rx, ry, gx, gy)
                                issues.append({
                                    "severity": "CRITICAL",
                                    "type": "CLIFF_FALL",
                                    "geo": [gx, gy],
                                    "world": [wx, wy],
                                    "msg": f"Hazardous cliff drop of {h_diff}u with open {dname.title()} flag (Z1={h}, Z2={nh})",
                                    "details": {"dir": dname, "drop": h_diff, "from_z": h, "to_z": nh}
                                })

        return {
            "stats": stats,
            "total_issues_found": stats["asymmetry_errors"] + stats["cliff_errors"] + stats["layer_squeeze_errors"] + stats["out_of_bounds_errors"],
            "sample_issues": issues
        }

    def repair_and_save(self, src_path: str, dst_path: str, stop_event=None) -> Dict[str, Any]:
        rx, ry = region_of(src_path)
        blocks = parse_region(src_path)
        stats = {
            "cliffs_sealed": 0,
            "asymmetries_repaired": 0,
            "layers_sorted": 0
        }

        # Deep copy blocks so mutations don't corrupt shared flat arrays
        unpacked_blocks = []
        for blk in blocks:
            unpacked_blocks.append([[(l[0], l[1]) for l in cell] for cell in blk])

        for gx in range(CELLS_PER_AXIS):
            if stop_event and stop_event.is_set():
                stats["stopped"] = True
                return stats
            for gy in range(CELLS_PER_AXIS):
                layers = get_cell_layers(unpacked_blocks, gx, gy)

                # Sort multilayer ascending
                if len(layers) > 1:
                    sorted_l = sorted(layers, key=lambda l: l[0])
                    if sorted_l != layers:
                        set_cell_layers(unpacked_blocks, gx, gy, sorted_l)
                        stats["layers_sorted"] += 1
                        layers = sorted_l

                for dx, dy, flag, back, _ in FORWARD_DIRECTIONS:
                    nx, ny = gx + dx, gy + dy
                    if nx < CELLS_PER_AXIS and ny < CELLS_PER_AXIS:
                        self._repair_boundary(unpacked_blocks, gx, gy, nx, ny, flag, back, stats)

        # Encode back to target format
        out_fmt = sniff_format(dst_path) or sniff_format(src_path)
        l2j_bytes = self._encode_to_l2j_bytes(unpacked_blocks)

        if out_fmt == 'l2g':
            enc = L2GCodec.encrypt(l2j_bytes)
            with open(dst_path, 'wb') as f:
                f.write(enc)
        elif out_fmt == 'l2j':
            with open(dst_path, 'wb') as f:
                f.write(l2j_bytes)
        elif out_fmt == 'pts':
            pts_bytes, _, _, _ = l2j2pts_bytes(l2j_bytes, rx, ry, PROTO_GD)
            with open(dst_path, 'wb') as f:
                f.write(pts_bytes)
        else:
            with open(dst_path, 'wb') as f:
                f.write(l2j_bytes)

        return stats

    def _repair_boundary(self, blocks, gx, gy, nx, ny, flag, back, stats):
        """Repair the boundary between cell A=(gx,gy) and B=(nx,ny).

        Layers are paired by nearest height in BOTH directions, so an upper
        layer that exists only on B is still checked against A (otherwise a
        fall from it would stay open). For each pair:

        * drop > cliff_threshold: close the flag from the HIGHER layer toward
          the lower one only; the lower floor (e.g. under an arch) keeps it.
        * step <= max_step with a one-way flag: close the open side. Opening
          the closed side instead could cut through a thin wall, since the
          original collision is not available here.
        """
        a = get_cell_layers(blocks, gx, gy)
        b = get_cell_layers(blocks, nx, ny)
        if not a or not b:
            return
        a, b = list(a), list(b)
        pairs = []
        for i, (h, _) in enumerate(a):
            pairs.append((i, self._closest_idx(h, b)))
        for j, (nh, _) in enumerate(b):
            pair = (self._closest_idx(nh, a), j)
            if pair not in pairs:
                pairs.append(pair)
        changed = False
        for i, j in pairs:
            h, nswe = a[i]
            nh, nnswe = b[j]
            diff = abs(h - nh)
            if diff > self.cliff_threshold:
                if h > nh and nswe & flag:
                    a[i] = (h, nswe & ~flag)
                    stats["cliffs_sealed"] += 1
                    changed = True
                elif nh > h and nnswe & back:
                    b[j] = (nh, nnswe & ~back)
                    stats["cliffs_sealed"] += 1
                    changed = True
            elif diff <= self.max_step and bool(nswe & flag) != bool(nnswe & back):
                a[i] = (h, nswe & ~flag)
                b[j] = (nh, nnswe & ~back)
                stats["asymmetries_repaired"] += 1
                changed = True
        if changed:
            set_cell_layers(blocks, gx, gy, a)
            set_cell_layers(blocks, nx, ny, b)

    def _closest(self, z: int, layers: List[Tuple[int, int]]) -> Optional[Tuple[int, int]]:
        if not layers: return None
        best = layers[0]
        min_diff = abs(layers[0][0] - z)
        for l in layers:
            d = abs(l[0] - z)
            if d < min_diff:
                min_diff = d
                best = l
        return best

    def _closest_idx(self, z: int, layers: List[Tuple[int, int]]) -> Optional[int]:
        if not layers: return None
        best_idx = 0
        min_diff = abs(layers[0][0] - z)
        for idx, l in enumerate(layers):
            d = abs(l[0] - z)
            if d < min_diff:
                min_diff = d
                best_idx = idx
        return best_idx

    def _encode_to_l2j_bytes(self, blocks: List[Any]) -> bytes:
        out = bytearray()
        for blk in blocks:
            # Check if block is flat (all 64 cells have 1 layer with same height and NSWE=15)
            is_flat = True
            first_h = blk[0][0][0]
            for cell in blk:
                if len(cell) != 1 or cell[0][1] != 15 or cell[0][0] != first_h:
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


def cmd_diagnose(paths: List[str], json_mode: bool = False, fix_dir: Optional[str] = None, cliff_th: int = 48) -> int:
    engine = GeoDiagnosticEngine(cliff_threshold=cliff_th)
    all_reports = []

    for p in paths:
        if os.path.isdir(p):
            files = [os.path.join(p, f) for f in os.listdir(p) if sniff_format(f)]
        else:
            files = [p]

        for f in sorted(files):
            rep = engine.analyze(f)
            all_reports.append(rep)

            if not json_mode:
                s = rep["stats"]
                print(f"\n  {bold('Diagnosis:')} {cyan(s['file'])} (Region {s['region']}, Format: {s['format'].upper()})")
                print(f"    Asymmetric one-way walls: {yellow(str(s['asymmetry_errors'])) if s['asymmetry_errors'] else green('0')}")
                print(f"    Dangerous cliff drops:    {red(str(s['cliff_errors'])) if s['cliff_errors'] else green('0')}")
                print(f"    Layer traps / squeezes:   {yellow(str(s['layer_squeeze_errors'])) if s['layer_squeeze_errors'] else green('0')}")
                print(f"    Out-of-bounds Z errors:   {red(str(s['out_of_bounds_errors'])) if s['out_of_bounds_errors'] else green('0')}")

                if rep["sample_issues"]:
                    print(dim(f"    Showing first {len(rep['sample_issues'])} sample issues:"))
                    for iss in rep["sample_issues"][:5]:
                        prefix = red("[!]") if iss["severity"] == "CRITICAL" else yellow("[*]")
                        print(f"      {prefix} ({iss['type']}) @ World({iss['world'][0]}, {iss['world'][1]}): {iss['msg']}")

            if fix_dir:
                os.makedirs(fix_dir, exist_ok=True)
                dst = os.path.join(fix_dir, os.path.basename(f))
                fix_res = engine.repair_and_save(f, dst)
                if not json_mode:
                    print(f"    {green('✓')} Auto-repaired -> {dst}: {fix_res['asymmetries_repaired']} walls fixed, {fix_res['cliffs_sealed']} cliffs sealed.")

    if json_mode:
        print(json.dumps(all_reports, indent=2))

    return 0
