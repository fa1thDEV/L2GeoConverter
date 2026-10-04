#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests verifying .l2g support in diff and spawncheck."""

import os
import struct
import tempfile
import unittest

from geolib.formats import L2GCodec, BLOCKS
from geolib.diff import region_files, sampled_surface, cmd_diff
from geolib.spawncheck import RegionGeo, _geo_path, classify_point


class TestDiffSpawnL2G(unittest.TestCase):

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.tmpdir = self.td.name

    def tearDown(self):
        self.td.cleanup()

    def _create_dummy_l2g(self, path, z_height=0):
        raw = bytearray()
        for _ in range(BLOCKS):
            raw.append(0)  # FLAT block
            raw.extend(struct.pack('<h', z_height))
        enc = L2GCodec.encrypt(bytes(raw))
        with open(path, 'wb') as f:
            f.write(enc)

    def test_diff_region_files_and_sampled_surface(self):
        p1 = os.path.join(self.tmpdir, "20_20.l2g")
        self._create_dummy_l2g(p1, z_height=100)

        rf = region_files(self.tmpdir)
        self.assertIn("20_20", rf)
        self.assertEqual(rf["20_20"], p1)

        sample = {0, 1, 2}
        surf = sampled_surface(p1, sample)
        self.assertEqual(len(surf), 3)
        self.assertEqual(surf[0], [100] * 8)

    def test_diff_two_l2g_packs(self):
        dir_a = os.path.join(self.tmpdir, "pack_a")
        dir_b = os.path.join(self.tmpdir, "pack_b")
        os.makedirs(dir_a, exist_ok=True)
        os.makedirs(dir_b, exist_ok=True)

        self._create_dummy_l2g(os.path.join(dir_a, "20_20.l2g"), z_height=100)
        self._create_dummy_l2g(os.path.join(dir_b, "20_20.l2g"), z_height=100)

        ret = cmd_diff(dir_a, dir_b)
        self.assertEqual(ret, 0)

    def test_spawncheck_region_geo_l2g(self):
        p = os.path.join(self.tmpdir, "20_20.l2g")
        self._create_dummy_l2g(p, z_height=200)

        found = _geo_path(self.tmpdir, 20, 20)
        self.assertEqual(found, p)

        rg = RegionGeo(p)
        self.assertEqual(rg.fmt, 'l2j')
        layers = rg.cell(0, 0)
        self.assertEqual(layers, [(200, 15)])

        bucket, hz, ad = classify_point(layers, 200)
        self.assertEqual(bucket, 'ok')
        self.assertEqual(hz, 200)


if __name__ == "__main__":
    unittest.main()
