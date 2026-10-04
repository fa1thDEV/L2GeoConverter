#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Official-style type-0 flatten, PTS (high, low), DoorData NSWE=15."""

import os
import struct
import tempfile
import unittest

from geolib.convert import convert_file, l2j2pts_bytes, validate_pts_bytes
from geolib.doors import (
    door_index_for_region, find_doordata, open_door_nswe, parse_doors,
)
from geolib.formats import (
    BLOCKS, FLAT_SPAN, enc_cell, pack_pts_flat_heights, parse_region,
    pts_flat_surface, quant_h,
)
from geolib.generate import pack_l2j_block


def _complex_l2j(heights, nswes=None):
    nswes = nswes or [15] * 64
    out = bytearray()
    out.append(1)
    for h, n in zip(heights, nswes):
        out += struct.pack('<H', enc_cell(h, n))
    out.append(0)
    out += struct.pack('<h', -4648)
    for _ in range(BLOCKS - 2):
        out.append(0)
        out += struct.pack('<h', -4648)
    return bytes(out)


class QuantAndPtsFlatTests(unittest.TestCase):
    def test_quant_h_8_grid(self):
        self.assertEqual(quant_h(-4648), -4648)
        self.assertEqual(quant_h(-4641) % 8, 0)
        self.assertIn(quant_h(-4641), (-4648, -4640))

    def test_pts_flat_surface_is_max(self):
        self.assertEqual(pts_flat_surface(-3352, -3360), -3352)
        self.assertEqual(pts_flat_surface(-3360, -3352), -3352)
        self.assertEqual(pack_pts_flat_heights(-3360, -3352),
                         struct.pack('<hh', -3352, -3360))

    def test_parse_pts_uses_high_word(self):
        pts = bytearray(struct.pack('<BBBBBBIII', 19, 19, 0x80, 0, 0x10, 0, 0, 0, BLOCKS))
        pts += struct.pack('<Hhh', 0x0000, -3352, -3360)
        for _ in range(BLOCKS - 1):
            pts += struct.pack('<Hhh', 0x0000, -4648, -4648)
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, '19_19_conv.dat')
            open(p, 'wb').write(pts)
            blocks = parse_region(p)
        self.assertEqual(blocks[0][0][0], (-3352, 15))


class FlattenTests(unittest.TestCase):
    def test_pack_quantizes_identical_raw_heights(self):
        cells = [[(-4641, 15)] for _ in range(64)]
        blk = pack_l2j_block(cells)
        self.assertEqual(blk[0], 0)
        (h,) = struct.unpack_from('<h', blk, 1)
        self.assertEqual(h, quant_h(-4641))
        self.assertEqual(h % 8, 0)

    def test_pack_keeps_complex_for_span_24(self):
        cells = [[(-4648 if i < 32 else -4672, 15)] for i in range(64)]
        blk = pack_l2j_block(cells)
        self.assertEqual(blk[0], 1)

    def test_l2j2pts_flattens_identical_heights(self):
        hs = [-4648] * 64
        l2j = _complex_l2j(hs)
        pts, n_flat, n_cx, n_ml = l2j2pts_bytes(l2j, 19, 21)
        validate_pts_bytes(pts)
        self.assertEqual(n_cx, 0)
        self.assertEqual(n_ml, 0)
        self.assertEqual(n_flat, BLOCKS)
        a, b = struct.unpack_from('<hh', pts, 18 + 2)
        self.assertEqual((a, b), (-4648, -4648))

    def test_l2j2pts_keeps_span_24_complex(self):
        """A 24u ramp must not become type-0 (max surface = 24u block-edge wall)."""
        hs = [-4648 if i < 32 else -4672 for i in range(64)]
        pts, n_flat, n_cx, _nm = l2j2pts_bytes(_complex_l2j(hs), 19, 21)
        self.assertEqual(n_cx, 1)
        self.assertEqual(n_flat, BLOCKS - 1)

    def test_l2j2pts_does_not_flatten_closed_nswe(self):
        hs = [-4648] * 64
        ns = [15] * 64
        ns[0] = 14
        pts, n_flat, n_cx, _nm = l2j2pts_bytes(_complex_l2j(hs, ns), 19, 21)
        self.assertEqual(n_cx, 1)
        self.assertEqual(n_flat, BLOCKS - 1)

    def test_l2j2pts_does_not_flatten_span_over_32(self):
        hs = [-4648 if i < 32 else -4648 - 40 for i in range(64)]
        pts, n_flat, n_cx, _nm = l2j2pts_bytes(_complex_l2j(hs), 19, 21)
        self.assertEqual(n_cx, 1)
        self.assertGreater(max(hs) - min(hs), FLAT_SPAN)

    def test_pts_to_l2j_keeps_per_cell_ramp(self):
        hs = [-4648 if i < 32 else -4672 for i in range(64)]
        l2j = _complex_l2j(hs)
        pts, _, _, _ = l2j2pts_bytes(l2j, 19, 21)
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, '19_21_conv.dat')
            dst = os.path.join(td, '19_21.l2j')
            open(src, 'wb').write(pts)
            convert_file(src, dst)
            back = parse_region(dst)
        self.assertEqual(back[0][0][0], (-4648, 15))
        self.assertEqual(back[0][32][0], (-4672, 15))


class DoorTests(unittest.TestCase):
    SAMPLE = (
        "door_begin\t[gludio_castle_outter_001]\ttype=normal_type\t"
        "height=320\tpos={-18481;113065;-2476}\t"
        "range={{-18481;113059;-2799};{-18351;113059;-2799};"
        "{-18351;113071;-2799};{-18481;113071;-2799}}\tdoor_end\n"
        "door_begin\t[gludio_castle_wall_001]\ttype=wall_type\t"
        "height=460\tpos={-19912;111381;-2688}\t"
        "range={{-19975;111082;-2922};{-19849;111082;-2922};"
        "{-19848;111680;-2922};{-19975;111680;-2922}}\tdoor_end\n"
    )

    def test_parse_skips_wall_type(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'doordata.txt')
            open(p, 'w', encoding='utf-8').write(self.SAMPLE)
            doors = parse_doors(p)
        self.assertEqual(len(doors), 1)
        self.assertEqual(doors[0]['name'], 'gludio_castle_outter_001')

    def test_open_gate_cell(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'doordata.txt')
            open(p, 'w', encoding='utf-8').write(self.SAMPLE)
            doors = parse_doors(p)
        west, north = (19 - 20) * 32768, (21 - 18) * 32768
        idx = door_index_for_region(doors, west, north)
        gx = int((-18481 - west) // 16)
        gy = int((113065 - north) // 16)
        self.assertIn((gx, gy), idx)
        self.assertEqual(open_door_nswe(6, gx, gy, -2776, idx), 15)
        self.assertEqual(open_door_nswe(6, gx, gy, 8000, idx), 6)

    def test_open_uses_quant_h_when_raw_z_misses_window(self):
        # Packed SoD floor -12152 is in the door window; raw ray Z can sit
        # just above z1 and then pack onto the 8-grid inside it.
        z0, z1 = -12394, -12148
        idx = {(0, 0): (z0, z1)}
        raw = packed = None
        for z in range(z1 + 1, z1 + 8):
            q = quant_h(z)
            if z0 <= q <= z1:
                raw, packed = z, q
                break
        self.assertIsNotNone(raw)
        self.assertGreater(raw, z1)
        self.assertTrue(z0 <= packed <= z1)
        self.assertEqual(open_door_nswe(13, 0, 0, raw, idx), 15)
        self.assertEqual(open_door_nswe(13, 0, 0, packed, idx), 15)
        self.assertEqual(open_door_nswe(13, 0, 0, 8000, idx), 13)

    def test_find_doordata_explicit_and_client(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'doordata.txt')
            open(p, 'w', encoding='utf-8').write(self.SAMPLE)
            self.assertEqual(find_doordata(None, p), p)
            client = os.path.join(td, 'client')
            os.makedirs(os.path.join(client, 'Script'))
            script = os.path.join(client, 'Script', 'doordata.txt')
            open(script, 'w', encoding='utf-8').write(self.SAMPLE)
            self.assertEqual(find_doordata(client), script)
            empty = os.path.join(td, 'empty_client')
            os.makedirs(empty)
            self.assertIsNone(find_doordata(empty))


if __name__ == '__main__':
    unittest.main()
