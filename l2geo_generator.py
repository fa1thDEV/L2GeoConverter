"""
L2Geo Generator
Procedural Lineage 2 geodata generation and terrain manipulation.

Supported operations:
- Flat arena / terrain carving
- Wall and barrier extrusion
- Passage opening (door / wall clearing)
- Multilayer platform and bridge insertion
- Heightmap parsing with NSWE slope computation
- Batch JSON patch execution
"""

import math
from typing import List, Dict, Any, Tuple, Optional
from l2geo_core import (
    GeoRegion, GeoBlock, GeoCell,
    BLOCK_FLAT, BLOCK_COMPLEX, BLOCK_MULTILAYER,
    FLAG_EAST, FLAG_WEST, FLAG_SOUTH, FLAG_NORTH, FLAG_ALL, FLAG_NONE,
    BLOCKS_PER_AXIS, CELLS_PER_BLOCK, CELLS_PER_AXIS, REGION_SIZE, CELL_SIZE
)

class GeoGenerator:
    @staticmethod
    def create_blank_region(region_x: int, region_y: int, default_z: int = 0) -> GeoRegion:
        """Creates a pristine, valid 256x256 geodata region with flat blocks."""
        region = GeoRegion(region_x, region_y)
        clean_z = int(default_z) & 0xFFF0
        for bx in range(BLOCKS_PER_AXIS):
            for by in range(BLOCKS_PER_AXIS):
                region.blocks[bx][by] = GeoBlock(BLOCK_FLAT, clean_z)
        return region

    @staticmethod
    def set_cell(region: GeoRegion, gx: int, gy: int, z: int, nswe: int = FLAG_ALL, layer_idx: int = 0):
        """Sets an exact cell height and movement flags, promoting block to COMPLEX or MULTILAYER if needed."""
        if not (0 <= gx < CELLS_PER_AXIS and 0 <= gy < CELLS_PER_AXIS):
            return
        bx = gx >> 3
        by = gy >> 3
        cx = gx & 7
        cy = gy & 7
        idx = (cx << 3) + cy

        block = region.blocks[bx][by]
        if block.block_type == BLOCK_FLAT:
            if block.flat_z == z and nswe == FLAG_ALL:
                return # Already flat at this value
            block.to_complex()

        if block.block_type == BLOCK_COMPLEX:
            if layer_idx == 0:
                block.cells[idx] = GeoCell(z, nswe)
            else:
                # Promote to multilayer
                old_cell = block.cells[idx]
                multi_cells = [[c] for c in block.cells]
                multi_cells[idx].append(GeoCell(z, nswe))
                block.block_type = BLOCK_MULTILAYER
                block.cells = multi_cells
        elif block.block_type == BLOCK_MULTILAYER:
            layers = block.cells[idx]
            if layer_idx < len(layers):
                layers[layer_idx] = GeoCell(z, nswe)
            else:
                layers.append(GeoCell(z, nswe))

    @staticmethod
    def carve_geo_box(region: GeoRegion, min_gx: int, min_gy: int, max_gx: int, max_gy: int, z: int, nswe: int = FLAG_ALL):
        """Sets a rectangular zone in geodata coordinates (0..2047)."""
        x0 = max(0, min(min_gx, max_gx))
        x1 = min(CELLS_PER_AXIS - 1, max(min_gx, max_gx))
        y0 = max(0, min(min_gy, max_gy))
        y1 = min(CELLS_PER_AXIS - 1, max(min_gy, max_gy))

        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                GeoGenerator.set_cell(region, gx, gy, z, nswe)

    @staticmethod
    def carve_world_box(region: GeoRegion, min_wx: int, min_wy: int, max_wx: int, max_wy: int, z: int, nswe: int = FLAG_ALL):
        """Sets a rectangular zone using Lineage 2 World coordinates (e.g. 83000, 148000)."""
        gx0, gy0 = region.world_to_geo(min(min_wx, max_wx), min(min_wy, max_wy))
        gx1, gy1 = region.world_to_geo(max(min_wx, max_wx), max(min_wy, max_wy))
        GeoGenerator.carve_geo_box(region, gx0, gy0, gx1, gy1, z, nswe)

    @staticmethod
    def carve_impassable_wall(region: GeoRegion, min_wx: int, min_wy: int, max_wx: int, max_wy: int, wall_height: int = 150):
        """Builds an impassable wall barrier across the bounding box."""
        gx0, gy0 = region.world_to_geo(min(min_wx, max_wx), min(min_wy, max_wy))
        gx1, gy1 = region.world_to_geo(max(min_wx, max_wx), max(min_wy, max_wy))

        x0 = max(0, min(gx0, gx1))
        x1 = min(CELLS_PER_AXIS - 1, max(gx0, gx1))
        y0 = max(0, min(gy0, gy1))
        y1 = min(CELLS_PER_AXIS - 1, max(gy0, gy1))

        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                cur_z = region.get_height(gx, gy)
                GeoGenerator.set_cell(region, gx, gy, cur_z + wall_height, FLAG_NONE)

    @staticmethod
    def add_bridge_layer(region: GeoRegion, min_wx: int, min_wy: int, max_wx: int, max_wy: int, bridge_z: int):
        """Adds an upper bridge/platform layer above the existing terrain without destroying ground below."""
        gx0, gy0 = region.world_to_geo(min(min_wx, max_wx), min(min_wy, max_wy))
        gx1, gy1 = region.world_to_geo(max(min_wx, max_wx), max(min_wy, max_wy))

        x0 = max(0, min(gx0, gx1))
        x1 = min(CELLS_PER_AXIS - 1, max(gx0, gx1))
        y0 = max(0, min(gy0, gy1))
        y1 = min(CELLS_PER_AXIS - 1, max(gy0, gy1))

        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                bx = gx >> 3
                by = gy >> 3
                cx = gx & 7
                cy = gy & 7
                block = region.blocks[bx][by]
                # Ensure multilayer
                if block.block_type == BLOCK_FLAT:
                    ground_z = block.flat_z
                    block.block_type = BLOCK_MULTILAYER
                    block.cells = [[GeoCell(ground_z, FLAG_ALL)] for _ in range(64)]
                elif block.block_type == BLOCK_COMPLEX:
                    block.block_type = BLOCK_MULTILAYER
                    block.cells = [[c] for c in block.cells]

                idx = (cx << 3) + cy
                block.cells[idx].append(GeoCell(bridge_z, FLAG_ALL))

    @staticmethod
    def recalculate_slopes(region: GeoRegion, slope_threshold: int = 32):
        """
        Scans entire region and calculates accurate NSWE passage based on elevation difference.
        If slope between neighbor cells is <= slope_threshold, movement is allowed. Otherwise, blocked.
        """
        # Ensure blocks that need slope changes become complex
        for gx in range(CELLS_PER_AXIS):
            bx = gx >> 3
            cx = gx & 7
            for gy in range(CELLS_PER_AXIS):
                by = gy >> 3
                cy = gy & 7
                z = region.get_height(gx, gy)

                # Check 4 directions
                e_ok = False
                w_ok = False
                s_ok = False
                n_ok = False

                if gx + 1 < CELLS_PER_AXIS and abs(region.get_height(gx + 1, gy) - z) <= slope_threshold:
                    e_ok = True
                if gx - 1 >= 0 and abs(region.get_height(gx - 1, gy) - z) <= slope_threshold:
                    w_ok = True
                if gy + 1 < CELLS_PER_AXIS and abs(region.get_height(gx, gy + 1) - z) <= slope_threshold:
                    s_ok = True
                if gy - 1 >= 0 and abs(region.get_height(gx, gy - 1) - z) <= slope_threshold:
                    n_ok = True

                nswe = (FLAG_EAST if e_ok else 0) | \
                       (FLAG_WEST if w_ok else 0) | \
                       (FLAG_SOUTH if s_ok else 0) | \
                       (FLAG_NORTH if n_ok else 0)

                block = region.blocks[bx][by]
                if block.block_type == BLOCK_FLAT:
                    if nswe != FLAG_ALL:
                        block.to_complex()
                        block.cells[(cx << 3) + cy].nswe = nswe
                elif block.block_type == BLOCK_COMPLEX:
                    block.cells[(cx << 3) + cy].nswe = nswe
                elif block.block_type == BLOCK_MULTILAYER:
                    # Update top layer
                    block.cells[(cx << 3) + cy][-1].nswe = nswe

        region.optimize_all_blocks()

    @staticmethod
    def apply_patch_script(region: GeoRegion, patch_data: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Executes structured JSON patch operations.
        Supported actions:
        - "level_ground": {"min_x", "min_y", "max_x", "max_y", "z"}
        - "build_wall": {"min_x", "min_y", "max_x", "max_y", "height"}
        - "open_door": {"min_x", "min_y", "max_x", "max_y"}
        - "add_bridge": {"min_x", "min_y", "max_x", "max_y", "z"}
        """
        applied = 0
        for cmd in patch_data:
            action = cmd.get("action", "").lower()
            if action == "level_ground":
                GeoGenerator.carve_world_box(
                    region,
                    cmd["min_x"], cmd["min_y"], cmd["max_x"], cmd["max_y"],
                    cmd["z"], cmd.get("nswe", FLAG_ALL)
                )
                applied += 1
            elif action == "build_wall":
                GeoGenerator.carve_impassable_wall(
                    region,
                    cmd["min_x"], cmd["min_y"], cmd["max_x"], cmd["max_y"],
                    cmd.get("height", 150)
                )
                applied += 1
            elif action == "open_door":
                gx0, gy0 = region.world_to_geo(cmd["min_x"], cmd["min_y"])
                gx1, gy1 = region.world_to_geo(cmd["max_x"], cmd["max_y"])
                for gx in range(min(gx0, gx1), max(gx0, gx1) + 1):
                    for gy in range(min(gy0, gy1), max(gy0, gy1) + 1):
                        z = region.get_height(gx, gy)
                        GeoGenerator.set_cell(region, gx, gy, z, FLAG_ALL)
                applied += 1
            elif action == "add_bridge":
                GeoGenerator.add_bridge_layer(
                    region,
                    cmd["min_x"], cmd["min_y"], cmd["max_x"], cmd["max_y"],
                    cmd["z"]
                )
                applied += 1
        return {"actions_applied": applied}
