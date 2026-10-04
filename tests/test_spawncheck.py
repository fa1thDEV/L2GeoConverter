#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""npcpos spawn vs geodata classification."""

import os
import struct
import tempfile
import unittest

from geolib.formats import BLOCKS, pack_pts_header
from geolib.spawncheck import (
    RegionGeo, classify_point, classify_territory, layer_in_window, pip,
    world_cell, world_region,
)


class WorldIndexTests(unittest.TestCase):
    def test_origin_region(self):
        self.assertEqual(world_region(0, 0), (20, 18))
        self.assertEqual(world_region(-1, -1), (19, 17))

    def test_cell_0_of_19_21(self):
        rx, ry = 19, 21
        wx, wy = (rx - 20) * 32768 + 8, (ry - 18) * 32768 + 8
        self.assertEqual(world_cell(wx, wy, rx, ry), (0, 0))


class PipTests(unittest.TestCase):
    def test_square_contains_center(self):
        sq = [(0, 0), (100, 0), (100, 100), (0, 100)]
        self.assertTrue(pip(50, 50, sq))
        self.assertFalse(pip(150, 50, sq))


class ClassifyTests(unittest.TestCase):
    def test_point_ok_within_64(self):
        b, h, d = classify_point([(-1824, 15)], -1829)
        self.assertEqual(b, 'ok')
        self.assertEqual(h, -1824)
        self.assertEqual(d, 5)

    def test_point_hole_ocean(self):
        b, h, d = classify_point([(-4648, 15)], -1800)
        self.assertEqual(b, 'hole')
        self.assertEqual(h, -4648)

    def test_point_wrong_floor(self):
        b, h, _d = classify_point([(-800, 15)], -3500)
        self.assertEqual(b, 'wrong_floor')
        self.assertEqual(h, -800)

    def test_layer_in_window(self):
        self.assertEqual(layer_in_window([(-2000, 15), (-800, 15)], -900, -700)[0], -800)
        self.assertIsNone(layer_in_window([(-2000, 15)], -900, -700))

    def test_territory_ok_when_any_hit(self):
        self.assertEqual(classify_territory(True, -4648, 4000, -2000, -1000, 'field'), 'ok')

    def test_territory_sky_skip(self):
        self.assertEqual(
            classify_territory(False, -2000, 8000, 4000, 9000, 'giran_sky_01'),
            'skip_sky')


class RegionGeoTests(unittest.TestCase):
    def test_pts_flat_cell(self):
        pts = bytearray(pack_pts_header(19, 21, BLOCKS, 0, 0, 0))
        pts += struct.pack('<Hhh', 0x0000, -1824, -1832)
        for _ in range(BLOCKS - 1):
            pts += struct.pack('<Hhh', 0x0000, -4648, -4648)
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, '19_21_conv.dat')
            with open(p, 'wb') as f:
                f.write(pts)
            geo = RegionGeo(p)
        self.assertEqual(geo.cell(0, 0), [(-1824, 15)])
        self.assertEqual(geo.cell(8, 0)[0][0], -4648)
        self.assertEqual(geo.cell(-1, 0), [])


if __name__ == '__main__':
    unittest.main()
