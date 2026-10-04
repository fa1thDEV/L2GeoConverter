#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cell encoding and BSP poly-flag constants used by generate."""

import struct
import unittest

from geolib.formats import dec_h, dec_nswe, enc_cell
from geolib.unreal import PF_NOTSOLID, PF_PORTAL


class CellEncodingTests(unittest.TestCase):
    def test_nswe_round_trip(self):
        for nswe in range(16):
            v = enc_cell(96, nswe)
            self.assertEqual(dec_nswe(v), nswe)
            self.assertEqual(dec_h(v), 96)

    def test_height_quantized_to_8(self):
        # (h<<1) & 0xFFF0 drops the low 3 bits of height.
        self.assertEqual(dec_h(enc_cell(100, 15)), 96)
        self.assertEqual(dec_h(enc_cell(-8, 0)), -8)
        self.assertEqual(dec_h(enc_cell(-4641, 15)), -4648)

    def test_negative_height_as_signed(self):
        v = enc_cell(-16384, 15)
        packed = struct.pack('<H', v)
        self.assertEqual(dec_h(v), -16384)
        self.assertEqual(len(packed), 2)


class PolyFlagTests(unittest.TestCase):
    def test_pf_notsolid_and_portal_bits(self):
        self.assertEqual(PF_NOTSOLID, 0x08)
        self.assertEqual(PF_PORTAL, 0x04000000)
        self.assertTrue(PF_NOTSOLID & 0x08)
        self.assertFalse(PF_PORTAL & PF_NOTSOLID)
        # a typical solid dungeon floor has neither bit
        self.assertFalse(0 & (PF_PORTAL | PF_NOTSOLID))
        # water/haze sheets the client walks through
        self.assertTrue(PF_NOTSOLID & (PF_PORTAL | PF_NOTSOLID))
