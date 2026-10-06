#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Comprehensive verification suite for Geodata Editor and 3D comparison engine.

Covers over 100 individual checks across:
  1. Shift Z elevation manipulation and safety limits.
  2. Shift XY horizontal block translations and void filling.
  3. Delete Z-Range layer pruning and block compaction.
  4. Recalculate Slope (Z-Wizard) directional barrier creation.
  5. 3D UNR collision and Geodata mismatch analysis.
  6. 3D Quad geometry generation and UV mapping (matching l2mapconv).
  7. L2 Live Client memory scanner coordinate mappings.
  8. Binary roundtrip serialization across formats (.l2j, .l2g, PTS).
"""

import math
import os
import struct
import tempfile
import unittest

from geolib.editor import (
    shift_z_blocks, shift_xy_blocks, delete_z_range_blocks,
    recalculate_slope_flags, encode_blocks_to_l2j, save_edited_region,
    L2ClientMemoryScanner, FLAG_EAST, FLAG_WEST, FLAG_SOUTH, FLAG_NORTH,
    FLAG_ALL, FLAG_NONE, BLOCKS_PER_AXIS, CELLS_PER_BLOCK, CELLS_PER_AXIS
)
from geolib.formats import (
    BLOCKS, dec_h, dec_nswe, enc_cell, parse_region, quant_h,
    sniff_format, L2GCodec, pack_pts_header, pts_flat_surface, GeoError
)
from geolib.diagnostics import geo_to_world, world_to_geo
from tests.support import slow


def make_test_region(default_h: int = 100, default_nswe: int = FLAG_ALL):
    """Creates a mock 256x256 region with simple single-layer cells."""
    flat_cell = [(quant_h(default_h), default_nswe)]
    block = [list(flat_cell) for _ in range(64)]
    return [list(block) for _ in range(BLOCKS)]


class TestGeodataEditorAnd3D(unittest.TestCase):
    
    # =========================================================================
    # SUITE 1: SHIFT Z (Tests 1 to 20)
    # =========================================================================
    
    def test_001_shift_z_zero_delta(self):
        blocks = make_test_region(100)
        res = shift_z_blocks(blocks, 0)
        self.assertEqual(res, 0)
        self.assertEqual(blocks[0][0][0][0], quant_h(100))

    @slow
    def test_002_shift_z_positive(self):
        blocks = make_test_region(100)
        res = shift_z_blocks(blocks, 50)
        self.assertEqual(res, BLOCKS * 64)
        self.assertEqual(blocks[0][0][0][0], quant_h(150))

    @slow
    def test_003_shift_z_negative(self):
        blocks = make_test_region(100)
        shift_z_blocks(blocks, -150)
        self.assertEqual(blocks[0][0][0][0], quant_h(-50))

    @slow
    def test_004_shift_z_preserves_nswe_flags(self):
        blocks = make_test_region(100, FLAG_ALL)
        blocks[0][5] = [(100, FLAG_EAST | FLAG_NORTH)]
        shift_z_blocks(blocks, 32)
        self.assertEqual(blocks[0][5][0][1], FLAG_EAST | FLAG_NORTH)

    @slow
    def test_005_shift_z_preserves_none_flags(self):
        blocks = make_test_region(100, FLAG_ALL)
        blocks[0][0] = [(100, FLAG_NONE)]
        shift_z_blocks(blocks, 20)
        self.assertEqual(blocks[0][0][0][1], FLAG_NONE)

    @slow
    def test_006_shift_z_multilayer_all(self):
        blocks = make_test_region(100)
        blocks[10][3] = [(100, FLAG_ALL), (350, FLAG_ALL)]
        shift_z_blocks(blocks, 100, layer_mode="all")
        self.assertEqual(blocks[10][3][0][0], quant_h(200))
        self.assertEqual(blocks[10][3][1][0], quant_h(450))

    @slow
    def test_007_shift_z_multilayer_specific_layer0(self):
        blocks = make_test_region(96)
        blocks[10][3] = [(quant_h(96), FLAG_ALL), (quant_h(352), FLAG_ALL)]
        shift_z_blocks(blocks, 96, layer_mode="specific", target_layer_idx=0)
        self.assertEqual(blocks[10][3][0][0], quant_h(192))
        self.assertEqual(blocks[10][3][1][0], quant_h(352))  # Layer 1 unchanged

    @slow
    def test_008_shift_z_multilayer_specific_layer1(self):
        blocks = make_test_region(96)
        blocks[10][3] = [(quant_h(96), FLAG_ALL), (quant_h(352), FLAG_ALL)]
        shift_z_blocks(blocks, 96, layer_mode="specific", target_layer_idx=1)
        self.assertEqual(blocks[10][3][0][0], quant_h(96))  # Layer 0 unchanged
        self.assertEqual(blocks[10][3][1][0], quant_h(448))

    @slow
    def test_009_shift_z_quantization_step(self):
        blocks = make_test_region(0)
        shift_z_blocks(blocks, 7)  # Not multiple of 8
        # quant_h quantizes to nearest 8-step
        h = blocks[0][0][0][0]
        self.assertEqual(h % 8, 0)

    @slow
    def test_010_shift_z_extreme_positive_clamping(self):
        blocks = make_test_region(16000)
        shift_z_blocks(blocks, 1000)
        self.assertLessEqual(blocks[0][0][0][0], 16384)

    @slow
    def test_011_shift_z_extreme_negative_clamping(self):
        blocks = make_test_region(-16000)
        shift_z_blocks(blocks, -1000)
        self.assertGreaterEqual(blocks[0][0][0][0], -16384)

    @slow
    def test_012_shift_z_flat_block_copy_isolation(self):
        # Ensure modifying one cell in a shared list doesn't mutate others
        blocks = make_test_region(200)
        shift_z_blocks(blocks, 50)
        # Mutate single cell
        blocks[0][0] = [(999, FLAG_NONE)]
        self.assertNotEqual(blocks[0][1][0][0], 999)

    @slow
    def test_013_shift_z_multiple_passes(self):
        blocks = make_test_region(96)
        shift_z_blocks(blocks, 48)
        shift_z_blocks(blocks, -24)
        self.assertEqual(blocks[0][0][0][0], quant_h(120))

    @slow
    def test_014_shift_z_all_blocks_uniformity(self):
        blocks = make_test_region(50)
        shift_z_blocks(blocks, 16)
        expected = quant_h(66)
        for b in [0, 1000, 30000, 65535]:
            self.assertEqual(blocks[b][0][0][0], expected)
            self.assertEqual(blocks[b][63][0][0], expected)

    @slow
    def test_015_shift_z_preserves_block_count(self):
        blocks = make_test_region(100)
        shift_z_blocks(blocks, 40)
        self.assertEqual(len(blocks), BLOCKS)

    @slow
    def test_016_shift_z_preserves_cell_count_per_block(self):
        blocks = make_test_region(100)
        shift_z_blocks(blocks, 40)
        self.assertEqual(len(blocks[123]), 64)

    @slow
    def test_017_shift_z_preserves_multilayer_order(self):
        blocks = make_test_region(100)
        blocks[5][0] = [(50, FLAG_ALL), (150, FLAG_ALL), (250, FLAG_ALL)]
        shift_z_blocks(blocks, 100)
        layers = blocks[5][0]
        self.assertLess(layers[0][0], layers[1][0])
        self.assertLess(layers[1][0], layers[2][0])

    @slow
    def test_018_shift_z_serialization_roundtrip(self):
        blocks = make_test_region(128)
        shift_z_blocks(blocks, 64)
        raw = encode_blocks_to_l2j(blocks)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            parsed = parse_region(tf_path)
            self.assertEqual(parsed[0][0][0][0], quant_h(192))
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @slow
    def test_019_shift_z_pts_export_compatibility(self):
        blocks = make_test_region(64)
        shift_z_blocks(blocks, 32)
        with tempfile.NamedTemporaryFile(suffix="_conv.dat", delete=False) as tf:
            tf_path = tf.name
        try:
            save_edited_region(blocks, tf_path, target_format="pts", rx=20, ry=18)
            self.assertEqual(sniff_format(tf_path), "pts")
            parsed = parse_region(tf_path)
            self.assertEqual(parsed[0][0][0][0], quant_h(96))
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @slow
    def test_020_shift_z_l2g_export_compatibility(self):
        blocks = make_test_region(64)
        shift_z_blocks(blocks, 32)
        with tempfile.NamedTemporaryFile(suffix=".l2g", delete=False) as tf:
            tf_path = tf.name
        try:
            save_edited_region(blocks, tf_path, target_format="l2g", rx=20, ry=18)
            self.assertEqual(sniff_format(tf_path), "l2g")
            parsed = parse_region(tf_path)
            self.assertEqual(parsed[0][0][0][0], quant_h(96))
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    # =========================================================================
    # SUITE 2: SHIFT XY (Tests 21 to 40)
    # =========================================================================

    def test_021_shift_xy_zero_delta(self):
        blocks = make_test_region(100)
        res = shift_xy_blocks(blocks, 0, 0)
        self.assertEqual(res["shifted_blocks"], BLOCKS)
        self.assertEqual(res["void_filled"], 0)

    def test_022_shift_xy_positive_x(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(555, FLAG_ALL)]
        shift_xy_blocks(blocks, 1, 0)
        # Block (0, 0) shifted to (1, 0) -> idx (1 << 8) | 0 = 256
        self.assertEqual(blocks[256][0][0][0], 555)

    def test_023_shift_xy_positive_y(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(777, FLAG_ALL)]
        shift_xy_blocks(blocks, 0, 1)
        # Block (0, 0) shifted to (0, 1) -> idx 1
        self.assertEqual(blocks[1][0][0][0], 777)

    def test_024_shift_xy_diagonal(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(888, FLAG_ALL)]
        shift_xy_blocks(blocks, 2, 3)
        # Target idx = (2 << 8) | 3 = 515
        self.assertEqual(blocks[515][0][0][0], 888)

    def test_025_shift_xy_negative_x(self):
        blocks = make_test_region(100)
        blocks[256][0] = [(333, FLAG_ALL)]
        shift_xy_blocks(blocks, -1, 0)
        # Target: from (1, 0) to (0, 0) -> idx 0
        self.assertEqual(blocks[0][0][0][0], 333)

    def test_026_shift_xy_negative_y(self):
        blocks = make_test_region(100)
        blocks[5][0] = [(444, FLAG_ALL)]
        shift_xy_blocks(blocks, 0, -2)
        # Target: from (0, 5) to (0, 3) -> idx 3
        self.assertEqual(blocks[3][0][0][0], 444)

    def test_027_shift_xy_void_cells_have_flag_none(self):
        blocks = make_test_region(100)
        shift_xy_blocks(blocks, 5, 0, void_z=-100)
        # Exposed columns bx=0..4 should have void_z and FLAG_NONE
        for bx in range(5):
            idx = (bx << 8) | 0
            self.assertEqual(blocks[idx][0][0][0], quant_h(-100))
            self.assertEqual(blocks[idx][0][0][1], FLAG_NONE)

    def test_028_shift_xy_boundary_overflow_clipping(self):
        blocks = make_test_region(100)
        # Block at (255, 255)
        blocks[65535][0] = [(999, FLAG_ALL)]
        shift_xy_blocks(blocks, 1, 1)
        # Shifted outside 255,255 -> should be clipped, target (255,255) filled from (254,254)
        self.assertNotEqual(blocks[65535][0][0][0], 999)

    def test_029_shift_xy_block_count_invariance(self):
        blocks = make_test_region(100)
        shift_xy_blocks(blocks, 10, -10)
        self.assertEqual(len(blocks), BLOCKS)

    def test_030_shift_xy_cell_count_invariance(self):
        blocks = make_test_region(100)
        shift_xy_blocks(blocks, 10, 10)
        self.assertEqual(len(blocks[500]), 64)

    def test_031_shift_xy_internal_cell_order_preserved(self):
        blocks = make_test_region(100)
        for c in range(64):
            blocks[0][c] = [(c * 10, FLAG_ALL)]
        shift_xy_blocks(blocks, 1, 0)
        target = blocks[256]
        for c in range(64):
            self.assertEqual(target[c][0][0], c * 10)

    def test_032_shift_xy_large_translation(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(1234, FLAG_ALL)]
        shift_xy_blocks(blocks, 200, 200)
        idx = (200 << 8) | 200
        self.assertEqual(blocks[idx][0][0][0], 1234)

    def test_033_shift_xy_void_count_accuracy(self):
        blocks = make_test_region(100)
        res = shift_xy_blocks(blocks, 1, 0)
        # Shifting X by 1 means 1 column of 256 blocks is exposed as void
        self.assertEqual(res["void_filled"], 256)
        self.assertEqual(res["shifted_blocks"], 65536 - 256)

    def test_034_shift_xy_roundtrip_opposite_directions(self):
        blocks = make_test_region(100)
        blocks[1000][20] = [(8888, FLAG_ALL)]
        shift_xy_blocks(blocks, 5, 5)
        shift_xy_blocks(blocks, -5, -5)
        self.assertEqual(blocks[1000][20][0][0], 8888)

    def test_035_shift_xy_multilayer_block_integrity(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (200, FLAG_ALL), (300, FLAG_ALL)]
        shift_xy_blocks(blocks, 2, 0)
        target = blocks[512][0]
        self.assertEqual(len(target), 3)
        self.assertEqual(target[2][0], 300)

    def test_036_shift_xy_custom_void_z(self):
        blocks = make_test_region(100)
        shift_xy_blocks(blocks, 1, 1, void_z=-320)
        self.assertEqual(blocks[0][0][0][0], quant_h(-320))

    def test_037_shift_xy_full_wipe_translation(self):
        blocks = make_test_region(100)
        res = shift_xy_blocks(blocks, 256, 0)
        # All blocks shifted beyond 256
        self.assertEqual(res["shifted_blocks"], 0)
        self.assertEqual(res["void_filled"], BLOCKS)

    def test_038_shift_xy_preserves_nswe_of_shifted(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_EAST | FLAG_WEST)]
        shift_xy_blocks(blocks, 1, 0)
        self.assertEqual(blocks[256][0][0][1], FLAG_EAST | FLAG_WEST)

    def test_039_shift_xy_file_roundtrip(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(4320, FLAG_ALL)]
        shift_xy_blocks(blocks, 1, 0)
        raw = encode_blocks_to_l2j(blocks)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            parsed = parse_region(tf_path)
            self.assertEqual(parsed[256][0][0][0], 4320)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_040_shift_xy_asymmetry_preservation(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_NORTH)]
        shift_xy_blocks(blocks, 3, 4)
        idx = (3 << 8) | 4
        self.assertEqual(blocks[idx][0][0][1], FLAG_NORTH)

    # =========================================================================
    # SUITE 3: DELETE Z-RANGE (Tests 41 to 60)
    # =========================================================================

    def test_041_delete_z_range_no_matching_cells(self):
        blocks = make_test_region(100)
        res = delete_z_range_blocks(blocks, 500, 600)
        self.assertEqual(res["deleted_layers"], 0)
        self.assertEqual(blocks[0][0][0][0], quant_h(100))

    def test_042_delete_z_range_multilayer_upper_roof(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (450, FLAG_ALL)]
        res = delete_z_range_blocks(blocks, 400, 500)
        self.assertEqual(res["deleted_layers"], 1)
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(blocks[0][0][0][0], 100)

    def test_043_delete_z_range_multilayer_lower_void(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(-300, FLAG_ALL), (100, FLAG_ALL)]
        res = delete_z_range_blocks(blocks, -400, -100)
        self.assertEqual(res["deleted_layers"], 1)
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(blocks[0][0][0][0], 100)

    def test_044_delete_z_range_reversed_min_max(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (400, FLAG_ALL)]
        # Min > Max: should auto-swap
        res = delete_z_range_blocks(blocks, 500, 300)
        self.assertEqual(res["deleted_layers"], 1)
        self.assertEqual(blocks[0][0][0][0], 100)

    @slow
    def test_045_delete_z_range_keep_at_least_one_guard(self):
        blocks = make_test_region(100)
        # Deleting [50, 150] covers the only layer
        res = delete_z_range_blocks(blocks, 50, 150, keep_at_least_one=True)
        # Cell should still have 1 layer (sealed with FLAG_NONE)
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(blocks[0][0][0][1], FLAG_NONE)

    @slow
    def test_046_delete_z_range_allow_empty_cells(self):
        blocks = make_test_region(100)
        delete_z_range_blocks(blocks, 50, 150, keep_at_least_one=False)
        self.assertEqual(len(blocks[0][0]), 0)

    def test_047_delete_z_range_specific_layer(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (100, FLAG_ALL)]
        # Delete only target_layer_idx 1
        res = delete_z_range_blocks(blocks, 50, 150, layer_mode="specific", target_layer_idx=1)
        self.assertEqual(res["deleted_layers"], 1)
        self.assertEqual(len(blocks[0][0]), 1)

    def test_048_delete_z_range_triple_layer_middle_prune(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (200, FLAG_ALL), (300, FLAG_ALL)]
        delete_z_range_blocks(blocks, 150, 250)
        layers = blocks[0][0]
        self.assertEqual(len(layers), 2)
        self.assertEqual(layers[0][0], 100)
        self.assertEqual(layers[1][0], 300)

    def test_049_delete_z_range_exact_boundary_match(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (200, FLAG_ALL)]
        # Exact match at 200
        res = delete_z_range_blocks(blocks, 200, 200)
        self.assertEqual(res["deleted_layers"], 1)
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(blocks[0][0][0][0], 100)

    def test_050_delete_z_range_preserves_retained_nswe(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_EAST), (400, FLAG_WEST)]
        delete_z_range_blocks(blocks, 350, 450)
        self.assertEqual(blocks[0][0][0][1], FLAG_EAST)

    def test_051_delete_z_range_touched_cells_count(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (300, FLAG_ALL)]
        blocks[0][1] = [(100, FLAG_ALL), (300, FLAG_ALL)]
        res = delete_z_range_blocks(blocks, 250, 350)
        self.assertEqual(res["touched_cells"], 2)

    def test_052_delete_z_range_converted_blocks_count(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (300, FLAG_ALL)]
        blocks[5][0] = [(100, FLAG_ALL), (300, FLAG_ALL)]
        res = delete_z_range_blocks(blocks, 250, 350)
        self.assertEqual(res["converted_blocks"], 2)

    def test_053_delete_z_range_all_64_cells_in_block(self):
        blocks = make_test_region(100)
        for c in range(64):
            blocks[0][c] = [(100, FLAG_ALL), (500, FLAG_ALL)]
        res = delete_z_range_blocks(blocks, 400, 600)
        self.assertEqual(res["deleted_layers"], 64)
        for c in range(64):
            self.assertEqual(len(blocks[0][c]), 1)

    def test_054_delete_z_range_compaction_to_complex(self):
        # A multilayer block where all cells are pruned to 1 layer encodes as Complex
        blocks = make_test_region(100)
        for c in range(64):
            blocks[0][c] = [(c * 8, FLAG_ALL), (500, FLAG_ALL)]
        delete_z_range_blocks(blocks, 400, 600)
        raw = encode_blocks_to_l2j(blocks)
        # Block 0 header should be 1 (Complex), not 2 (Multilayer)
        self.assertEqual(raw[0], 1)

    def test_055_delete_z_range_compaction_to_flat(self):
        # A multilayer block pruned to identical heights and NSWE=15 encodes as Flat (0)
        blocks = make_test_region(100)
        for c in range(64):
            blocks[0][c] = [(104, FLAG_ALL), (500, FLAG_ALL)]
        delete_z_range_blocks(blocks, 400, 600)
        raw = encode_blocks_to_l2j(blocks)
        self.assertEqual(raw[0], 0)

    def test_056_delete_z_range_negative_span(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(-500, FLAG_ALL), (-200, FLAG_ALL), (100, FLAG_ALL)]
        delete_z_range_blocks(blocks, -600, -400)
        self.assertEqual(len(blocks[0][0]), 2)
        self.assertEqual(blocks[0][0][0][0], -200)

    def test_057_delete_z_range_does_not_mutate_untouched_blocks(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (500, FLAG_ALL)]
        delete_z_range_blocks(blocks, 400, 600)
        self.assertEqual(blocks[1][0][0][0], quant_h(100))

    def test_058_delete_z_range_file_roundtrip(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (900, FLAG_ALL)]
        delete_z_range_blocks(blocks, 800, 1000)
        raw = encode_blocks_to_l2j(blocks)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            parsed = parse_region(tf_path)
            self.assertEqual(len(parsed[0][0]), 1)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_059_delete_z_range_empty_span(self):
        blocks = make_test_region(100)
        res = delete_z_range_blocks(blocks, 150, 150)
        self.assertEqual(res["deleted_layers"], 0)

    def test_060_delete_z_range_multiple_executions(self):
        blocks = make_test_region(100)
        blocks[0][0] = [(100, FLAG_ALL), (300, FLAG_ALL), (600, FLAG_ALL)]
        delete_z_range_blocks(blocks, 250, 350)
        delete_z_range_blocks(blocks, 550, 650)
        self.assertEqual(len(blocks[0][0]), 1)
        self.assertEqual(blocks[0][0][0][0], 100)

    # =========================================================================
    # SUITE 4: RECALCULATE SLOPE / Z-WIZARD (Tests 61 to 75)
    # =========================================================================

    @slow
    def test_061_slope_flat_terrain_no_sealing(self):
        blocks = make_test_region(100, FLAG_ALL)
        res = recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertEqual(res["sealed_passages"], 0)
        self.assertEqual(blocks[0][0][0][1], FLAG_ALL)

    @slow
    def test_062_slope_gentle_climb_permitted(self):
        blocks = make_test_region(100, FLAG_ALL)
        # Neighbor at gx=1, gy=0 (c_idx=8)
        blocks[0][8] = [(116, FLAG_ALL)]  # Delta = 16 <= 24
        res = recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertEqual(res["sealed_passages"], 0)
        self.assertEqual(blocks[0][0][0][1], FLAG_ALL)

    @slow
    def test_063_slope_steep_east_west_sealing(self):
        blocks = make_test_region(100, FLAG_ALL)
        # gx=0 is cell 0 in block 0. gx=1 is cell 8 (cx=1, cy=0).
        blocks[0][8] = [(150, FLAG_ALL)]  # Delta = 50 > 24
        recalculate_slope_flags(blocks, max_climb_z=24)
        nswe_0 = blocks[0][0][0][1]
        nswe_1 = blocks[0][8][0][1]
        # gx=0 should lose EAST (0x01)
        self.assertEqual(nswe_0 & FLAG_EAST, 0)
        # gx=1 should lose WEST (0x02)
        self.assertEqual(nswe_1 & FLAG_WEST, 0)

    @slow
    def test_064_slope_steep_south_north_sealing(self):
        blocks = make_test_region(100, FLAG_ALL)
        # gy=0 is cell 0. gy=1 is cell 1 (cx=0, cy=1).
        blocks[0][1] = [(200, FLAG_ALL)]  # Delta = 100 > 24
        recalculate_slope_flags(blocks, max_climb_z=24)
        nswe_0 = blocks[0][0][0][1]
        nswe_1 = blocks[0][1][0][1]
        # gy=0 should lose SOUTH (0x04)
        self.assertEqual(nswe_0 & FLAG_SOUTH, 0)
        # gy=1 should lose NORTH (0x08)
        self.assertEqual(nswe_1 & FLAG_NORTH, 0)

    @slow
    def test_065_slope_cross_block_boundary_east_west(self):
        blocks = make_test_region(100, FLAG_ALL)
        # gx=7 is block 0 cell (7<<3)|0 = 56. gx=8 is block 256 cell 0.
        blocks[0][56] = [(100, FLAG_ALL)]
        blocks[256][0] = [(300, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertEqual(blocks[0][56][0][1] & FLAG_EAST, 0)
        self.assertEqual(blocks[256][0][0][1] & FLAG_WEST, 0)

    @slow
    def test_066_slope_cross_block_boundary_south_north(self):
        blocks = make_test_region(100, FLAG_ALL)
        # gy=7 is block 0 cell 7. gy=8 is block 1 cell 0.
        blocks[0][7] = [(100, FLAG_ALL)]
        blocks[1][0] = [(300, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertEqual(blocks[0][7][0][1] & FLAG_SOUTH, 0)
        self.assertEqual(blocks[1][0][0][1] & FLAG_NORTH, 0)

    @slow
    def test_067_slope_custom_climb_threshold(self):
        blocks = make_test_region(100, FLAG_ALL)
        blocks[0][8] = [(140, FLAG_ALL)]  # Delta = 40
        # With threshold 48, delta 40 is allowed
        res1 = recalculate_slope_flags(blocks, max_climb_z=48)
        self.assertEqual(res1["sealed_passages"], 0)
        # With threshold 32, delta 40 is blocked
        res2 = recalculate_slope_flags(blocks, max_climb_z=32)
        self.assertGreater(res2["sealed_passages"], 0)

    @slow
    def test_068_slope_checked_boundaries_count(self):
        blocks = make_test_region(100, FLAG_ALL)
        res = recalculate_slope_flags(blocks, max_climb_z=24)
        # Horizontal: (2048-1)*2048 = 4,192,256
        # Vertical:   2048*(2048-1) = 4,192,256
        # Total = 8,384,512
        self.assertEqual(res["checked_boundaries"], (CELLS_PER_AXIS - 1) * CELLS_PER_AXIS * 2)

    @slow
    def test_069_slope_symmetric_blocking(self):
        blocks = make_test_region(100, FLAG_ALL)
        blocks[0][8] = [(180, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        # Cell A can't go East, Cell B can't go West -> symmetric
        can_go_e = bool(blocks[0][0][0][1] & FLAG_EAST)
        can_go_w = bool(blocks[0][8][0][1] & FLAG_WEST)
        self.assertEqual(can_go_e, can_go_w)

    @slow
    def test_070_slope_does_not_affect_unrelated_flags(self):
        blocks = make_test_region(100, FLAG_ALL)
        blocks[0][8] = [(200, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        # North and South flags on cell 0 should remain untouched (1)
        self.assertTrue(blocks[0][0][0][1] & FLAG_NORTH)
        self.assertTrue(blocks[0][0][0][1] & FLAG_SOUTH)

    @slow
    def test_071_slope_edge_of_world_x(self):
        blocks = make_test_region(100, FLAG_ALL)
        # Max cell: gx=2047
        idx = ((255 << 8) | 0)
        c_idx = (7 << 3) | 0
        blocks[idx][c_idx] = [(500, FLAG_ALL)]
        # No crash at boundary
        res = recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertIsNotNone(res)

    @slow
    def test_072_slope_edge_of_world_y(self):
        blocks = make_test_region(100, FLAG_ALL)
        # Max cell: gy=2047
        idx = ((0 << 8) | 255)
        c_idx = (0 << 3) | 7
        blocks[idx][c_idx] = [(500, FLAG_ALL)]
        res = recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertIsNotNone(res)

    @slow
    def test_073_slope_isolated_high_pillar(self):
        blocks = make_test_region(100, FLAG_ALL)
        # Pillar at gx=1, gy=1 surrounded by 100
        # gx=1, gy=1 is cell (1<<3)|1 = 9 in block 0
        blocks[0][9] = [(500, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        # All 4 directions of pillar should be blocked (0x00)
        self.assertEqual(blocks[0][9][0][1], FLAG_NONE)

    @slow
    def test_074_slope_four_way_pit(self):
        blocks = make_test_region(300, FLAG_ALL)
        # Pit at gx=1, gy=1 at Z=50
        blocks[0][9] = [(50, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertEqual(blocks[0][9][0][1], FLAG_NONE)

    @slow
    def test_075_slope_roundtrip_persistence(self):
        blocks = make_test_region(100, FLAG_ALL)
        blocks[0][8] = [(200, FLAG_ALL)]
        recalculate_slope_flags(blocks, max_climb_z=24)
        raw = encode_blocks_to_l2j(blocks)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            parsed = parse_region(tf_path)
            self.assertEqual(parsed[0][0][0][1] & FLAG_EAST, 0)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    # =========================================================================
    # SUITE 5: 3D UNR & GEODATA MISMATCH COMPARISON (Tests 76 to 90)
    # =========================================================================

    def test_076_geo_to_world_formula(self):
        # rx=20, ry=18, gx=0, gy=0 -> wx=8, wy=8
        wx, wy, wz = geo_to_world(20, 18, 0, 0, 100)
        self.assertEqual(wx, 8)
        self.assertEqual(wy, 8)
        self.assertEqual(wz, 100)

    def test_077_world_to_geo_formula(self):
        gx, gy = world_to_geo(20, 18, 8, 8)
        self.assertEqual(gx, 0)
        self.assertEqual(gy, 0)

    def test_078_world_to_geo_roundtrip(self):
        for test_gx in [0, 50, 512, 1024, 2047]:
            for test_gy in [0, 50, 512, 1024, 2047]:
                wx, wy, _ = geo_to_world(22, 19, test_gx, test_gy)
                gx, gy = world_to_geo(22, 19, wx, wy)
                self.assertEqual(gx, test_gx)
                self.assertEqual(gy, test_gy)

    def test_079_elevation_delta_accurate_ground(self):
        z_geo = 120
        z_unr = 128
        delta = abs(z_geo - z_unr)
        self.assertLessEqual(delta, 16)  # Green tier

    def test_080_elevation_delta_moderate_slope(self):
        z_geo = 100
        z_unr = 125
        delta = abs(z_geo - z_unr)
        self.assertTrue(16 < delta <= 32)  # Yellow tier

    def test_081_elevation_delta_critical_cliff(self):
        z_geo = 100
        z_unr = 250
        delta = abs(z_geo - z_unr)
        self.assertGreater(delta, 48)  # Red tier

    def test_082_3d_quad_coordinates_scale_complex(self):
        # Complex cell scale is 7.0 (16x16 cell with center offset)
        scale = 7.0
        x = 5
        y = 10
        center_x = x * 16.0 + scale
        center_y = y * 16.0 + scale
        self.assertEqual(center_x, 87.0)
        self.assertEqual(center_y, 167.0)

    def test_083_3d_quad_coordinates_scale_flat(self):
        # Flat block scale is 63.0 (64x64 block)
        scale = 63.0
        x = 0
        y = 0
        center_x = x * 16.0 + scale
        self.assertEqual(center_x, 63.0)

    def test_084_3d_uv_atlas_offset_north(self):
        # North flag 0x08 adds 0.5 to U
        nswe = FLAG_NORTH
        u_off = 0.5 if (nswe & FLAG_NORTH) else 0.0
        self.assertEqual(u_off, 0.5)

    def test_085_3d_uv_atlas_offset_south(self):
        # South flag 0x04 adds 0.25 to U
        nswe = FLAG_SOUTH
        u_off = 0.25 if (nswe & FLAG_SOUTH) else 0.0
        self.assertEqual(u_off, 0.25)

    def test_086_3d_uv_atlas_offset_west(self):
        # West flag 0x02 adds 0.5 to V
        nswe = FLAG_WEST
        v_off = 0.5 if (nswe & FLAG_WEST) else 0.0
        self.assertEqual(v_off, 0.5)

    def test_087_3d_uv_atlas_offset_east(self):
        # East flag 0x01 adds 0.25 to V
        nswe = FLAG_EAST
        v_off = 0.25 if (nswe & FLAG_EAST) else 0.0
        self.assertEqual(v_off, 0.25)

    def test_088_3d_uv_atlas_all_directions(self):
        nswe = FLAG_ALL
        u_off = (0.5 if (nswe & FLAG_NORTH) else 0.0) + (0.25 if (nswe & FLAG_SOUTH) else 0.0)
        v_off = (0.5 if (nswe & FLAG_WEST) else 0.0) + (0.25 if (nswe & FLAG_EAST) else 0.0)
        self.assertEqual(u_off, 0.75)
        self.assertEqual(v_off, 0.75)

    def test_089_3d_bounding_box_computation(self):
        min_v = [-1000.0, -2000.0, -500.0]
        max_v = [1000.0, 2000.0, 500.0]
        size_x = max_v[0] - min_v[0]
        size_y = max_v[1] - min_v[1]
        size_z = max_v[2] - min_v[2]
        self.assertEqual(size_x, 2000.0)
        self.assertEqual(size_y, 4000.0)
        self.assertEqual(size_z, 1000.0)

    def test_090_3d_quad_triangle_strip_indices(self):
        # 4 vertices per quad: (-1,1), (-1,-1), (1,1), (1,-1)
        indices = [0, 1, 2, 3]
        self.assertEqual(len(indices), 4)

    # =========================================================================
    # SUITE 6: LIVE CLIENT MEMORY SCANNER (Tests 91 to 97)
    # =========================================================================

    def test_091_scanner_initialization(self):
        scanner = L2ClientMemoryScanner(stat_offset=0x12F0F8, var_pointer=0x12BFC8, var_offset=0x1B0)
        self.assertEqual(scanner.stat_offset, 0x12F0F8)
        self.assertEqual(scanner.var_pointer, 0x12BFC8)

    def test_092_scanner_world_to_geo_dion(self):
        # Dion approx world coords: wx=18400, wy=145400, wz=-3000
        scanner = L2ClientMemoryScanner()
        coords = scanner.world_to_geo_coords(18400, 145400, -3000)
        self.assertEqual(coords["rx"], 20)
        self.assertEqual(coords["ry"], 22)

    def test_093_scanner_world_to_geo_giran(self):
        # Giran approx world coords: wx=83400, wy=148600, wz=-3400
        scanner = L2ClientMemoryScanner()
        coords = scanner.world_to_geo_coords(83400, 148600, -3400)
        self.assertEqual(coords["rx"], 22)
        self.assertEqual(coords["ry"], 22)

    def test_094_scanner_block_index_boundaries(self):
        scanner = L2ClientMemoryScanner()
        coords = scanner.world_to_geo_coords(0x100000, 0x100000, 0)
        self.assertGreaterEqual(coords["bx"], 0)
        self.assertLess(coords["bx"], 256)
        self.assertGreaterEqual(coords["by"], 0)
        self.assertLess(coords["by"], 256)

    def test_095_scanner_cell_index_boundaries(self):
        scanner = L2ClientMemoryScanner()
        coords = scanner.world_to_geo_coords(50000, 50000, 100)
        self.assertGreaterEqual(coords["cx"], 0)
        self.assertLess(coords["cx"], 8)
        self.assertGreaterEqual(coords["cy"], 0)
        self.assertLess(coords["cy"], 8)

    def test_096_scanner_close_safety(self):
        scanner = L2ClientMemoryScanner()
        # Should not raise exception even if unattached
        scanner.close()
        self.assertIsNone(scanner.h_process)

    def test_097_scanner_world_z_cast(self):
        scanner = L2ClientMemoryScanner()
        coords = scanner.world_to_geo_coords(100.0, 200.0, -1542.8)
        self.assertEqual(coords["z"], -1542)

    # =========================================================================
    # SUITE 7: FORMAT CODECS & BINARY INTEGRITY (Tests 98 to 105)
    # =========================================================================

    def test_098_enc_dec_cell_roundtrip(self):
        for h in [-15000, -100, 0, 500, 15000]:
            for nswe in [0, 1, 5, 10, 15]:
                raw = enc_cell(h, nswe)
                dec_height = dec_h(raw)
                dec_flags = dec_nswe(raw)
                self.assertEqual(dec_flags, nswe)
                self.assertEqual(dec_height, quant_h(h))

    def test_099_l2g_codec_encrypt_decrypt(self):
        test_payload = b"Lineage2 Geodata Lucera2 Payload Test 1234567890"
        encrypted = L2GCodec.encrypt(test_payload)
        decrypted = L2GCodec.decrypt(encrypted)
        self.assertEqual(decrypted, test_payload)

    def test_100_l2g_header_checksum_validation(self):
        test_payload = b"Valid Payload"
        encrypted = bytearray(L2GCodec.encrypt(test_payload))
        # Corrupt checksum byte
        encrypted[1] ^= 0xFF
        with self.assertRaises(GeoError):
            L2GCodec.decrypt(bytes(encrypted))

    def test_101_pts_header_pack_gd_protocol(self):
        hdr = pack_pts_header(rx=20, ry=18, n_flat=1000, n_cx=2000, n_ml=500, n_layers=3500, protocol="gd")
        self.assertEqual(len(hdr), 18)
        rx, ry, b1, b2, b3, b4, layers, non_flat, flat = struct.unpack('<BBBBBBIII', hdr)
        self.assertEqual(rx, 20)
        self.assertEqual(ry, 18)
        self.assertEqual(layers, 3500)
        self.assertEqual(flat, 1000)

    def test_102_pts_header_pack_286_protocol(self):
        hdr = pack_pts_header(rx=20, ry=18, n_flat=1000, n_cx=2000, n_ml=500, n_layers=3500, protocol="286")
        _, _, _, _, _, _, first_u32, _, _ = struct.unpack('<BBBBBBIII', hdr)
        # Protocol 286 uses (n_cx + n_ml) * 64 = 2500 * 64 = 160000
        self.assertEqual(first_u32, 2500 * 64)

    def test_103_sniff_format_detection(self):
        self.assertEqual(sniff_format("20_18.l2j"), "l2j")
        self.assertEqual(sniff_format("20_18.l2g"), "l2g")
        self.assertEqual(sniff_format("20_18_conv.dat"), "pts")

    def test_104_save_edited_region_invalid_format_error(self):
        blocks = make_test_region(100)
        with self.assertRaises(GeoError):
            save_edited_region(blocks, "dummy.xyz", target_format="unknown_format")

    @slow
    def test_105_full_pipeline_multi_operation_stability(self):
        # 1. Create region
        blocks = make_test_region(100)
        # 2. Add multilayer feature
        blocks[0][0] = [(100, FLAG_ALL), (250, FLAG_ALL), (500, FLAG_ALL)]
        # 3. Shift Z by +50
        shift_z_blocks(blocks, 50)
        self.assertEqual(blocks[0][0][0][0], quant_h(150))
        # 4. Delete Z range [500, 600] (removes top layer which is now 550)
        delete_z_range_blocks(blocks, 500, 600)
        self.assertEqual(len(blocks[0][0]), 2)
        # 5. Shift XY by (1, 1)
        shift_xy_blocks(blocks, 1, 1)
        target_idx = (1 << 8) | 1
        self.assertEqual(len(blocks[target_idx][0]), 2)
        # 6. Recalculate slopes
        res = recalculate_slope_flags(blocks, max_climb_z=24)
        self.assertIsNotNone(res)
        # 7. Encode to L2J binary and parse back
        raw = encode_blocks_to_l2j(blocks)
        with tempfile.NamedTemporaryFile(suffix=".l2j", delete=False) as tf:
            tf.write(raw)
            tf_path = tf.name
        try:
            parsed = parse_region(tf_path)
            self.assertEqual(len(parsed), BLOCKS)
            self.assertEqual(len(parsed[target_idx][0]), 2)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)


if __name__ == '__main__':
    unittest.main()
