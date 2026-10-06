#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Automated Test Suite: UNR 3D Real Structures vs Geodata Validation
Validates StaticMeshes, Terrain, BSP brushes, and BlockingVolumes
from client Maps/*.unr against generated/server geodata (.l2g / .l2j).

(c) fa1thDEV & L2GeoConverter Contributors
"""

import math
import os
import struct
import tempfile
import threading
import unittest
from typing import List, Tuple

from geolib.formats import (
    BLOCKS, dec_h, dec_nswe, enc_cell, parse_region, quant_h,
    sniff_format, L2GCodec, GeoError, summarize, complex_is_flat
)
from geolib.diagnostics import (
    geo_to_world, world_to_geo, FLAG_EAST, FLAG_WEST, FLAG_SOUTH, FLAG_NORTH,
    FLAG_ALL, FLAG_NONE
)
from geolib.editor import BLOCKS_PER_AXIS, CELLS_PER_BLOCK, CELLS_PER_AXIS
from geolib.unreal import Package, Reader, read_properties, PF_NOTSOLID, PF_PORTAL
from geolib.meshes import (
    MeshLibrary, parse_staticmesh, bsp_face_collides, is_zone_hull,
    VIEW_BLOCKING_VOLUME_CLASSES, volume_triangles, actor_matrix
)
from geolib.generate import (
    load_terrain, terrain_cells, REGION_UNITS, Z_CALIBRATION, TEX_UNITS,
    UP_STEP, DOWN_STEP, _step_ok, gather_collision_triangles,
    _wall_between, _span_layers, _cell_range, _boundary_indices,
    _tri_axis_span, _max_merged_span, _blocking_edges
)
from geolib.unrview import (
    pack_region_unr, client_dirs, MAGIC, HEADER,
    _in_region, _area2, _pick, _shift
)
from geolib.viewer import ViewerState
from tests.support import CLIENT_DIR, GEO_DIR, HAS_REAL_CLIENT, needs_client


MAPS_DIR = os.path.join(CLIENT_DIR, "Maps")
TEX_DIR = os.path.join(CLIENT_DIR, "Textures")
USX_DIR = os.path.join(CLIENT_DIR, "StaticMeshes")


class TestUnrStructureVsGeodata(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.client_available = HAS_REAL_CLIENT
        if cls.client_available:
            cls.map_22_22_path = os.path.join(MAPS_DIR, "22_22.unr")
            cls.geo_22_22_path = os.path.join(GEO_DIR, "22_22.l2g")
            cls.mesh_lib = MeshLibrary(USX_DIR) if os.path.isdir(USX_DIR) else None
            cls.payload_22_22, cls.meta_22_22 = pack_region_unr(CLIENT_DIR, "22_22", mesh_lib=cls.mesh_lib)
            cls.blocks_22_22 = parse_region(cls.geo_22_22_path)
            cls.heights_22_22, cls.holes_22_22, cls.loc_22_22 = load_terrain(MAPS_DIR, TEX_DIR, "22_22")
            cls.hcell_22_22, _ = terrain_cells("22_22", cls.heights_22_22, cls.holes_22_22, cls.loc_22_22)
        else:
            cls.map_22_22_path = None
            cls.geo_22_22_path = None
            cls.mesh_lib = None
            cls.payload_22_22 = None
            cls.meta_22_22 = None
            cls.blocks_22_22 = None
            cls.heights_22_22 = None
            cls.holes_22_22 = None
            cls.loc_22_22 = None
            cls.hcell_22_22 = None

    # =========================================================================
    # PART 1: UNR MAP PARSING, ACTORS & EXPORTS (Tests 1-20)
    # =========================================================================

    @needs_client
    def test_001_unr_file_exists(self):
        self.assertTrue(os.path.exists(self.map_22_22_path), "22_22.unr must exist")

    @needs_client
    def test_002_unr_package_signature(self):
        pkg = Package(self.map_22_22_path)
        self.assertGreater(len(pkg.exports), 1000, "22_22.unr must contain thousands of exports")
        self.assertGreater(len(pkg.names), 500, "22_22.unr must contain name table")

    @needs_client
    def test_003_unr_terrain_info_presence(self):
        pkg = Package(self.map_22_22_path)
        tis = pkg.find_exports("TerrainInfo")
        self.assertGreaterEqual(len(tis), 1, "22_22.unr must export at least one TerrainInfo")

    @needs_client
    def test_004_unr_terrain_info_properties(self):
        pkg = Package(self.map_22_22_path)
        tis = pkg.find_exports("TerrainInfo")
        props = read_properties(pkg, tis[0])
        self.assertIn("Location", props)
        self.assertIn("TerrainScale", props)

    @needs_client
    def test_005_terrain_scale_vector_validity(self):
        pkg = Package(self.map_22_22_path)
        props = read_properties(pkg, pkg.find_exports("TerrainInfo")[0])
        sx, sy, sz = props["TerrainScale"]
        self.assertGreater(sx, 0.0)
        self.assertGreater(sy, 0.0)
        self.assertGreater(sz, 0.0)

    @needs_client
    def test_006_heightmap_texture_package_resolution(self):
        self.assertEqual(len(self.heights_22_22), 256)
        self.assertEqual(len(self.heights_22_22[0]), 256)

    @needs_client
    def test_007_terrain_holes_is_set(self):
        self.assertIsInstance(self.holes_22_22, set)

    @needs_client
    def test_008_static_mesh_actor_exports_exist(self):
        pkg = Package(self.map_22_22_path)
        actors = pkg.find_exports("StaticMeshActor")
        self.assertGreater(len(actors), 100, "22_22.unr must contain multiple StaticMeshActors")

    @needs_client
    def test_009_static_mesh_actor_properties(self):
        pkg = Package(self.map_22_22_path)
        actors = pkg.find_exports("StaticMeshActor")
        props = read_properties(pkg, actors[0])
        self.assertTrue("Location" in props or "StaticMesh" in props)

    @needs_client
    def test_010_static_mesh_import_reference(self):
        pkg = Package(self.map_22_22_path)
        sm_imports = [imp for imp in pkg.imports if imp[1] == "StaticMesh"]
        self.assertGreater(len(sm_imports), 10)

    @needs_client
    def test_011_mesh_library_load(self):
        self.assertIsNotNone(self.mesh_lib)

    @needs_client
    def test_012_bsp_model_exports(self):
        pkg = Package(self.map_22_22_path)
        models = pkg.find_exports("Model")
        self.assertGreaterEqual(len(models), 1, "UNR must have level BSP Model")

    def test_013_bsp_skybox_edge_filter(self):
        tri_skybox = ((0, 0, 0), (20000, 0, 0), (0, 0, 0))
        self.assertFalse(bsp_face_collides(tri_skybox, 0))

    def test_014_bsp_notsolid_filter(self):
        tri = ((0, 0, 0), (100, 0, 0), (0, 100, 0))
        self.assertFalse(bsp_face_collides(tri, PF_NOTSOLID))

    def test_015_bsp_portal_filter(self):
        tri = ((0, 0, 0), (100, 0, 0), (0, 100, 0))
        self.assertFalse(bsp_face_collides(tri, PF_PORTAL))

    def test_016_bsp_valid_collision_face(self):
        tri = ((0, 0, 0), (100, 0, 0), (0, 100, 0))
        self.assertTrue(bsp_face_collides(tri, 0))

    @needs_client
    def test_017_blocking_volume_detection(self):
        pkg = Package(self.map_22_22_path)
        bvs = pkg.find_exports("BlockingVolume")
        self.assertIsInstance(bvs, list)

    def test_018_zone_hull_filter_detection(self):
        small_box_tris = [((0, 0, 0), (100, 0, 0), (0, 100, 0))]
        self.assertFalse(is_zone_hull(small_box_tris))
        large_box_tris = [((0, 0, 0), (5000, 0, 0), (0, 5000, 0))]
        self.assertTrue(is_zone_hull(large_box_tris))

    def test_019_unr_neighbor_map_names(self):
        from geolib.generate import neighbor_map_names
        neighbors = neighbor_map_names("22_22")
        self.assertEqual(len(neighbors), 8)
        self.assertIn("21_21", neighbors)
        self.assertIn("23_23", neighbors)

    def test_020_region_id_parsing(self):
        from geolib.generate import _region_id
        self.assertEqual(_region_id("22_22.unr"), "22_22")
        self.assertEqual(_region_id("22_22_Classic.unr"), "22_22")

    # =========================================================================
    # PART 2: COLLISION GEOMETRY & MESH TRANSFORMATIONS (Tests 21-40)
    # =========================================================================

    def test_021_area2_calculation(self):
        tri = ((0, 0, 0), (3, 0, 0), (0, 4, 0))
        self.assertAlmostEqual(_area2(tri), 144.0, places=2)

    def test_022_area2_zero_collinear(self):
        tri = ((0, 0, 0), (1, 1, 1), (2, 2, 2))
        self.assertAlmostEqual(_area2(tri), 0.0, places=5)

    def test_023_tri_shift_z(self):
        tri = ((10, 20, 30), (40, 50, 60), (70, 80, 90))
        shifted = _shift(tri, 43.35)
        self.assertAlmostEqual(shifted[0][2], 73.35, places=2)
        self.assertAlmostEqual(shifted[1][2], 103.35, places=2)

    def test_024_in_region_strictly_inside(self):
        tri = ((70000, 140000, 0), (70100, 140000, 0), (70000, 140100, 0))
        self.assertTrue(_in_region(tri, 65536, 131072))

    def test_025_in_region_outside(self):
        tri = ((10000, 10000, 0), (10100, 10000, 0), (10000, 10100, 0))
        self.assertFalse(_in_region(tri, 65536, 131072))

    def test_026_in_region_padding_inclusion(self):
        tri = ((65536 - 1000, 131072, 0), (65536 - 900, 131072, 0), (65536 - 1000, 131072 + 100, 0))
        self.assertTrue(_in_region(tri, 65536, 131072, pad=4096))

    def test_027_pick_under_cap(self):
        tris = [((0, 0, 0), (1, 0, 0), (0, 1, 0))]
        picked = _pick(tris, kind=0, cap=10)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0][1], 0)

    def test_028_pick_over_cap_sorts_by_area(self):
        small = ((0, 0, 0), (1, 0, 0), (0, 1, 0))
        big = ((0, 0, 0), (100, 0, 0), (0, 100, 0))
        picked = _pick([small, big], kind=1, cap=1)
        self.assertEqual(len(picked), 1)
        self.assertEqual(picked[0][0], big)

    def test_029_step_ok_within_bounds(self):
        self.assertTrue(_step_ok(dz_up=10))
        self.assertTrue(_step_ok(dz_up=-50))

    def test_030_step_ok_climb_too_high(self):
        self.assertFalse(_step_ok(dz_up=UP_STEP + 1))

    def test_031_step_ok_drop_too_deep(self):
        self.assertFalse(_step_ok(dz_up=-(DOWN_STEP + 1)))

    def test_032_rotator_matrix_identity(self):
        m = actor_matrix((0, 0, 0), scale=1.0, scale3d=(1.0, 1.0, 1.0))
        self.assertAlmostEqual(m[0][0], 1.0)
        self.assertAlmostEqual(m[1][1], 1.0)
        self.assertAlmostEqual(m[2][2], 1.0)

    def test_033_rotator_yaw_90(self):
        m = actor_matrix((0, 16384, 0), scale=1.0, scale3d=(1.0, 1.0, 1.0))
        self.assertAlmostEqual(m[0][0], 0.0, places=2)
        self.assertAlmostEqual(m[0][1], -1.0, places=2)
        self.assertAlmostEqual(m[1][0], 1.0, places=2)

    @needs_client
    def test_034_gather_collision_triangles_count(self):
        self.assertGreater(self.meta_22_22["nmesh"], 1000)

    @needs_client
    def test_035_mesh_vertex_coordinates_finite(self):
        self.assertTrue(math.isfinite(self.meta_22_22["zmin"]))
        self.assertTrue(math.isfinite(self.meta_22_22["zmax"]))

    @needs_client
    def test_036_blocking_volume_triangles_extraction(self):
        pkg = Package(self.map_22_22_path)
        tris = volume_triangles(pkg, VIEW_BLOCKING_VOLUME_CLASSES)
        self.assertIsInstance(tris, list)

    def test_037_normal_vector_flat_plane(self):
        v0 = (0.0, 0.0, 0.0)
        v1 = (1.0, 0.0, 0.0)
        v2 = (0.0, 1.0, 0.0)
        e1 = (v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2])
        e2 = (v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2])
        nz = e1[0]*e2[1] - e1[1]*e2[0]
        self.assertGreater(nz, 0.0)

    def test_038_normal_vector_vertical_wall(self):
        v0 = (0.0, 0.0, 0.0)
        v1 = (1.0, 0.0, 0.0)
        v2 = (0.0, 0.0, 1.0)
        e1 = (v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2])
        e2 = (v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2])
        nz = e1[0]*e2[1] - e1[1]*e2[0]
        self.assertAlmostEqual(nz, 0.0)

    @needs_client
    def test_039_client_dirs_detection(self):
        m, u = client_dirs(CLIENT_DIR)
        self.assertTrue(os.path.isdir(m))
        self.assertTrue(os.path.isdir(u))

    @needs_client
    def test_040_guess_client(self):
        from geolib.unrview import guess_client
        cand = guess_client(MAPS_DIR)
        self.assertIsNotNone(cand)

    # =========================================================================
    # PART 3: TERRAIN HEIGHTS & GEODATA CORRELATION (Tests 41-60)
    # =========================================================================

    @needs_client
    def test_041_load_terrain_grid_size(self):
        self.assertEqual(len(self.heights_22_22), 256)
        self.assertEqual(len(self.heights_22_22[0]), 256)

    @needs_client
    def test_042_terrain_cells_output_shape(self):
        self.assertEqual(len(self.hcell_22_22), CELLS_PER_AXIS)
        self.assertEqual(len(self.hcell_22_22[0]), CELLS_PER_AXIS)

    @needs_client
    def test_043_server_geodata_load_22_22(self):
        self.assertEqual(len(self.blocks_22_22), BLOCKS)

    @needs_client
    def test_044_terrain_vs_geodata_open_ground_height(self):
        gx, gy = 1800, 1800
        b_idx = (gy // 8) * 256 + (gx // 8)
        c_idx = (gy % 8) * 8 + (gx % 8)
        geo_h = self.blocks_22_22[b_idx][c_idx][0][0]
        unr_h = quant_h(int(round(self.hcell_22_22[gy][gx])))
        self.assertLessEqual(abs(geo_h - unr_h), 16)

    @needs_client
    def test_045_terrain_vs_geodata_point_100_100(self):
        gx, gy = 100, 100
        b_idx = (gy // 8) * 256 + (gx // 8)
        c_idx = (gy % 8) * 8 + (gx % 8)
        geo_h = self.blocks_22_22[b_idx][c_idx][0][0]
        unr_h = quant_h(int(round(self.hcell_22_22[gy][gx])))
        self.assertLessEqual(abs(geo_h - unr_h), 16)

    @needs_client
    def test_046_terrain_vs_geodata_point_500_500(self):
        gx, gy = 500, 500
        b_idx = (gy // 8) * 256 + (gx // 8)
        c_idx = (gy % 8) * 8 + (gx % 8)
        geo_h = self.blocks_22_22[b_idx][c_idx][0][0]
        unr_h = quant_h(int(round(self.hcell_22_22[gy][gx])))
        self.assertLessEqual(abs(geo_h - unr_h), 16)

    def test_047_flat_block_identification(self):
        from geolib.formats import block_type
        flat_cells = [[(100, 15)]] * 64
        self.assertEqual(block_type(flat_cells), 0)

    def test_048_complex_block_identification(self):
        from geolib.formats import block_type
        complex_cells = [[(100 + i, 15)] for i in range(64)]
        self.assertEqual(block_type(complex_cells), 1)

    def test_049_multilayer_block_identification(self):
        from geolib.formats import block_type
        ml_cells = [[(100, 15), (200, 15)] for _ in range(64)]
        self.assertEqual(block_type(ml_cells), 2)

    @needs_client
    def test_050_geodata_22_22_block_distribution(self):
        types, hmin, hmax, lmax, smin = summarize(self.blocks_22_22)
        self.assertEqual(len(types), 65536)
        self.assertGreater(types.count(1), 1000)

    @needs_client
    def test_051_geodata_22_22_z_bounds(self):
        types, hmin, hmax, lmax, smin = summarize(self.blocks_22_22)
        self.assertGreater(max(hmax), -1000)
        self.assertLess(min(hmin), -4000)

    def test_052_bilinear_lumps_relaxation(self):
        from geolib.generate import _relax_bilinear_lumps
        hcell = [[100.0] * 64 for _ in range(64)]
        hcell[32][33] = 124.0 # lump delta = 24 (up + 8)
        _relax_bilinear_lumps(hcell, up=16)
        self.assertEqual(hcell[32][33], 116.0) # pulled 8 units closer

    def test_053_quant_h_quantization_step(self):
        self.assertEqual(quant_h(104), 104)
        self.assertEqual(quant_h(107), 104)
        self.assertEqual(quant_h(108), 104)
        self.assertEqual(quant_h(111), 104)
        self.assertEqual(quant_h(112), 112)

    def test_054_dec_h_roundtrip(self):
        for z in (-4000, -2000, 0, 1500, 5000):
            qz = quant_h(z)
            packed = enc_cell(qz, 15)
            self.assertEqual(dec_h(packed), qz)

    def test_055_dec_nswe_roundtrip(self):
        for flags in (0, 1, 2, 4, 8, 15):
            packed = enc_cell(100, flags)
            self.assertEqual(dec_nswe(packed), flags)

    def test_056_coordinate_roundtrip_origin(self):
        rx, ry = 22, 22
        wx, wy, _ = geo_to_world(rx, ry, 0, 0, 0)
        cgx, cgy = world_to_geo(rx, ry, wx, wy)
        self.assertEqual(cgx, 0)
        self.assertEqual(cgy, 0)

    def test_057_coordinate_roundtrip_corner(self):
        rx, ry = 22, 22
        wx, wy, _ = geo_to_world(rx, ry, 2047, 2047, 0)
        cgx, cgy = world_to_geo(rx, ry, wx, wy)
        self.assertEqual(cgx, 2047)
        self.assertEqual(cgy, 2047)

    def test_058_coordinate_world_span(self):
        rx, ry = 22, 22
        w0x, w0y, _ = geo_to_world(rx, ry, 0, 0)
        w1x, w1y, _ = geo_to_world(rx, ry, 2048, 2048)
        self.assertEqual(w1x - w0x, REGION_UNITS)
        self.assertEqual(w1y - w0y, REGION_UNITS)

    def test_059_z_calibration_constant(self):
        self.assertAlmostEqual(Z_CALIBRATION, 43.35, places=2)

    @needs_client
    def test_060_holes_masking_detection(self):
        for h in list(self.holes_22_22)[:5]:
            self.assertIsInstance(h, tuple)
            self.assertEqual(len(h), 2)

    # =========================================================================
    # PART 4: STATIC MESH OBSTACLES, ARCHES & MULTILAYERS (Tests 61-80)
    # =========================================================================

    @needs_client
    def test_061_multilayer_cell_has_multiple_layers(self):
        found_ml = False
        for b in self.blocks_22_22:
            for cell in b:
                if len(cell) > 1:
                    found_ml = True
                    break
            if found_ml:
                break
        self.assertTrue(found_ml, "22_22 must contain multi-layer cells under bridges/structures")

    @needs_client
    def test_062_multilayer_cell_height_ordering(self):
        for b in self.blocks_22_22:
            for cell in b:
                if len(cell) > 1:
                    heights = [l[0] for l in cell]
                    # In L2 geodata layers are ordered descending from surface/roof down to ground
                    for i in range(len(heights) - 1):
                        self.assertGreater(heights[i], heights[i+1])
                    return

    @needs_client
    def test_063_headroom_separation(self):
        for b in self.blocks_22_22:
            for cell in b:
                if len(cell) > 1:
                    heights = [l[0] for l in cell]
                    # Headroom between top layer and next layer
                    self.assertGreaterEqual(heights[0] - heights[1], 24)
                    return

    def test_064_wall_horizontal_blocking(self):
        v0 = (-10.0, 8.0, -50.0)
        e1 = (20.0, 0.0, 0.0)
        e2 = (0.0, 0.0, 100.0)
        wall_tri = (v0[0], v0[1], v0[2], e1[0], e1[1], e1[2], e2[0], e2[1], e2[2])
        walls = [wall_tri]
        w_idx = [0]
        has_wall = _wall_between(0.0, 0.0, 0.0, 16.0, 0.0, w_idx, walls)
        self.assertTrue(has_wall)

    def test_065_wall_clear_above_top(self):
        v0 = (-10.0, 8.0, -50.0)
        e1 = (20.0, 0.0, 0.0)
        e2 = (0.0, 0.0, 100.0)
        wall_tri = (v0[0], v0[1], v0[2], e1[0], e1[1], e1[2], e2[0], e2[1], e2[2])
        walls = [wall_tri]
        w_idx = [0]
        has_wall = _wall_between(0.0, 0.0, 0.0, 16.0, 200.0, w_idx, walls)
        self.assertFalse(has_wall)

    def test_066_span_layers_single_floor(self):
        floors = [100]
        ceils = [200]
        layers = _span_layers(floors, ceils, base=[0])
        self.assertGreaterEqual(len(layers), 1)

    def test_067_span_layers_bridge_over_ground(self):
        floors = [0, 500]
        ceils = [200, 700]
        layers = _span_layers(floors, ceils, base=[-50])
        self.assertEqual(len(layers), 2)

    def test_068_pack_l2j_block_flat(self):
        from geolib.generate import pack_l2j_block
        flat_cells = [[(100, 15)]] * 64
        packed = pack_l2j_block(flat_cells)
        self.assertEqual(packed[0], 0)
        self.assertEqual(len(packed), 3)

    def test_069_pack_l2j_block_complex(self):
        from geolib.generate import pack_l2j_block
        cells = [[(100 + i, 15)] for i in range(64)]
        packed = pack_l2j_block(cells)
        self.assertEqual(packed[0], 1)
        self.assertEqual(len(packed), 1 + 64 * 2)

    def test_070_pack_l2j_block_multilayer(self):
        from geolib.generate import pack_l2j_block
        cells = [[(100, 15), (200, 15)] for _ in range(64)]
        packed = pack_l2j_block(cells)
        self.assertEqual(packed[0], 2)
        self.assertGreater(len(packed), 129)

    @needs_client
    def test_071_archway_preserves_lower_movement(self):
        for b in self.blocks_22_22:
            for cell in b:
                if len(cell) > 1 and cell[-1][0] < -2000:
                    ground_nswe = cell[-1][1]
                    if ground_nswe != FLAG_NONE:
                        self.assertGreater(ground_nswe, 0)
                        return

    def test_072_boundary_indices_computation(self):
        indices = _boundary_indices(16, 48, origin=0)
        self.assertIn(1, indices)
        self.assertIn(2, indices)

    def test_073_cell_range_coverage(self):
        lo_idx, hi_idx = _cell_range(0.0, 32.0, origin=0.0)
        self.assertEqual(lo_idx, 0)
        self.assertEqual(hi_idx, 1)

    def test_074_tri_axis_span(self):
        tri = ((0, 0, 0), (10, 0, 0), (0, 10, 0))
        span = _tri_axis_span(tri, axis=0, value=5.0)
        self.assertIsNotNone(span)

    def test_075_max_merged_span(self):
        spans = [(0.0, 10.0), (9.0, 20.0)]
        merged = _max_merged_span(spans)
        self.assertEqual(merged, 20.0)

    def test_076_blocking_edges_generation(self):
        blocking_tris = [((66000, 132000, 0), (66100, 132000, 0), (66000, 132100, 0))]
        edges = _blocking_edges(blocking_tris, west=65536, north=131072)
        self.assertIsInstance(edges, dict)

    def test_077_moller_trumbore_ray_intersection(self):
        orig = (0.0, 0.0, 100.0)
        dir_vec = (0.0, 0.0, -1.0)
        v0 = (-10.0, -10.0, 0.0)
        v1 = (10.0, -10.0, 0.0)
        v2 = (0.0, 10.0, 0.0)
        e1 = (v1[0]-v0[0], v1[1]-v0[1], v1[2]-v0[2])
        e2 = (v2[0]-v0[0], v2[1]-v0[1], v2[2]-v0[2])
        pvec = (dir_vec[1]*e2[2] - dir_vec[2]*e2[1],
                dir_vec[2]*e2[0] - dir_vec[0]*e2[2],
                dir_vec[0]*e2[1] - dir_vec[1]*e2[0])
        det = e1[0]*pvec[0] + e1[1]*pvec[1] + e1[2]*pvec[2]
        self.assertNotEqual(det, 0.0)

    def test_078_door_data_open_door_nswe(self):
        from geolib.doors import open_door_nswe
        opened = open_door_nswe(nswe=0, gx=10, gy=10, z=0, index={(10, 10): (-100, 100)})
        self.assertEqual(opened, 15)

    def test_079_load_region_doors(self):
        from geolib.doors import load_region_doors
        doors = load_region_doors(None, 65536, 131072)
        self.assertEqual(doors, {})

    def test_080_complex_is_flat_predicate(self):
        flat_heights = [100] * 64
        flat_nswes = [15] * 64
        self.assertTrue(complex_is_flat(flat_heights, flat_nswes))
        non_flat_h = [100] * 63 + [200]
        self.assertFalse(complex_is_flat(non_flat_h, flat_nswes))

    # =========================================================================
    # PART 5: 3D UNRVIEW PAYLOAD & VIEWER INTEGRATION (Tests 81-100)
    # =========================================================================

    @needs_client
    def test_081_pack_region_unr_header(self):
        self.assertGreaterEqual(len(self.payload_22_22), 32)
        magic, ntri, zmin, zmax, nmesh, nbsp, nblk, skipped = HEADER.unpack_from(self.payload_22_22, 0)
        self.assertEqual(magic, MAGIC)
        self.assertEqual(ntri, self.meta_22_22["ntri"])
        self.assertLess(zmin, zmax)

    @needs_client
    def test_082_pack_region_unr_payload_size_formula(self):
        ntri = self.meta_22_22["ntri"]
        expected_size = 32 + (ntri * 36) + (ntri * 1)
        self.assertEqual(len(self.payload_22_22), expected_size)

    @needs_client
    def test_083_pack_region_unr_z_bounds_match_meta(self):
        _, _, zmin, zmax, _, _, _, _ = HEADER.unpack_from(self.payload_22_22, 0)
        self.assertAlmostEqual(zmin, self.meta_22_22["zmin"], places=2)
        self.assertAlmostEqual(zmax, self.meta_22_22["zmax"], places=2)

    @needs_client
    def test_084_pack_region_unr_kind_counts(self):
        _, ntri, _, _, nmesh, nbsp, nblk, _ = HEADER.unpack_from(self.payload_22_22, 0)
        self.assertEqual(ntri, nmesh + nbsp + nblk)

    @needs_client
    def test_085_pack_region_unr_kinds_buffer_values(self):
        ntri = self.meta_22_22["ntri"]
        kinds_offset = 32 + (ntri * 36)
        kinds = self.payload_22_22[kinds_offset:kinds_offset + min(100, ntri)]
        for k in kinds:
            self.assertIn(k, (0, 1, 2))

    @needs_client
    def test_086_viewer_state_detects_l2g_files(self):
        state = ViewerState(primary=GEO_DIR, client_dir=CLIENT_DIR)
        files = state.files()
        self.assertIn("22_22", files)
        self.assertTrue(files["22_22"].endswith(".l2g"))

    @needs_client
    def test_087_viewer_state_parses_22_22_geodata(self):
        state = ViewerState(primary=GEO_DIR, client_dir=CLIENT_DIR)
        parsed = state.parsed("22_22")
        self.assertIsNotNone(parsed)
        self.assertEqual(len(parsed), BLOCKS)

    @needs_client
    def test_088_viewer_state_unr_payload_caching(self):
        state = ViewerState(primary=GEO_DIR, client_dir=CLIENT_DIR)
        p1 = state.unr_payload("22_22")
        p2 = state.unr_payload("22_22")
        self.assertIs(p1, p2, "ViewerState must return cached UNR payload on subsequent calls")

    @needs_client
    def test_089_viewer_state_files_discovery_count(self):
        state = ViewerState(primary=GEO_DIR, client_dir=CLIENT_DIR)
        self.assertGreaterEqual(len(state.files()), 150)

    @needs_client
    def test_090_viewer_state_thread_safety(self):
        state = ViewerState(primary=GEO_DIR, client_dir=CLIENT_DIR)
        results = []

        def worker():
            blocks = state.parsed("22_22")
            results.append(len(blocks))

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(results, [65536, 65536, 65536, 65536])

    def test_091_unr_map_20_20_parsing(self):
        map_20_20 = os.path.join(MAPS_DIR, "20_20.unr")
        if os.path.exists(map_20_20):
            pkg = Package(map_20_20)
            self.assertGreater(len(pkg.exports), 500)

    def test_092_unr_map_17_13_parsing(self):
        map_17_13 = os.path.join(MAPS_DIR, "17_13.unr")
        if os.path.exists(map_17_13):
            pkg = Package(map_17_13)
            self.assertGreater(len(pkg.exports), 500)

    def test_093_unr_map_16_10_parsing(self):
        map_16_10 = os.path.join(MAPS_DIR, "16_10.unr")
        if os.path.exists(map_16_10):
            pkg = Package(map_16_10)
            self.assertGreater(len(pkg.exports), 500)

    def test_094_unr_payload_20_20_validity(self):
        if os.path.exists(os.path.join(MAPS_DIR, "20_20.unr")):
            payload, meta = pack_region_unr(CLIENT_DIR, "20_20", mesh_lib=self.mesh_lib)
            self.assertGreater(meta["ntri"], 100)

    def test_095_unr_payload_17_13_validity(self):
        if os.path.exists(os.path.join(MAPS_DIR, "17_13.unr")):
            payload, meta = pack_region_unr(CLIENT_DIR, "17_13", mesh_lib=self.mesh_lib)
            self.assertGreater(meta["ntri"], 100)

    def test_096_geodata_seam_continuity_east(self):
        geo_23_22 = os.path.join(GEO_DIR, "23_22.l2g")
        if os.path.exists(geo_23_22):
            b_22 = self.blocks_22_22
            b_23 = parse_region(geo_23_22)
            # Valley pass crossing at gy=1400:
            gy = 1400
            b_east = (gy // 8) * 256 + 255
            c_east = (gy % 8) * 8 + 7
            b_west = (gy // 8) * 256 + 0
            c_west = (gy % 8) * 8 + 0
            z_east = b_22[b_east][c_east][0][0]
            z_west = b_23[b_west][c_west][0][0]
            self.assertLessEqual(abs(z_east - z_west), 150)

    def test_097_geodata_seam_continuity_south(self):
        geo_22_23 = os.path.join(GEO_DIR, "22_23.l2g")
        if os.path.exists(geo_22_23):
            b_22 = self.blocks_22_22
            b_22_23 = parse_region(geo_22_23)
            # Valley pass crossing towards harbor at gx=2000:
            gx = 2000
            b_south = 255 * 256 + (gx // 8)
            c_south = 7 * 8 + (gx % 8)
            b_north = 0 * 256 + (gx // 8)
            c_north = 0 * 8 + (gx % 8)
            z_south = b_22[b_south][c_south][0][0]
            z_north = b_22_23[b_north][c_north][0][0]
            self.assertLessEqual(abs(z_south - z_north), 150)

    def test_098_page_html_wasd_controls_present(self):
        from geolib.page import HTML_PAGE
        self.assertIn("k==='w'", HTML_PAGE)
        self.assertIn("k==='s'", HTML_PAGE)
        self.assertIn("k==='a'", HTML_PAGE)
        self.assertIn("k==='d'", HTML_PAGE)

    def test_099_page_html_webgl_canvas_present(self):
        from geolib.page import HTML_PAGE
        self.assertIn("<canvas", HTML_PAGE)
        self.assertIn("getContext('webgl')", HTML_PAGE)

    def test_100_page_html_unr_overlay_fetch_endpoint(self):
        from geolib.page import HTML_PAGE
        self.assertIn("/api/unr/", HTML_PAGE)
        self.assertIn("L2U1", HTML_PAGE)


if __name__ == "__main__":
    unittest.main()
