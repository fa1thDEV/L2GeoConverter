#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L2J ↔ PTS round-trip on a synthetic region (flat + complex + multilayer)."""

import os
import struct
import tempfile
import unittest

from geolib.convert import (
    convert_file, l2j2pts_bytes, l2j2pts_file, validate_l2j_bytes, validate_pts_bytes,
)
from geolib.formats import BLOCKS, enc_cell, parse_region


def _make_l2j():
    """One complex block, one real multilayer block, the rest flat."""
    out = bytearray()
    flat_h = -4648
    for b in range(BLOCKS):
        if b == 0:
            out.append(1)
            for i in range(64):
                nswe = 15 if i else 14          # one cell with W closed
                out += struct.pack('<H', enc_cell(flat_h + (i % 8) * 8, nswe))
        elif b == 1:
            out.append(2)
            for i in range(64):
                if i == 0:
                    out.append(2)
                    out += struct.pack('<HH', enc_cell(96, 15), enc_cell(flat_h, 15))
                else:
                    out.append(1)
                    out += struct.pack('<H', enc_cell(flat_h, 15))
        else:
            out.append(0)
            out += struct.pack('<h', flat_h)
    return bytes(out)


class RoundTripTests(unittest.TestCase):
    def test_validate_l2j_accepts_fixture(self):
        data = _make_l2j()
        validate_l2j_bytes(data)

    def test_l2j_pts_l2j_byte_identical(self):
        l2j = _make_l2j()
        pts, n_flat, n_cx, n_ml = l2j2pts_bytes(l2j, 19, 21)
        validate_pts_bytes(pts)
        self.assertEqual(n_cx, 1)
        self.assertEqual(n_ml, 1)
        self.assertEqual(n_flat, BLOCKS - 2)
        self.assertEqual(pts[0], 19)
        self.assertEqual(pts[1], 21)
        self.assertEqual(pts[2:6], b'\x80\x00\x10\x00')

        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, '19_21_conv.dat')
            dst = os.path.join(td, '19_21.l2j')
            with open(src, 'wb') as f:
                f.write(pts)
            convert_file(src, dst)
            with open(dst, 'rb') as f:
                back = f.read()
        self.assertEqual(back, l2j)

    def test_pts_header_layer_count(self):
        l2j = _make_l2j()
        pts, _nf, _nc, _nm = l2j2pts_bytes(l2j, 23, 18)
        n_layers, n_flat_cx, n_flat = struct.unpack_from('<III', pts, 6)
        # complex 64 + multilayer (2 + 63) = 129  — Glory Days (default)
        self.assertEqual(n_layers, 64 + 65)
        self.assertEqual(n_flat, BLOCKS - 2)
        self.assertEqual(n_flat_cx, n_flat + 1)

    def test_pts_header_286_counts_cells_not_layers(self):
        """Official protocol 286: first u32 is (cx+ml)*64, not layer sum."""
        l2j = _make_l2j()
        pts_gd, n_flat, n_cx, n_ml = l2j2pts_bytes(l2j, 23, 18, 'gd')
        pts286, nf2, nc2, nm2 = l2j2pts_bytes(l2j, 23, 18, '286')
        self.assertEqual((n_flat, n_cx, n_ml), (nf2, nc2, nm2))
        self.assertEqual(n_cx, 1)
        self.assertEqual(n_ml, 1)
        field_gd = struct.unpack_from('<I', pts_gd, 6)[0]
        field_286 = struct.unpack_from('<I', pts286, 6)[0]
        self.assertEqual(field_gd, 64 + 65)
        self.assertEqual(field_286, (n_cx + n_ml) * 64)
        self.assertNotEqual(field_gd, field_286)
        self.assertEqual(pts_gd[:6], pts286[:6])
        self.assertEqual(pts_gd[10:], pts286[10:])   # rest of header + body
        validate_pts_bytes(pts_gd)
        validate_pts_bytes(pts286)

    def test_protocol_aliases(self):
        from geolib.formats import PROTO_SHOWN, normalize_protocol
        self.assertEqual(PROTO_SHOWN['gd'], ('gd', 'interlude', 'hf', 'epilogue', 'glory'))
        self.assertEqual(PROTO_SHOWN['286'], ('286', 'c4'))
        for alias in PROTO_SHOWN['gd'] + ('glorydays', 'il', 'highfive', 'ep'):
            self.assertEqual(normalize_protocol(alias), 'gd', alias)
        for alias in PROTO_SHOWN['286']:
            self.assertEqual(normalize_protocol(alias), '286', alias)
        pts_hf = l2j2pts_bytes(_make_l2j(), 1, 1, 'hf')[0]
        pts_il = l2j2pts_bytes(_make_l2j(), 1, 1, 'interlude')[0]
        pts_ep = l2j2pts_bytes(_make_l2j(), 1, 1, 'epilogue')[0]
        pts_c4 = l2j2pts_bytes(_make_l2j(), 1, 1, 'c4')[0]
        self.assertEqual(struct.unpack_from('<I', pts_hf, 6)[0], 129)
        self.assertEqual(struct.unpack_from('<I', pts_il, 6)[0], 129)
        self.assertEqual(struct.unpack_from('<I', pts_ep, 6)[0], 129)
        self.assertEqual(struct.unpack_from('<I', pts_c4, 6)[0], 128)

    def test_parse_region_pts_and_l2j_agree(self):
        l2j = _make_l2j()
        pts, _, _, _ = l2j2pts_bytes(l2j, 20, 22)
        with tempfile.TemporaryDirectory() as td:
            lp = os.path.join(td, '20_22.l2j')
            pp = os.path.join(td, '20_22_conv.dat')
            with open(lp, 'wb') as f:
                f.write(l2j)
            with open(pp, 'wb') as f:
                f.write(pts)
            a = parse_region(lp)
            b = parse_region(pp)
        self.assertEqual(a[0][0], b[0][0])          # complex cell 0
        self.assertEqual(len(a[1][0]), 2)           # multilayer cell 0
        self.assertEqual(a[1][0], b[1][0])
        self.assertEqual(a[2][0], b[2][0])          # flat

    def test_file_helpers_match_bytes(self):
        l2j = _make_l2j()
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, '25_21.l2j')
            dst = os.path.join(td, '25_21_conv.dat')
            with open(src, 'wb') as f:
                f.write(l2j)
            l2j2pts_file(src, dst, 25, 21)
            with open(dst, 'rb') as f:
                self.assertEqual(f.read(), l2j2pts_bytes(l2j, 25, 21)[0])

    def test_encode_generated_pts_skips_l2j_file(self):
        from geolib.generate import _encode_generated
        l2j = _make_l2j()
        self.assertEqual(_encode_generated(l2j, '19_21', 'l2j'), l2j)
        pts = _encode_generated(l2j, '19_21_Classic', 'pts')
        validate_pts_bytes(pts)
        self.assertEqual(pts[0], 19)
        self.assertEqual(pts[1], 21)
        self.assertEqual(struct.unpack_from('<I', pts, 6)[0], 129)
        pts286 = _encode_generated(l2j, '19_21', 'pts', '286')
        self.assertEqual(struct.unpack_from('<I', pts286, 6)[0], 128)
