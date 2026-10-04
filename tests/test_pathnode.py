#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pathnode compiler: record layout, flat fill grid, T-junction extras."""

import os
import struct
import tempfile
import unittest

from geolib.formats import BLOCKS, enc_cell, pack_pts_header, pack_pts_flat_heights
from geolib.pathnode import (
    CELL, FLOOR_Z, MAX_PER_SECTION, MERGE_DIST, NSEC, PARALLEL_MIN_NODES, RECORD,
    REGION, SECS, SECTION, _cap_section, _link_jobs, _sec_slot, _walk_pts,
    _write_secindex, cmd_pathnode, compile_region, decode_record, encode_record,
    octant, parse_idx, popcount4, read_bin, region_origin,
)


def _flat_pts(path, rx, ry, h=-4656):
    """All type-0 flats, NSWE=15."""
    body = pack_pts_header(rx, ry, BLOCKS, 0, 0, 0)
    pair = pack_pts_flat_heights(h, h)
    body += (struct.pack('<H', 0) + pair) * BLOCKS
    with open(path, 'wb') as f:
        f.write(body)


def _one_tjunction_pts(path, rx, ry, h=-1824):
    """Flat ocean plus one complex block whose SW cell is NSWE=14 (missing E)."""
    chunks = []
    tj = enc_cell(h, 14)
    open15 = enc_cell(h, 15)
    cells = [tj] + [open15] * 63
    for b in range(BLOCKS):
        if b == 0:
            chunks.append(struct.pack('<H', 0x40) + struct.pack('<64H', *cells))
        else:
            chunks.append(struct.pack('<H', 0) + pack_pts_flat_heights(h, h))
    with open(path, 'wb') as f:
        f.write(pack_pts_header(rx, ry, BLOCKS - 1, 1, 0, 64) + b''.join(chunks))


class RecordTests(unittest.TestCase):
    def test_roundtrip_44_bytes(self):
        raw = encode_record(-294784, 163968, -4656, [129, 2, 130])
        self.assertEqual(len(raw), RECORD)
        x, y, z, links = decode_record(raw)
        self.assertEqual((x, y, z), (-294784, 163968, -4656))
        self.assertEqual(list(links)[:3], [129, 2, 130])
        self.assertEqual(list(links)[3:], [0] * 5)

    def test_dummy_is_zeros(self):
        x, y, z, links = decode_record(encode_record(0, 0, 0, []))
        self.assertEqual((x, y, z), (0, 0, 0))
        self.assertEqual(list(links), [0] * 8)

    def test_popcount(self):
        self.assertEqual(popcount4(15), 4)
        self.assertEqual(popcount4(14), 3)
        self.assertEqual(popcount4(0), 0)

    def test_octant_cardinals(self):
        self.assertEqual(octant(256, 0), 0)
        self.assertEqual(octant(0, 256), 2)
        self.assertEqual(octant(-256, 0), 4)
        self.assertEqual(octant(0, -256), 6)
        self.assertIsNone(octant(0, 0))


class FlatGridTests(unittest.TestCase):
    def test_flat_region_is_128x128_section_centres(self):
        rx, ry = 11, 23
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, '11_23_conv.dat')
            _flat_pts(p, rx, ry, -4656)
            secs = compile_region(p, rx, ry)
        self.assertEqual(len(secs), SECS * SECS)
        west, north = region_origin(rx, ry)
        self.assertEqual(secs[(0, 0)], [(west + 128, north + 128, -4656)])
        self.assertEqual(secs[(1, 0)], [(west + 256 + 128, north + 128, -4656)])
        self.assertEqual(sum(len(v) for v in secs.values()), 16384)


class TJunctionTests(unittest.TestCase):
    def test_three_sided_cell_adds_a_centre_node(self):
        rx, ry = 18, 13
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, '18_13_conv.dat')
            _one_tjunction_pts(p, rx, ry, -1824)
            secs = compile_region(p, rx, ry)
        west, north = region_origin(rx, ry)
        # cell (0,0) centre — T-junction on this floor, so no same-floor fill.
        self.assertIn((west + 8, north + 8, -1824), secs[(0, 0)])
        self.assertNotIn((west + 128, north + 128, -1824), secs[(0, 0)])
        # a section with no T-junction still gets the 256-grid fill
        self.assertEqual(secs[(2, 2)], [(west + 2 * 256 + 128, north + 2 * 256 + 128, -1824)])


class CmdWriteTests(unittest.TestCase):
    def test_writes_bin_idx_dummy_and_zone_grid(self):
        rx, ry = 18, 13
        with tempfile.TemporaryDirectory() as td:
            geo = os.path.join(td, 'geo')
            out = os.path.join(td, 'out')
            os.makedirs(geo)
            _flat_pts(os.path.join(geo, '18_13_conv.dat'), rx, ry, -4656)
            rc = cmd_pathnode(geo, out, write_txt=False, regions=['18_13'])
            self.assertEqual(rc, 0)
            recs = read_bin(os.path.join(out, 'pathnode.bin'))
            self.assertEqual(recs[0][:3], (0, 0, 0))
            self.assertEqual(len(recs), 16384 + 1)
            self.assertEqual(os.path.getsize(os.path.join(out, 'pathnode.bin')),
                             (16384 + 1) * RECORD)
            with open(os.path.join(out, 'pathnode.idx'), encoding='utf-8') as f:
                total, zones = parse_idx(f.read())
            self.assertEqual(total, 16384)
            self.assertEqual(zones[(10, 10)], [])
            self.assertEqual(len(zones[(18, 13)]), 16384)
            self.assertEqual(zones[(18, 13)][0][:2], region_origin(18, 13))
            # interior 8-grid: node 1 is section (0,0); +Y neighbour is index 2
            west, north = region_origin(rx, ry)
            x, y, z, links = recs[1]
            self.assertEqual((x, y, z), (west + 128, north + 128, -4656))
            self.assertIn(2, links)


class CapTests(unittest.TestCase):
    def test_section_cap_constant(self):
        self.assertEqual(MAX_PER_SECTION, 16)
        self.assertEqual(MERGE_DIST, 48.0)
        self.assertEqual(FLOOR_Z, 64)
        self.assertEqual(CELL, 16)
        self.assertEqual(SECTION, 256)
        self.assertEqual(REGION, 32768)
        self.assertEqual(PARALLEL_MIN_NODES, 80000)

    def test_sec_slot_grid_corners(self):
        self.assertEqual(_sec_slot(10, 10, 0, 0), 0)
        self.assertEqual(_sec_slot(29, 26, 127, 127), NSEC - 1)
        self.assertIsNone(_sec_slot(9, 10, 0, 0))
        self.assertIsNone(_sec_slot(18, 13, -1, 0))

    def test_secindex_csr_matches_append_order(self):
        nodes = [(0, 0, 0, None, [0] * 8)]
        nodes.append((1, 1, 1, (10, 10, 0, 0), [0] * 8))
        nodes.append((2, 2, 2, (10, 10, 0, 0), [0] * 8))
        nodes.append((3, 3, 3, (18, 13, 1, 2), [0] * 8))
        with tempfile.TemporaryDirectory() as td:
            _write_secindex(td, nodes)
            with open(os.path.join(td, 'secindex.bin'), 'rb') as f:
                raw = f.read()
        starts = list(struct.unpack_from(f'<{NSEC + 1}i', raw))
        s0 = _sec_slot(10, 10, 0, 0)
        s1 = _sec_slot(18, 13, 1, 2)
        self.assertEqual(list(range(starts[s0], starts[s0 + 1])), [1, 2])
        self.assertEqual(list(range(starts[s1], starts[s1 + 1])), [3])
        self.assertEqual(starts[NSEC], 4)

    def test_small_pack_stays_in_process(self):
        self.assertEqual(_link_jobs(16384, None, min_free_ram=2.0, max_cpu=80), 1)
        self.assertEqual(_link_jobs(16384, 8, min_free_ram=2.0, max_cpu=80), 1)

    def test_cap_round_robins_floors(self):
        street = [(i * 16, 0, -3504) for i in range(20)]
        roof = [(i * 16, 32, -3048) for i in range(20)]
        kept = _cap_section(street + roof)
        self.assertEqual(len(kept), 16)
        zs = {z for _x, _y, z in kept}
        self.assertIn(-3504, zs)
        self.assertIn(-3048, zs)
        self.assertEqual(sum(1 for _x, _y, z in kept if z == -3504), 8)
        self.assertEqual(sum(1 for _x, _y, z in kept if z == -3048), 8)


class TwoFloorFillTests(unittest.TestCase):
    def test_roof_tjunction_still_fills_street(self):
        """T-junction on the roof must not skip the street centre fill."""
        rx, ry = 18, 13
        street, roof = -3504, -3048
        chunks = []
        # block 0 cell 0: roof T-junction (NSWE=14). Other cells: street only.
        b0 = [enc_cell(roof, 14)] + [enc_cell(street, 15)] * 63
        # block 257 (gx=8,gy=8): cell 0 is the section-0 centre — both floors.
        # L2Server order: b = bx*256+by, so b=257 is still bx=1, by=1.
        for b in range(BLOCKS):
            if b == 0:
                chunks.append(struct.pack('<H', 0x40) + struct.pack('<64H', *b0))
            elif b == 257:
                body = b''
                for i in range(64):
                    if i == 0:
                        body += struct.pack('<H', 2)
                        body += struct.pack('<HH', enc_cell(street, 15),
                                            enc_cell(roof, 15))
                    else:
                        body += struct.pack('<H', 1)
                        body += struct.pack('<H', enc_cell(street, 15))
                chunks.append(struct.pack('<H', 2 + 63) + body)
            else:
                chunks.append(struct.pack('<H', 0) + pack_pts_flat_heights(street, street))
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, '18_13_conv.dat')
            with open(p, 'wb') as f:
                f.write(pack_pts_header(rx, ry, BLOCKS - 2, 1, 1, 2 + 63)
                        + b''.join(chunks))
            secs = compile_region(p, rx, ry)
        west, north = region_origin(rx, ry)
        nodes = secs[(0, 0)]
        zs = {z for _x, _y, z in nodes}
        self.assertIn((west + 8, north + 8, roof), nodes)
        self.assertIn(street, zs)
        self.assertIn((west + 128, north + 128, street), nodes)


def _nswe_wall_pts(path, rx, ry, h=-4656, wall_gx=16):
    """Flat ocean plus a north-south NSWE wall between gx=wall_gx-1 and gx=wall_gx.

    Section (0,0) centre is gx=8, section (1,0) centre is gx=24 — 256 units
    apart, inside MAX_LINK — so the E octant link must not cross this wall.
    """
    open15 = enc_cell(h, 15)
    no_e = enc_cell(h, 14)
    no_w = enc_cell(h, 13)
    chunks = []
    n_cx = 0
    for b in range(BLOCKS):
        bx, by = b >> 8, b & 255
        gx0, gy0 = bx * 8, by * 8
        need = False
        cells = []
        for lx in range(8):
            for ly in range(8):
                gx = gx0 + lx
                if gx == wall_gx - 1:
                    cells.append(no_e)
                    need = True
                elif gx == wall_gx:
                    cells.append(no_w)
                    need = True
                else:
                    cells.append(open15)
        if need:
            n_cx += 1
            chunks.append(struct.pack('<H', 0x40) + struct.pack('<64H', *cells))
        else:
            chunks.append(struct.pack('<H', 0) + pack_pts_flat_heights(h, h))
    n_flat = BLOCKS - n_cx
    with open(path, 'wb') as f:
        f.write(pack_pts_header(rx, ry, n_flat, n_cx, 0, n_cx * 64)
                + b''.join(chunks))


class AxisOrderTests(unittest.TestCase):
    def test_walk_pts_matches_l2server_block_and_cell(self):
        """File block b=bx*256+by, cell i=cx*8+cy — not the swapped walk."""
        rx, ry = 16, 25
        mark = enc_cell(-1168, 15)
        fill = enc_cell(-4536, 15)
        # bx=1, by=0, cx=1, cy=0 → gx=9, gy=0. Swapped walk would report (0, 9).
        b = 1 * 256 + 0
        i = 1 * 8 + 0
        chunks = []
        for bi in range(BLOCKS):
            if bi == b:
                cells = [fill] * 64
                cells[i] = mark
                chunks.append(struct.pack('<H', 0x40) + struct.pack('<64H', *cells))
            else:
                chunks.append(struct.pack('<H', 0) + pack_pts_flat_heights(-4536, -4536))
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, '16_25_conv.dat')
            with open(p, 'wb') as f:
                f.write(pack_pts_header(rx, ry, BLOCKS - 1, 1, 0, 64)
                        + b''.join(chunks))
            hits = [(gx, gy, ls[0][0]) for gx, gy, ls in _walk_pts(p)
                    if ls[0][0] == -1168]
        self.assertEqual(hits, [(9, 0, -1168)])


class WallLinkTests(unittest.TestCase):
    def test_east_link_does_not_cross_nswe_wall(self):
        rx, ry = 18, 13
        with tempfile.TemporaryDirectory() as td:
            geo = os.path.join(td, 'geo')
            out = os.path.join(td, 'out')
            os.makedirs(geo)
            _nswe_wall_pts(os.path.join(geo, '18_13_conv.dat'), rx, ry)
            rc = cmd_pathnode(geo, out, write_txt=False, regions=['18_13'])
            self.assertEqual(rc, 0)
            recs = read_bin(os.path.join(out, 'pathnode.bin'))
            west, _north = region_origin(rx, ry)
            wall_x = west + 16 * CELL
            crossed = 0
            kept = 0
            for i in range(1, len(recs)):
                x, _y, _z, links = recs[i]
                west_side = x < wall_x
                for dest in links:
                    if not dest:
                        continue
                    dx = recs[dest][0]
                    if west_side and dx >= wall_x:
                        crossed += 1
                    elif (not west_side) and dx < wall_x:
                        crossed += 1
                    else:
                        kept += 1
            self.assertEqual(crossed, 0)
            self.assertGreater(kept, 0)


if __name__ == '__main__':
    unittest.main()
