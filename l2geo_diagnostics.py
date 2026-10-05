"""
L2Geo Diagnostics & Error Hunter
Detects, reports, and auto-repairs Lineage 2 geodata bugs:
- NSWE Asymmetry (One-way / invisible walls)
- Critical Cliff Discontinuities (Fall through world / step > 48)
- Multilayer Squeezes & Inverted Layers (< 32 units clearance)
- Extreme Out-of-bounds Z coordinates
- Block type redundancy & optimization opportunities

(c) fa1thDEV & L2GeoConverter Open Source Contributors
"""

from typing import List, Dict, Any, Tuple, Optional
from l2geo_core import (
    GeoRegion, GeoBlock, GeoCell,
    BLOCK_FLAT, BLOCK_COMPLEX, BLOCK_MULTILAYER,
    FLAG_EAST, FLAG_WEST, FLAG_SOUTH, FLAG_NORTH, FLAG_ALL, FLAG_NONE,
    BLOCKS_PER_AXIS, CELLS_PER_BLOCK, CELLS_PER_AXIS
)

class GeoDiagnosticReport:
    def __init__(self, region: GeoRegion):
        self.region = region
        self.issues: List[Dict[str, Any]] = []
        self.stats = {
            "total_cells_checked": 0,
            "asymmetry_errors": 0,
            "cliff_errors": 0,
            "layer_squeeze_errors": 0,
            "out_of_bounds_errors": 0,
            "redundant_complex_blocks": 0
        }

    def add_issue(self, severity: str, bug_type: str, geo_x: int, geo_y: int, message: str, details: Optional[Dict[str, Any]] = None):
        wx, wy, wz = self.region.geo_to_world(geo_x, geo_y)
        issue = {
            "severity": severity, # 'CRITICAL', 'WARNING', 'INFO'
            "type": bug_type,
            "geo_coords": {"gx": geo_x, "gy": geo_y},
            "world_coords": {"x": wx, "y": wy},
            "message": message,
            "details": details or {}
        }
        self.issues.append(issue)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "region": f"{self.region.region_x}_{self.region.region_y}",
            "stats": self.stats,
            "issue_count": len(self.issues),
            "issues": self.issues
        }


class GeoAuditor:
    def __init__(self, cliff_threshold: int = 48, min_layer_clearance: int = 32):
        self.cliff_threshold = cliff_threshold
        self.min_layer_clearance = min_layer_clearance

    def audit(self, region: GeoRegion, sample_limit: int = 200, stop_event=None) -> GeoDiagnosticReport:
        report = GeoDiagnosticReport(region)

        # 1. Audit block level redundancy
        for bx in range(BLOCKS_PER_AXIS):
            if stop_event and stop_event.is_set():
                return report
            for by in range(BLOCKS_PER_AXIS):
                b = region.blocks[bx][by]
                if b.block_type == BLOCK_COMPLEX:
                    # check if all 64 cells are identical
                    if b.cells and len(b.cells) == 64:
                        first = b.cells[0]
                        if first.nswe == FLAG_ALL and all(c.z == first.z and c.nswe == FLAG_ALL for c in b.cells):
                            report.stats["redundant_complex_blocks"] += 1
                            if report.stats["redundant_complex_blocks"] <= sample_limit:
                                gx = (bx << 3)
                                gy = (by << 3)
                                report.add_issue(
                                    "INFO", "REDUNDANT_COMPLEX_BLOCK",
                                    gx, gy,
                                    f"Block ({bx}, {by}) is Complex but completely flat at Z={first.z}. Can be optimized to Type 0.",
                                    {"bx": bx, "by": by, "z": first.z}
                                )

        # 2. Audit cell level NSWE symmetry, cliffs, and layers
        for gx in range(CELLS_PER_AXIS):
            if stop_event and stop_event.is_set():
                return report
            bx = gx >> 3
            cx = gx & 7
            for gy in range(CELLS_PER_AXIS):
                by = gy >> 3
                cy = gy & 7
                report.stats["total_cells_checked"] += 1

                block = region.blocks[bx][by]
                layers = block.get_cell_layers(cx, cy)

                # Check Multilayer issues
                if len(layers) > 1:
                    for i in range(len(layers) - 1):
                        z_curr = layers[i].z
                        z_next = layers[i+1].z
                        clearance = abs(z_curr - z_next)
                        if clearance < self.min_layer_clearance:
                            report.stats["layer_squeeze_errors"] += 1
                            if report.stats["layer_squeeze_errors"] <= sample_limit:
                                report.add_issue(
                                    "WARNING", "LAYER_SQUEEZE",
                                    gx, gy,
                                    f"Layers too close at ({gx}, {gy}): Z1={z_curr}, Z2={z_next} (diff={clearance} < {self.min_layer_clearance}). Players/mobs may get stuck.",
                                    {"layer1_z": z_curr, "layer2_z": z_next, "clearance": clearance}
                                )

                # Check each layer for out of bounds Z and NSWE connections
                for layer in layers:
                    z = layer.z
                    nswe = layer.nswe

                    if z < -16384 or z > 16384:
                        report.stats["out_of_bounds_errors"] += 1
                        if report.stats["out_of_bounds_errors"] <= sample_limit:
                            report.add_issue(
                                "CRITICAL", "OUT_OF_BOUNDS_Z",
                                gx, gy,
                                f"Illegal height Z={z} at ({gx}, {gy}). Valid range is [-16384, 16384].",
                                {"z": z}
                            )

                    # Check East neighbor (gx + 1, gy)
                    if (nswe & FLAG_EAST) and gx + 1 < CELLS_PER_AXIS:
                        n_gx = gx + 1
                        n_gy = gy
                        n_layers = region.blocks[n_gx >> 3][n_gy >> 3].get_cell_layers(n_gx & 7, n_gy & 7)
                        # Find corresponding layer in neighbor
                        n_layer = self._find_matching_layer(z, n_layers)
                        if n_layer:
                            # Check symmetry
                            if not (n_layer.nswe & FLAG_WEST):
                                report.stats["asymmetry_errors"] += 1
                                if report.stats["asymmetry_errors"] <= sample_limit:
                                    report.add_issue(
                                        "WARNING", "NSWE_ASYMMETRY",
                                        gx, gy,
                                        f"One-way wall: Can move East from ({gx}, {gy}) to ({n_gx}, {n_gy}), but neighbor denies West movement.",
                                        {"from": [gx, gy], "to": [n_gx, n_gy], "dir": "EAST"}
                                    )
                            # Check cliff height jump
                            h_diff = abs(z - n_layer.z)
                            if h_diff > self.cliff_threshold:
                                report.stats["cliff_errors"] += 1
                                if report.stats["cliff_errors"] <= sample_limit:
                                    report.add_issue(
                                        "CRITICAL", "CLIFF_FALL_THROUGH",
                                        gx, gy,
                                        f"Dangerous cliff passage: East movement allowed across {h_diff} units drop (Z1={z}, Z2={n_layer.z}). Players will fall through world.",
                                        {"from_z": z, "to_z": n_layer.z, "drop": h_diff}
                                    )

                    # Check South neighbor (gx, gy + 1)
                    if (nswe & FLAG_SOUTH) and gy + 1 < CELLS_PER_AXIS:
                        n_gx = gx
                        n_gy = gy + 1
                        n_layers = region.blocks[n_gx >> 3][n_gy >> 3].get_cell_layers(n_gx & 7, n_gy & 7)
                        n_layer = self._find_matching_layer(z, n_layers)
                        if n_layer:
                            if not (n_layer.nswe & FLAG_NORTH):
                                report.stats["asymmetry_errors"] += 1
                                if report.stats["asymmetry_errors"] <= sample_limit:
                                    report.add_issue(
                                        "WARNING", "NSWE_ASYMMETRY",
                                        gx, gy,
                                        f"One-way wall: Can move South from ({gx}, {gy}) to ({n_gx}, {n_gy}), but neighbor denies North movement.",
                                        {"from": [gx, gy], "to": [n_gx, n_gy], "dir": "SOUTH"}
                                    )
                            h_diff = abs(z - n_layer.z)
                            if h_diff > self.cliff_threshold:
                                report.stats["cliff_errors"] += 1
                                if report.stats["cliff_errors"] <= sample_limit:
                                    report.add_issue(
                                        "CRITICAL", "CLIFF_FALL_THROUGH",
                                        gx, gy,
                                        f"Dangerous cliff passage: South movement allowed across {h_diff} units drop (Z1={z}, Z2={n_layer.z}). Players will fall through world.",
                                        {"from_z": z, "to_z": n_layer.z, "drop": h_diff}
                                    )

        return report

    def _find_matching_layer(self, z: int, layers: List[GeoCell]) -> Optional[GeoCell]:
        if not layers: return None
        best = layers[0]
        min_diff = abs(layers[0].z - z)
        for l in layers:
            d = abs(l.z - z)
            if d < min_diff:
                min_diff = d
                best = l
        return best


class GeoRepairer:
    def __init__(self, max_walkable_step: int = 32, max_cliff_step: int = 48):
        self.max_walkable_step = max_walkable_step
        self.max_cliff_step = max_cliff_step

    def repair(self, region: GeoRegion, stop_event=None) -> Dict[str, int]:
        """Repairs all common geodata glitches in the region."""
        stats = {
            "cliffs_blocked": 0,
            "asymmetries_repaired": 0,
            "layers_sorted": 0,
            "redundant_blocks_flattened": 0
        }

        # 1. Flatten redundant complex blocks first
        stats["redundant_blocks_flattened"] = region.optimize_all_blocks()

        # 2. Convert blocks to complex if we need to modify individual cell NSWE
        for gx in range(CELLS_PER_AXIS):
            if stop_event and stop_event.is_set():
                stats["stopped"] = True
                return stats
            bx = gx >> 3
            cx = gx & 7
            for gy in range(CELLS_PER_AXIS):
                by = gy >> 3
                cy = gy & 7
                block = region.blocks[bx][by]

                # Sort multilayer heights
                if block.block_type == BLOCK_MULTILAYER and block.cells:
                    idx = (cx << 3) + cy
                    layers = block.cells[idx]
                    if len(layers) > 1:
                        # Sort layers ascending by Z
                        sorted_layers = sorted(layers, key=lambda l: l.z)
                        if [l.z for l in layers] != [l.z for l in sorted_layers]:
                            block.cells[idx] = sorted_layers
                            stats["layers_sorted"] += 1

                # Check East connection
                if gx + 1 < CELLS_PER_AXIS:
                    n_gx = gx + 1
                    n_gy = gy
                    n_block = region.blocks[n_gx >> 3][n_gy >> 3]

                    layers1 = block.get_cell_layers(cx, cy)
                    layers2 = n_block.get_cell_layers(n_gx & 7, n_gy & 7)

                    for l1 in layers1:
                        l2 = self._closest(l1.z, layers2)
                        if not l2: continue
                        h_diff = abs(l1.z - l2.z)

                        # If height difference is too steep, block passage only on the higher layer towards the lower layer
                        if h_diff > self.max_cliff_step:
                            if l1.z > l2.z:
                                if l1.nswe & FLAG_EAST:
                                    block.to_complex()
                                    l1.nswe &= ~FLAG_EAST
                                    stats["cliffs_blocked"] += 1
                            elif l2.z > l1.z:
                                if l2.nswe & FLAG_WEST:
                                    n_block.to_complex()
                                    l2.nswe &= ~FLAG_WEST
                                    stats["cliffs_blocked"] += 1

                        # If height difference is walkable, ensure symmetry
                        elif h_diff <= self.max_walkable_step:
                            if bool(l1.nswe & FLAG_EAST) != bool(l2.nswe & FLAG_WEST):
                                block.to_complex()
                                n_block.to_complex()
                                # Enable passage bidirectionally
                                l1.nswe |= FLAG_EAST
                                l2.nswe |= FLAG_WEST
                                stats["asymmetries_repaired"] += 1

                # Check South connection
                if gy + 1 < CELLS_PER_AXIS:
                    n_gx = gx
                    n_gy = gy + 1
                    n_block = region.blocks[n_gx >> 3][n_gy >> 3]

                    layers1 = block.get_cell_layers(cx, cy)
                    layers2 = n_block.get_cell_layers(n_gx & 7, n_gy & 7)

                    for l1 in layers1:
                        l2 = self._closest(l1.z, layers2)
                        if not l2: continue
                        h_diff = abs(l1.z - l2.z)

                        if h_diff > self.max_cliff_step:
                            if l1.z > l2.z:
                                if l1.nswe & FLAG_SOUTH:
                                    block.to_complex()
                                    l1.nswe &= ~FLAG_SOUTH
                                    stats["cliffs_blocked"] += 1
                            elif l2.z > l1.z:
                                if l2.nswe & FLAG_NORTH:
                                    n_block.to_complex()
                                    l2.nswe &= ~FLAG_NORTH
                                    stats["cliffs_blocked"] += 1
                        elif h_diff <= self.max_walkable_step:
                            if bool(l1.nswe & FLAG_SOUTH) != bool(l2.nswe & FLAG_NORTH):
                                block.to_complex()
                                n_block.to_complex()
                                l1.nswe |= FLAG_SOUTH
                                l2.nswe |= FLAG_NORTH
                                stats["asymmetries_repaired"] += 1

        # Re-optimize where possible
        re_optimized = region.optimize_all_blocks()
        stats["redundant_blocks_flattened"] += re_optimized
        return stats

    def _closest(self, z: int, layers: List[GeoCell]) -> Optional[GeoCell]:
        if not layers: return None
        best = layers[0]
        min_diff = abs(layers[0].z - z)
        for l in layers:
            d = abs(l.z - z)
            if d < min_diff:
                min_diff = d
                best = l
        return best
