#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Short steep faces: lone risers vs stacked tent/building wall strips."""

import unittest

from geolib.generate import (
    STAIR_MAX_RISE, _max_merged_span, _prep_geometry,
)


def _band(x, y0, y1, z0, z1):
    """Vertical YZ quad as two triangles at fixed X."""
    a = (x, y0, z0)
    b = (x, y1, z0)
    c = (x, y0, z1)
    d = (x, y1, z1)
    return [(a, b, c), (b, d, c)]


class MergedSpanTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_max_merged_span([]), 0.0)

    def test_touching_bands_merge(self):
        self.assertEqual(_max_merged_span([(0, 16), (16, 32), (32, 48)]), 48)

    def test_gap_does_not_merge(self):
        self.assertEqual(_max_merged_span([(0, 16), (200, 216)]), 16)


class PrepGeometryRiserTests(unittest.TestCase):
    def test_lone_riser_is_not_a_wall(self):
        tris = _band(8.0, 0.0, 16.0, 0.0, float(STAIR_MAX_RISE))
        _fc, _fg, walls, w_grid = _prep_geometry(tris, 0.0, 0.0)
        self.assertEqual(walls, [])
        self.assertEqual(w_grid, {})

    def test_tall_face_is_a_wall(self):
        tris = _band(8.0, 0.0, 16.0, 0.0, float(STAIR_MAX_RISE + 8))
        _fc, _fg, walls, w_grid = _prep_geometry(tris, 0.0, 0.0)
        self.assertGreater(len(walls), 0)
        self.assertIn(0, w_grid)  # gx=0, gy=0

    def test_stacked_16u_strips_become_a_wall(self):
        tris = []
        for z0 in range(0, 128, 16):
            tris.extend(_band(8.0, 0.0, 16.0, float(z0), float(z0 + 16)))
        _fc, _fg, walls, w_grid = _prep_geometry(tris, 0.0, 0.0)
        self.assertGreater(len(walls), 0)
        self.assertIn(0, w_grid)
        self.assertGreaterEqual(len(w_grid[0]), 2)

    def test_two_separate_curbs_stay_risers(self):
        tris = _band(8.0, 0.0, 16.0, 0.0, 16.0)
        tris += _band(8.0, 0.0, 16.0, 200.0, 216.0)
        _fc, _fg, walls, w_grid = _prep_geometry(tris, 0.0, 0.0)
        self.assertEqual(walls, [])
        self.assertEqual(w_grid, {})


class RelaxBilinearLumpsTests(unittest.TestCase):
    def test_24u_pair_becomes_legal_step(self):
        from geolib.generate import _relax_bilinear_lumps
        g = [[0, 24], [0, 0]]
        _relax_bilinear_lumps(g, up=16)
        self.assertEqual(abs(g[0][1] - g[0][0]), 16)

    def test_real_cliff_32_untouched(self):
        from geolib.generate import _relax_bilinear_lumps
        g = [[0, 32], [0, 0]]
        _relax_bilinear_lumps(g, up=16)
        self.assertEqual(g[0][1], 32)


if __name__ == '__main__':
    unittest.main()
