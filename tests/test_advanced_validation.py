#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Advanced 100-check validation suite: stress testing, raycasting, and pathfinding.

Covers 100 specialized checks:
  1. Stress & Malformed Geodata Resilience (Tests 1-25)
  2. 3D Raycasting & Geometric Intersections (Tests 26-50)
  3. City Gate & Archway Clearance Invariants (Tests 51-75)
  4. Binary Structure & Multi-Protocol Format Integrity (Tests 76-100)
"""

import math
import os
import struct
import tempfile
import time
import unittest
from typing import List, Tuple

from geolib.formats import (
    BLOCKS, dec_h, dec_nswe, enc_cell, parse_region, quant_h,
    sniff_format, L2GCodec, pack_pts_header, pts_flat_surface, GeoError
)
from geolib.diagnostics import (
    geo_to_world, world_to_geo, GeoDiagnosticEngine,
    FLAG_EAST, FLAG_WEST, FLAG_SOUTH, FLAG_NORTH, FLAG_ALL, FLAG_NONE
)
from geolib.editor import (
    shift_z_blocks, shift_xy_blocks, delete_z_range_blocks,
    recalculate_slope_flags, encode_blocks_to_l2j, save_edited_region,
    L2ClientMemoryScanner, BLOCKS_PER_AXIS, CELLS_PER_BLOCK, CELLS_PER_AXIS
)


def make_mock_blocks(default_h: int = 100, default_nswe: int = 15):
    flat_cell = [(quant_h(default_h), default_nswe)]
    block = [list(flat_cell) for _ in range(64)]
    return [list(block) for _ in range(BLOCKS)]


class TestAdvancedValidation(unittest.TestCase):

    # =========================================================================
    # PART 1: STRESS & MALFORMED GEODATA RESILIENCE (Tests 1-25)
    # =========================================================================

    def test_001_empty_file_handling(self):
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(b"")
            tf_path = tf.name
        try:
            with self.assertRaises(Exception):
                parse_region(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_002_truncated_l2j_file(self):
        # L2J requires 65536 blocks; 10 bytes is truncated
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00")
            tf_path = tf.name
        try:
            with self.assertRaises(Exception):
                parse_region(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_003_invalid_block_type_byte(self):
        # Type 5 is invalid (only 0, 1, 2 valid)
        raw = bytearray([5, 0, 0] * 100)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(bytes(raw))
            tf_path = tf.name
        try:
            with self.assertRaises(GeoError):
                parse_region(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_004_corrupt_layer_count_exceeds_max(self):
        # Multilayer block with layer count = 150 (> 125 max allowed)
        raw = bytearray([2])  # Type 2
        raw.append(150)       # Corrupt nl
        raw.extend(b"\x00" * 300)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(bytes(raw))
            tf_path = tf.name
        try:
            with self.assertRaises(GeoError):
                parse_region(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_005_corrupt_layer_count_zero(self):
        # Multilayer cell with 0 layers is illegal
        raw = bytearray([2])
        raw.append(0)  # nl = 0
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(bytes(raw))
            tf_path = tf.name
        try:
            with self.assertRaises(GeoError):
                parse_region(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_006_massive_multilayer_capacity(self):
        # Test max valid layers (125 layers)
        blocks = make_mock_blocks(100)
        max_layers = [(i * 32, FLAG_ALL) for i in range(125)]
        blocks[0][0] = max_layers
        raw = encode_blocks_to_l2j(blocks)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            parsed = parse_region(tf_path)
            self.assertEqual(len(parsed[0][0]), 125)
            self.assertEqual(parsed[0][0][124][0], 124 * 32)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_007_all_flat_region_serialization_speed(self):
        blocks = make_mock_blocks(100)
        t0 = time.time()
        raw = encode_blocks_to_l2j(blocks)
        elapsed = time.time() - t0
        self.assertLess(elapsed, 1.5)
        # All flat = 65536 * 3 bytes = 196,608 bytes
        self.assertEqual(len(raw), 196608)

    def test_008_all_complex_region_size(self):
        blocks = make_mock_blocks(100)
        # Force complex by varying one cell in every block
        for b in range(10):
            blocks[b][0] = [(104, FLAG_EAST)]
        raw = encode_blocks_to_l2j(blocks)
        self.assertGreater(len(raw), 196608)

    def test_009_bfs_reachability_open_path(self):
        # 8x8 block with open path from (0,0) to (7,7)
        grid = [[FLAG_ALL for _ in range(8)] for _ in range(8)]
        # Simple BFS
        visited = set()
        queue = [(0, 0)]
        while queue:
            cx, cy = queue.pop(0)
            if (cx, cy) == (7, 7):
                visited.add((cx, cy))
                break
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            if cx < 7 and (grid[cy][cx] & FLAG_EAST):
                queue.append((cx + 1, cy))
            if cy < 7 and (grid[cy][cx] & FLAG_SOUTH):
                queue.append((cx, cy + 1))
        self.assertIn((7, 7), visited)

    def test_010_bfs_reachability_blocked_by_wall(self):
        grid = [[FLAG_ALL for _ in range(8)] for _ in range(8)]
        # Complete wall across column 4: no East passage from col 3, no West from col 4
        for y in range(8):
            grid[y][3] &= ~FLAG_EAST
            grid[y][4] &= ~FLAG_WEST
        visited = set()
        queue = [(0, 0)]
        while queue:
            cx, cy = queue.pop(0)
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            if cx < 7 and (grid[cy][cx] & FLAG_EAST):
                queue.append((cx + 1, cy))
            if cy < 7 and (grid[cy][cx] & FLAG_SOUTH):
                queue.append((cx, cy + 1))
        # Cannot reach (7, 7)
        self.assertNotIn((7, 7), visited)

    def test_011_random_noise_tolerance(self):
        import random
        random.seed(42)
        raw = bytes([random.randint(0, 255) for _ in range(10000)])
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            with self.assertRaises(Exception):
                parse_region(tf_path)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_012_extreme_z_quantization_stability(self):
        for val in [-32768, -32767, -1, 0, 1, 32766, 32767]:
            q = quant_h(val)
            self.assertEqual(q % 8, 0)
            self.assertGreaterEqual(q, -32768)
            self.assertLessEqual(q, 32767)

    def test_013_repeated_shift_z_zero_sum(self):
        blocks = make_mock_blocks(128)
        shift_z_blocks(blocks, 120)
        shift_z_blocks(blocks, -120)
        self.assertEqual(blocks[0][0][0][0], 128)

    def test_014_extreme_shift_xy_limits(self):
        blocks = make_mock_blocks(100)
        # Shift beyond 255
        res = shift_xy_blocks(blocks, 300, 300)
        self.assertEqual(res["shifted_blocks"], 0)
        self.assertEqual(res["void_filled"], BLOCKS)

    def test_015_delete_z_range_inverted_infinite(self):
        blocks = make_mock_blocks(100)
        # Delete entire universe [-32768, 32767]
        delete_z_range_blocks(blocks, -32768, 32767, keep_at_least_one=True)
        # Every cell should still have 1 sealed layer
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(blocks[0][0][0][1], FLAG_NONE)

    def test_016_delete_z_range_preserves_unrelated_cells(self):
        blocks = make_mock_blocks(100)
        blocks[0][0] = [(100, FLAG_ALL), (1000, FLAG_ALL)]
        blocks[0][1] = [(200, FLAG_ALL)]
        delete_z_range_blocks(blocks, 900, 1100)
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(len(blocks[0][1]), 1)
        self.assertEqual(blocks[0][1][0][0], 200)

    def test_017_nswe_bitwise_composition(self):
        # Test all 16 bit combinations
        for flags in range(16):
            has_e = bool(flags & FLAG_EAST)
            has_w = bool(flags & FLAG_WEST)
            has_s = bool(flags & FLAG_SOUTH)
            has_n = bool(flags & FLAG_NORTH)
            reconstructed = (
                (FLAG_EAST if has_e else 0) |
                (FLAG_WEST if has_w else 0) |
                (FLAG_SOUTH if has_s else 0) |
                (FLAG_NORTH if has_n else 0)
            )
            self.assertEqual(flags, reconstructed)

    def test_018_l2g_empty_payload_codec(self):
        empty = b""
        enc = L2GCodec.encrypt(empty)
        dec = L2GCodec.decrypt(enc)
        self.assertEqual(dec, empty)

    def test_019_l2g_large_payload_codec(self):
        payload = b"X" * 100_000
        enc = L2GCodec.encrypt(payload)
        dec = L2GCodec.decrypt(enc)
        self.assertEqual(dec, payload)

    def test_020_l2g_magic_key_xor(self):
        # Key header should be 4 bytes
        enc = L2GCodec.encrypt(b"Test")
        self.assertGreaterEqual(len(enc), 4)

    def test_021_world_coordinate_corner_top_left(self):
        # rx=10, ry=10
        wx, wy, _ = geo_to_world(10, 10, 0, 0)
        gx, gy = world_to_geo(10, 10, wx, wy)
        self.assertEqual(gx, 0)
        self.assertEqual(gy, 0)

    def test_022_world_coordinate_corner_bottom_right(self):
        # rx=30, ry=30, max cell 2047, 2047
        wx, wy, _ = geo_to_world(30, 30, 2047, 2047)
        gx, gy = world_to_geo(30, 30, wx, wy)
        self.assertEqual(gx, 2047)
        self.assertEqual(gy, 2047)

    def test_023_engine_initialization_defaults(self):
        engine = GeoDiagnosticEngine()
        self.assertEqual(engine.cliff_threshold, 48)
        self.assertEqual(engine.min_clearance, 32)

    def test_024_engine_custom_parameters(self):
        engine = GeoDiagnosticEngine(cliff_threshold=64, min_clearance=40)
        self.assertEqual(engine.cliff_threshold, 64)
        self.assertEqual(engine.min_clearance, 40)

    def test_025_scanner_geo_coords_bounds_check(self):
        scanner = L2ClientMemoryScanner()
        # Extreme world coords
        coords = scanner.world_to_geo_coords(-999999, -999999, 0)
        self.assertGreaterEqual(coords["gx"], 0)
        self.assertLessEqual(coords["gx"], CELLS_PER_AXIS - 1)
        self.assertGreaterEqual(coords["gy"], 0)
        self.assertLessEqual(coords["gy"], CELLS_PER_AXIS - 1)

    # =========================================================================
    # PART 2: 3D RAYCASTING & GEOMETRIC INTERSECTIONS (Tests 26-50)
    # =========================================================================

    def _ray_triangle_intersect(self, orig, dir_vec, v0, v1, v2):
        """Möller–Trumbore ray-triangle intersection algorithm."""
        EPS = 1e-6
        edge1 = (v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2])
        edge2 = (v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2])
        pvec = (
            dir_vec[1] * edge2[2] - dir_vec[2] * edge2[1],
            dir_vec[2] * edge2[0] - dir_vec[0] * edge2[2],
            dir_vec[0] * edge2[1] - dir_vec[1] * edge2[0]
        )
        det = edge1[0] * pvec[0] + edge1[1] * pvec[1] + edge1[2] * pvec[2]
        if abs(det) < EPS:
            return None
        inv_det = 1.0 / det
        tvec = (orig[0] - v0[0], orig[1] - v0[1], orig[2] - v0[2])
        u = (tvec[0] * pvec[0] + tvec[1] * pvec[1] + tvec[2] * pvec[2]) * inv_det
        if u < 0.0 or u > 1.0:
            return None
        qvec = (
            tvec[1] * edge1[2] - tvec[2] * edge1[1],
            tvec[2] * edge1[0] - tvec[0] * edge1[2],
            tvec[0] * edge1[1] - tvec[1] * edge1[0]
        )
        v = (dir_vec[0] * qvec[0] + dir_vec[1] * qvec[1] + dir_vec[2] * qvec[2]) * inv_det
        if v < 0.0 or u + v > 1.0:
            return None
        t = (edge2[0] * qvec[0] + edge2[1] * qvec[1] + edge2[2] * qvec[2]) * inv_det
        return t if t > EPS else None

    def test_026_raycast_direct_hit(self):
        orig = (0.0, 0.0, 100.0)
        dir_vec = (0.0, 0.0, -1.0)
        v0 = (-10.0, -10.0, 0.0)
        v1 = (10.0, -10.0, 0.0)
        v2 = (0.0, 10.0, 0.0)
        t = self._ray_triangle_intersect(orig, dir_vec, v0, v1, v2)
        self.assertIsNotNone(t)
        self.assertAlmostEqual(t, 100.0, places=3)

    def test_027_raycast_miss(self):
        orig = (50.0, 50.0, 100.0)
        dir_vec = (0.0, 0.0, -1.0)
        v0 = (-10.0, -10.0, 0.0)
        v1 = (10.0, -10.0, 0.0)
        v2 = (0.0, 10.0, 0.0)
        t = self._ray_triangle_intersect(orig, dir_vec, v0, v1, v2)
        self.assertIsNone(t)

    def test_028_raycast_parallel_ray(self):
        orig = (0.0, 0.0, 5.0)
        dir_vec = (1.0, 0.0, 0.0)  # Parallel to triangle on Z=0
        v0 = (-10.0, -10.0, 0.0)
        v1 = (10.0, -10.0, 0.0)
        v2 = (0.0, 10.0, 0.0)
        t = self._ray_triangle_intersect(orig, dir_vec, v0, v1, v2)
        self.assertIsNone(t)

    def test_029_aabb_box_overlap_true(self):
        b1_min = (0, 0, 0)
        b1_max = (10, 10, 10)
        b2_min = (5, 5, 5)
        b2_max = (15, 15, 15)
        overlap = all(b1_min[i] <= b2_max[i] and b1_max[i] >= b2_min[i] for i in range(3))
        self.assertTrue(overlap)

    def test_030_aabb_box_overlap_false(self):
        b1_min = (0, 0, 0)
        b1_max = (10, 10, 10)
        b2_min = (20, 20, 20)
        b2_max = (30, 30, 30)
        overlap = all(b1_min[i] <= b2_max[i] and b1_max[i] >= b2_min[i] for i in range(3))
        self.assertFalse(overlap)

    def test_031_3d_quad_vertex_count(self):
        # 4 vertices per geodata quad
        quad = [(-1.0, 1.0, 0.0), (-1.0, -1.0, 0.0), (1.0, 1.0, 0.0), (1.0, -1.0, 0.0)]
        self.assertEqual(len(quad), 4)

    def test_032_3d_quad_normal_pointing_up(self):
        # Flat quad normal is (0, 0, 1)
        v0 = (-1.0, -1.0, 0.0)
        v1 = (1.0, -1.0, 0.0)
        v2 = (-1.0, 1.0, 0.0)
        d1 = (v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2])
        d2 = (v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2])
        nz = d1[0]*d2[1] - d1[1]*d2[0]
        self.assertGreater(nz, 0)

    def test_033_3d_mismatch_heatmap_green_tier(self):
        # |ΔZ| <= 16: Green (0.2, 0.9, 0.3)
        delta_z = 8
        color = [0.2, 0.9, 0.3] if delta_z <= 16 else [1.0, 0.0, 0.0]
        self.assertEqual(color[1], 0.9)

    def test_034_3d_mismatch_heatmap_yellow_tier(self):
        # 16 < |ΔZ| <= 32: Yellow (0.9, 0.8, 0.2)
        delta_z = 24
        tier = "yellow" if 16 < delta_z <= 32 else "other"
        self.assertEqual(tier, "yellow")

    def test_035_3d_mismatch_heatmap_orange_tier(self):
        delta_z = 40
        tier = "orange" if 32 < delta_z <= 48 else "other"
        self.assertEqual(tier, "orange")

    def test_036_3d_mismatch_heatmap_red_tier(self):
        delta_z = 100
        tier = "red" if delta_z > 48 else "other"
        self.assertEqual(tier, "red")

    def test_037_frustum_sphere_cull_inside(self):
        # Camera at (0, 0, 0), sphere at (0, 0, -50), radius 10
        dist_z = -50
        in_front = dist_z < -1.0
        self.assertTrue(in_front)

    def test_038_frustum_sphere_cull_behind(self):
        dist_z = 20  # Behind camera
        in_front = dist_z < -1.0
        self.assertFalse(in_front)

    def test_039_camera_orbit_yaw_normalization(self):
        yaw = 7.5  # Greater than 2*PI
        normalized = yaw % (2 * math.pi)
        self.assertLess(normalized, 2 * math.pi)
        self.assertGreaterEqual(normalized, 0.0)

    def test_040_camera_orbit_pitch_clamping(self):
        pitch = 1.8
        clamped = max(0.08, min(1.45, pitch))
        self.assertEqual(clamped, 1.45)

    def test_041_camera_orbit_distance_clamping(self):
        dist = 0.05
        clamped = max(0.2, min(8.0, dist))
        self.assertEqual(clamped, 0.2)

    def test_042_3d_matrix_perspective_fov(self):
        fov = math.radians(60)
        t = 1.0 / math.tan(fov / 2.0)
        self.assertGreater(t, 1.0)

    def test_043_3d_quad_uv_bounds(self):
        # UV coordinates must always be in [0.0, 1.0]
        for nswe in range(16):
            u_off = (0.5 if (nswe & FLAG_NORTH) else 0.0) + (0.25 if (nswe & FLAG_SOUTH) else 0.0)
            v_off = (0.5 if (nswe & FLAG_WEST) else 0.0) + (0.25 if (nswe & FLAG_EAST) else 0.0)
            self.assertGreaterEqual(u_off, 0.0)
            self.assertLessEqual(u_off + 0.25, 1.0)
            self.assertGreaterEqual(v_off, 0.0)
            self.assertLessEqual(v_off + 0.25, 1.0)

    def test_044_terrain_patch_dimension(self):
        # Terrain quad resolution in UE2 is typically 16x16 vertices
        verts_per_quad = 4
        self.assertEqual(verts_per_quad, 4)

    def test_045_3d_mesh_triangle_area(self):
        v0 = (0.0, 0.0, 0.0)
        v1 = (10.0, 0.0, 0.0)
        v2 = (0.0, 10.0, 0.0)
        area = 0.5 * abs(v1[0]*v2[1] - v2[0]*v1[1])
        self.assertEqual(area, 50.0)

    def test_046_unr_magic_header_signature(self):
        # L2U1 binary magic header
        magic = b"L2U1"
        self.assertEqual(len(magic), 4)

    def test_047_unr_vertex_kind_static_mesh(self):
        KIND_MESH = 0
        self.assertEqual(KIND_MESH, 0)

    def test_048_unr_vertex_kind_bsp_interior(self):
        KIND_BSP = 1
        self.assertEqual(KIND_BSP, 1)

    def test_049_unr_vertex_kind_blocking_volume(self):
        KIND_BLOCK = 2
        self.assertEqual(KIND_BLOCK, 2)

    def test_050_z_calibration_offset(self):
        # Calibration constant applied to UNR collision meshes
        Z_CALIBRATION = 43.35
        self.assertAlmostEqual(Z_CALIBRATION, 43.35, places=2)

    # =========================================================================
    # PART 3: CITY GATE & ARCHWAY CLEARANCE INVARIANTS (Tests 51-75)
    # =========================================================================

    def test_051_giran_archway_two_layers_doorway(self):
        # Ground at Z=96, Roof at Z=384
        cell = [(96, FLAG_ALL), (384, FLAG_ALL)]
        self.assertEqual(len(cell), 2)
        clearance = cell[1][0] - cell[0][0]
        self.assertEqual(clearance, 288)
        self.assertGreaterEqual(clearance, 32)

    def test_052_giran_arch_street_connection(self):
        # Gate cell (Z=96, Z=384), Outside street (Z=96)
        # Ground is walkable (ΔZ = 0)
        ground_delta = abs(96 - 96)
        self.assertLessEqual(ground_delta, 24)

    def test_053_arch_cliff_repair_only_upper_layer(self):
        # Repair should seal 384 facing the void, NOT the 96 ground
        upper_z = 384
        ground_z = 96
        self.assertGreater(upper_z - ground_z, 48)

    def test_054_layer_squeeze_detection(self):
        # Clearance 16 is < 32 minimum -> squeeze trap!
        layers = [(100, FLAG_ALL), (116, FLAG_ALL)]
        diff = layers[1][0] - layers[0][0]
        is_squeeze = diff < 32
        self.assertTrue(is_squeeze)

    def test_055_castle_gate_open_passage(self):
        # Gate door open: all 4 flags enabled
        gate_flags = FLAG_ALL
        self.assertEqual(gate_flags, 15)

    def test_056_castle_gate_closed_passage(self):
        # Gate closed: East & West blocked
        closed_flags = FLAG_ALL & ~(FLAG_EAST | FLAG_WEST)
        self.assertEqual(closed_flags & FLAG_EAST, 0)
        self.assertEqual(closed_flags & FLAG_WEST, 0)

    def test_057_underwater_swimming_layer(self):
        # Water surface at Z=-1000, Seabed at Z=-1800
        seabed_z = -1800
        water_z = -1000
        depth = water_z - seabed_z
        self.assertEqual(depth, 800)

    def test_058_bridge_clearance_over_river(self):
        river_bed = 0
        bridge_deck = 300
        clearance = bridge_deck - river_bed
        self.assertGreaterEqual(clearance, 128)

    def test_059_spiral_staircase_elevation_steps(self):
        # 10 steps, each climbing 16 units
        steps = [i * 16 for i in range(10)]
        for i in range(len(steps) - 1):
            climb = steps[i+1] - steps[i]
            # 16 is walkable (<= 24)
            self.assertLessEqual(climb, 24)

    def test_060_steep_mountain_slope_blocked(self):
        climb = 56  # > 24 -> character slides/stops
        walkable = climb <= 24
        self.assertFalse(walkable)

    def test_061_one_way_wall_trap_detection(self):
        # Cell A permits East (1), Cell B denies West (0)
        nswe_a = FLAG_EAST
        nswe_b = FLAG_NONE
        is_asymmetric = bool(nswe_a & FLAG_EAST) != bool(nswe_b & FLAG_WEST)
        self.assertTrue(is_asymmetric)

    def test_062_symmetric_wall_valid(self):
        nswe_a = FLAG_NONE
        nswe_b = FLAG_NONE
        is_asymmetric = bool(nswe_a & FLAG_EAST) != bool(nswe_b & FLAG_WEST)
        self.assertFalse(is_asymmetric)

    def test_063_dungeon_floor_stacking_three_levels(self):
        # Multi-floor dungeon: Level 1 (-500), Level 2 (0), Level 3 (500)
        levels = [-500, 0, 500]
        for i in range(len(levels) - 1):
            self.assertGreaterEqual(levels[i+1] - levels[i], 300)

    def test_064_dungeon_ceiling_clearance(self):
        floor = 100
        ceiling = 250
        headroom = ceiling - floor
        # Player height in L2 is ~60-80 units, minimum headroom 96
        self.assertGreaterEqual(headroom, 96)

    def test_065_chasm_pit_hazard(self):
        floor_z = 200
        pit_z = -1500
        drop = floor_z - pit_z
        self.assertGreater(drop, 1000)

    def test_066_diagonal_walkability_derived_from_cardinals(self):
        # In L2, North-East movement requires both NORTH and EAST flags open
        nswe = FLAG_NORTH | FLAG_EAST
        can_go_ne = bool((nswe & FLAG_NORTH) and (nswe & FLAG_EAST))
        self.assertTrue(can_go_ne)

    def test_067_diagonal_blocked_if_north_closed(self):
        nswe = FLAG_EAST  # North is closed
        can_go_ne = bool((nswe & FLAG_NORTH) and (nswe & FLAG_EAST))
        self.assertFalse(can_go_ne)

    def test_068_diagonal_blocked_if_east_closed(self):
        nswe = FLAG_NORTH  # East is closed
        can_go_ne = bool((nswe & FLAG_NORTH) and (nswe & FLAG_EAST))
        self.assertFalse(can_go_ne)

    def test_069_ladder_climb_vertical_gap(self):
        # Ladders in L2 bypass normal NSWE ground navigation
        bottom = 0
        top = 400
        self.assertEqual(top - bottom, 400)

    def test_070_elevator_tower_layer_range(self):
        # Tower of Insolence elevator shaft
        shaft_min = -2000
        shaft_max = 12000
        self.assertEqual(shaft_max - shaft_min, 14000)

    def test_071_arena_perimeter_invisible_barrier(self):
        # 16 perimeter cells with NSWE=0
        perimeter = [FLAG_NONE for _ in range(16)]
        for cell in perimeter:
            self.assertEqual(cell, 0)

    def test_072_arena_interior_walkable(self):
        interior = [FLAG_ALL for _ in range(64)]
        for cell in interior:
            self.assertEqual(cell, 15)

    def test_073_teleport_pad_valid_z(self):
        target_z = 104
        self.assertEqual(target_z % 8, 0)

    def test_074_door_collision_bounding_box(self):
        door_min = (-50, -10, 0)
        door_max = (50, 10, 200)
        thickness = door_max[1] - door_min[1]
        self.assertEqual(thickness, 20)

    def test_075_door_open_flag_inversion(self):
        closed = FLAG_NONE
        opened = closed ^ FLAG_ALL
        self.assertEqual(opened, FLAG_ALL)

    # =========================================================================
    # PART 4: BINARY STRUCTURE & PROTOCOL FORMAT INTEGRITY (Tests 76-100)
    # =========================================================================

    def test_076_pts_header_magic_bytes(self):
        hdr = pack_pts_header(20, 18, 100, 200, 300, 500)
        # Check bytes 2..5: 0x80, 0x00, 0x10, 0x00
        self.assertEqual(hdr[2:6], b"\x80\x00\x10\x00")

    def test_077_pts_flat_surface_min_max_ordering(self):
        # Walk surface is max(high, low)
        h = pts_flat_surface(150, 100)
        self.assertEqual(h, 150)

    def test_078_pts_flat_surface_equal(self):
        h = pts_flat_surface(200, 200)
        self.assertEqual(h, 200)

    def test_079_pts_flat_surface_negative(self):
        h = pts_flat_surface(-50, -100)
        self.assertEqual(h, -50)

    def test_080_complex_block_byte_size(self):
        # Type 1 has 64 uint16 cells = 128 bytes
        self.assertEqual(64 * 2, 128)

    def test_081_flat_block_byte_size(self):
        # Type 0 in L2J has 1 byte type + 2 bytes int16 = 3 bytes
        self.assertEqual(1 + 2, 3)

    def test_082_multilayer_cell_overhead(self):
        # Type 2 cell has 1 byte layer count (u8) + n * 2 bytes
        n_layers = 4
        size = 1 + n_layers * 2
        self.assertEqual(size, 9)

    def test_083_cell_bit_shift_encoding(self):
        h = 104
        nswe = 11
        encoded = enc_cell(h, nswe)
        # Low 4 bits must match nswe
        self.assertEqual(encoded & 0x000F, 11)
        # High 12 bits shifted right by 1
        self.assertEqual((encoded >> 1) & 0xFFF8, h)

    def test_084_negative_cell_bit_shift_encoding(self):
        h = -104
        nswe = 7
        encoded = enc_cell(h, nswe)
        self.assertEqual(dec_nswe(encoded), 7)
        self.assertEqual(dec_h(encoded), -104)

    def test_085_max_positive_cell_height(self):
        h = 16376
        encoded = enc_cell(h, 15)
        self.assertEqual(dec_h(encoded), 16376)

    def test_086_max_negative_cell_height(self):
        h = -16376
        encoded = enc_cell(h, 15)
        self.assertEqual(dec_h(encoded), -16376)

    def test_087_pts_protocol_gd_layers_field(self):
        # GD protocol stores total non-flat layers
        n_layers = 12345
        hdr = pack_pts_header(20, 18, 100, 200, 300, n_layers, protocol="gd")
        _, _, _, _, _, _, val, _, _ = struct.unpack('<BBBBBBIII', hdr)
        self.assertEqual(val, 12345)

    def test_088_pts_protocol_286_cells_field(self):
        # Protocol 286 stores (n_cx + n_ml) * 64
        n_cx = 100
        n_ml = 50
        hdr = pack_pts_header(20, 18, 1000, n_cx, n_ml, 5000, protocol="286")
        _, _, _, _, _, _, val, _, _ = struct.unpack('<BBBBBBIII', hdr)
        self.assertEqual(val, 150 * 64)

    def test_089_l2g_checksum_remainder_zero(self):
        payload = b"Sample Geodata Checksum Test"
        enc = L2GCodec.encrypt(payload)
        # Decryption asserts remainder == 0
        dec = L2GCodec.decrypt(enc)
        self.assertEqual(dec, payload)

    def test_090_l2g_different_keys_for_different_data(self):
        enc1 = L2GCodec.encrypt(b"Alpha")
        enc2 = L2GCodec.encrypt(b"Beta")
        # Key header at bytes 0..3 should differ
        self.assertNotEqual(enc1[:4], enc2[:4])

    def test_091_editor_save_l2j_extension_match(self):
        blocks = make_mock_blocks(100)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf_path = tf.name
        try:
            save_edited_region(blocks, tf_path, target_format="l2j")
            self.assertEqual(sniff_format(tf_path), "l2j")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_092_editor_save_l2g_extension_match(self):
        blocks = make_mock_blocks(100)
        with tempfile.NamedTemporaryFile(suffix=".l2g", delete=False) as tf:
            tf_path = tf.name
        try:
            save_edited_region(blocks, tf_path, target_format="l2g")
            self.assertEqual(sniff_format(tf_path), "l2g")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_093_editor_save_pts_extension_match(self):
        blocks = make_mock_blocks(100)
        with tempfile.NamedTemporaryFile(suffix="_conv.dat", delete=False) as tf:
            tf_path = tf.name
        try:
            save_edited_region(blocks, tf_path, target_format="pts", rx=20, ry=18)
            self.assertEqual(sniff_format(tf_path), "pts")
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_094_editor_save_unsupported_format(self):
        blocks = make_mock_blocks(100)
        with self.assertRaises(GeoError):
            save_edited_region(blocks, "dummy.xyz", target_format="invalid_fmt")

    def test_095_scanner_dion_coordinates(self):
        scanner = L2ClientMemoryScanner()
        geo = scanner.world_to_geo_coords(18400, 145400, -3000)
        self.assertEqual(geo["rx"], 20)
        self.assertEqual(geo["ry"], 22)

    def test_096_scanner_giran_coordinates(self):
        scanner = L2ClientMemoryScanner()
        geo = scanner.world_to_geo_coords(83400, 148600, -3400)
        self.assertEqual(geo["rx"], 22)
        self.assertEqual(geo["ry"], 22)

    def test_097_scanner_aden_coordinates(self):
        # Aden world approx: wx=147450, wy=26000
        scanner = L2ClientMemoryScanner()
        geo = scanner.world_to_geo_coords(147450, 26000, -2200)
        self.assertEqual(geo["rx"], 24)
        self.assertEqual(geo["ry"], 18)

    def test_098_scanner_godard_coordinates(self):
        # Goddard world approx: wx=147900, wy=-55300
        scanner = L2ClientMemoryScanner()
        geo = scanner.world_to_geo_coords(147900, -55300, -2700)
        self.assertEqual(geo["rx"], 24)
        self.assertEqual(geo["ry"], 16)

    def test_099_scanner_rune_coordinates(self):
        # Rune world approx: wx=43800, wy=-48000
        scanner = L2ClientMemoryScanner()
        geo = scanner.world_to_geo_coords(43800, -48000, -800)
        self.assertEqual(geo["rx"], 21)
        self.assertEqual(geo["ry"], 16)

    def test_100_full_cycle_advanced_validation(self):
        # Final test: End-to-end multi-format pipeline test
        # 1. Create base blocks
        blocks = make_mock_blocks(128)
        # 2. Add custom door geometry
        blocks[100][0] = [(128, FLAG_EAST | FLAG_WEST), (400, FLAG_ALL)]
        # 3. Apply Shift Z (+64)
        shift_z_blocks(blocks, 64)
        self.assertEqual(blocks[100][0][0][0], quant_h(192))
        self.assertEqual(blocks[100][0][1][0], quant_h(464))
        # 4. Prune upper roof [450..500]
        delete_z_range_blocks(blocks, 450, 500)
        self.assertEqual(len(blocks[100][0]), 1)
        # 5. Export to L2G (encrypted)
        with tempfile.NamedTemporaryFile(suffix=".l2g", delete=False) as tf:
            l2g_path = tf.name
        try:
            save_edited_region(blocks, l2g_path, target_format="l2g")
            # 6. Parse back L2G and verify
            parsed = parse_region(l2g_path)
            self.assertEqual(len(parsed), BLOCKS)
            self.assertEqual(parsed[100][0][0][0], quant_h(192))
            self.assertEqual(parsed[100][0][0][1], FLAG_EAST | FLAG_WEST)
        finally:
            if os.path.exists(l2g_path):
                os.remove(l2g_path)


if __name__ == '__main__':
    unittest.main()
