#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Collision-flag fixtures: water BSP, dungeon slab, BlockingVolume."""

import unittest

from geolib.generate import BLOCK_WIN_HI, BLOCK_WIN_LO, ZONE_PLANE, _blocking_edges
from geolib.meshes import (
    BSP_SKYBOX_EDGE, BLOCKING_VOLUME_CLASSES, MESH_ACTOR_CLASSES,
    OMIT_MESH_ACTOR_CLASSES, ZONE_HULL_XY, bsp_face_collides, is_zone_hull,
)
from geolib.unreal import PF_NOTSOLID, PF_PORTAL


class WaterMapFixture(unittest.TestCase):
    """Water/haze is PF_NotSolid — generate must not rasterize it as a floor."""

    def test_notsolid_water_sheet_dropped(self):
        water = ((0.0, 0.0, -4641.0),
                 (256.0, 0.0, -4641.0),
                 (0.0, 256.0, -4641.0))
        self.assertFalse(bsp_face_collides(water, PF_NOTSOLID))
        self.assertFalse(bsp_face_collides(water, PF_PORTAL))
        # same sheet with collision left ON stays (walk-on water)
        self.assertTrue(bsp_face_collides(water, 0))


class DungeonSlabFixture(unittest.TestCase):
    """Antaras-nest / devil-island floors are large but still collide.

    The old BIG_PLANE=4096 size cut dropped a 7280×9000 nest slab. Size
    alone is not a drop reason — only skybox-scale edges and world-cube Z.
    """

    def test_large_dungeon_floor_kept(self):
        slab = ((0.0, 0.0, -7692.0),
                (7280.0, 0.0, -7692.0),
                (0.0, 9000.0, -7692.0))
        self.assertTrue(bsp_face_collides(slab, 0))
        # Unlit+SmallWavy is a shader combo, not a skip flag
        self.assertTrue(bsp_face_collides(slab, 0x10))

    def test_skybox_edge_dropped(self):
        sky = ((0.0, 0.0, 0.0),
               (float(BSP_SKYBOX_EDGE + 1), 0.0, 0.0),
               (0.0, float(BSP_SKYBOX_EDGE + 1), 0.0))
        self.assertFalse(bsp_face_collides(sky, 0))

    def test_world_cube_z_dropped(self):
        lid = ((0.0, 0.0, 16376.0),
               (32.0, 0.0, 16376.0),
               (0.0, 32.0, 16376.0))
        self.assertFalse(bsp_face_collides(lid, 0))


class ExtraActorClasses(unittest.TestCase):
    """Tried against official GD; extra classes moved us away from PathMaker."""

    def test_does_not_ingest_volumes_or_customizable(self):
        self.assertEqual(MESH_ACTOR_CLASSES, ('StaticMeshActor',))
        self.assertEqual(BLOCKING_VOLUME_CLASSES, ())
        for name in OMIT_MESH_ACTOR_CLASSES:
            self.assertNotIn(name, MESH_ACTOR_CLASSES)
        self.assertNotIn('BlockingVolume', BLOCKING_VOLUME_CLASSES)
        self.assertNotIn('ServerBlockingVolume', BLOCKING_VOLUME_CLASSES)
        self.assertIn('Mover', OMIT_MESH_ACTOR_CLASSES)
        self.assertIn('MovableStaticMeshActor', OMIT_MESH_ACTOR_CLASSES)
        self.assertIn('L2MovableStaticMeshActor', OMIT_MESH_ACTOR_CLASSES)
        self.assertIn('SkyMeshActor', OMIT_MESH_ACTOR_CLASSES)


class BlockingVolumeFixture(unittest.TestCase):
    """Steep inner volumes close NSWE in the body window; zone borders do not."""

    def test_east_west_wall_closes_north_south(self):
        # Vertical face in the XZ plane at y=80 (gy=5), x 120–136, z 0..64.
        # Normal is ±Y → blocks N/S along the wall, not E/W along it.
        tri = ((120.0, 80.0, 0.0),
               (136.0, 80.0, 0.0),
               (120.0, 80.0, 64.0))
        blocked = _blocking_edges([tri], west=0.0, north=0.0)
        self.assertIn(('y', 7, 5), blocked)
        self.assertIn(('y', 8, 5), blocked)
        self.assertNotIn(('x', 8, 5), blocked)
        zlo, zhi = blocked[('y', 8, 5)]
        self.assertEqual((zlo, zhi), (0.0, 64.0))
        floor_z = 0
        self.assertFalse(zhi < floor_z + BLOCK_WIN_LO or zlo > floor_z + BLOCK_WIN_HI)

    def test_north_south_wall_closes_east_west(self):
        tri = ((128.0, 80.0, 0.0),
               (128.0, 96.0, 0.0),
               (128.0, 80.0, 64.0))
        blocked = _blocking_edges([tri], west=0.0, north=0.0)
        self.assertIn(('x', 8, 5), blocked)
        self.assertFalse(any(k[0] == 'y' for k in blocked))
        self.assertEqual(blocked[('x', 8, 5)], (0.0, 64.0))

    def test_long_east_west_wall_does_not_fence_the_floor(self):
        # 160u E-W fence at y=80. Old edge-walk stamped x-keys along the
        # whole length (Pantheon-style invisible wall). Must be y-keys only.
        tri = ((0.0, 80.0, 0.0),
               (160.0, 80.0, 0.0),
               (0.0, 80.0, 64.0))
        blocked = _blocking_edges([tri], west=0.0, north=0.0)
        self.assertTrue(blocked)
        self.assertFalse(any(k[0] == 'x' for k in blocked))
        gxs = sorted(k[1] for k in blocked if k[0] == 'y' and k[2] == 5)
        self.assertEqual(gxs, list(range(0, 10)))

    def test_zone_border_plane_skipped(self):
        tri = ((0.0, 0.0, 0.0),
               (float(ZONE_PLANE + 1), 0.0, 0.0),
               (0.0, 0.0, 64.0))
        self.assertEqual(_blocking_edges([tri], 0.0, 0.0), {})

    def test_shallow_lid_is_not_a_wall(self):
        lid = ((0.0, 0.0, 10.0),
               (32.0, 0.0, 10.0),
               (0.0, 32.0, 10.0))
        self.assertEqual(_blocking_edges([lid], 0.0, 0.0), {})


class ZoneHullFixture(unittest.TestCase):
    """Region-scale boxes are location hulls, not inner pawn walls."""

    def test_two_axis_box_is_a_hull(self):
        tris = [((0.0, 0.0, 0.0),
                 (float(ZONE_HULL_XY + 10), 0.0, 0.0),
                 (0.0, float(ZONE_HULL_XY + 10), 0.0))]
        self.assertTrue(is_zone_hull(tris))

    def test_long_thin_wall_is_not_a_hull(self):
        tris = [((0.0, 0.0, 0.0),
                 (8000.0, 0.0, 0.0),
                 (0.0, 16.0, 64.0))]
        self.assertFalse(is_zone_hull(tris))

    def test_pantheon_museum_box_is_a_hull(self):
        # 16_25 BlockingVolume168
        tris = [((-118395.0, 251180.0, -2999.0),
                 (-107451.0, 251180.0, -2999.0),
                 (-118395.0, 260092.0, 3537.0))]
        self.assertTrue(is_zone_hull(tris))
