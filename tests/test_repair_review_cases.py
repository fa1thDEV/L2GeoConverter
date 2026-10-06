#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair/diagnose cases raised by the l2mapconv-public review
(docs/research/L2G_CLIFF_FIX_REVIEW.md, 2026-10-05)."""

import os
import struct
import tempfile
import unittest

from geolib.diagnostics import (
    FLAG_ALL, FLAG_EAST, FLAG_WEST, GeoDiagnosticEngine, get_cell_layers,
    set_cell_layers,
)
from geolib.formats import BLOCKS, quant_h
from tests.support import slow


def _flat_blocks(z=0):
    return [[[(z, FLAG_ALL)]] * 64 for _ in range(BLOCKS)]


def _stats():
    return {"cliffs_sealed": 0, "asymmetries_repaired": 0, "layers_sorted": 0}


class RepairBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = GeoDiagnosticEngine(cliff_threshold=48)
        self.blocks = _flat_blocks()

    def _repair_east(self, gx=100, gy=100):
        st = _stats()
        self.engine._repair_boundary(self.blocks, gx, gy, gx + 1, gy,
                                     FLAG_EAST, FLAG_WEST, st)
        return st

    def test_one_way_step_is_closed_not_opened(self):
        # A→B open, B→A closed on flat ground: never punch through B's wall.
        set_cell_layers(self.blocks, 101, 100, [(0, FLAG_ALL & ~FLAG_WEST)])
        st = self._repair_east()
        self.assertEqual(st["asymmetries_repaired"], 1)
        self.assertFalse(get_cell_layers(self.blocks, 100, 100)[0][1] & FLAG_EAST)
        self.assertFalse(get_cell_layers(self.blocks, 101, 100)[0][1] & FLAG_WEST)

    def test_upper_layer_only_on_neighbour_is_sealed(self):
        # B has a ledge at Z=400 open toward A, which only has ground at 0.
        set_cell_layers(self.blocks, 101, 100, [(0, FLAG_ALL), (400, FLAG_ALL)])
        st = self._repair_east()
        b = dict(get_cell_layers(self.blocks, 101, 100))
        self.assertFalse(b[400] & FLAG_WEST, 'fall from the ledge left open')
        self.assertTrue(b[0] & FLAG_WEST, 'ground passage must stay open')
        self.assertTrue(get_cell_layers(self.blocks, 100, 100)[0][1] & FLAG_EAST)
        self.assertEqual(st["cliffs_sealed"], 1)

    def test_arch_lower_passage_preserved(self):
        # A: ground + arch top; B: ground only. Only the arch top is sealed.
        set_cell_layers(self.blocks, 100, 100, [(0, FLAG_ALL), (300, FLAG_ALL)])
        self._repair_east()
        a = dict(get_cell_layers(self.blocks, 100, 100))
        self.assertTrue(a[0] & FLAG_EAST)
        self.assertFalse(a[300] & FLAG_EAST)
        self.assertTrue(get_cell_layers(self.blocks, 101, 100)[0][1] & FLAG_WEST)


@slow
class AnalyzeDirectionTests(unittest.TestCase):
    def test_west_cliff_reported(self):
        # Cell (100,100) is a 200u pillar whose only open flag is West.
        blocks = _flat_blocks()
        set_cell_layers(blocks, 100, 100, [(200, FLAG_WEST)])
        set_cell_layers(blocks, 99, 100, [(0, FLAG_ALL & ~FLAG_EAST)])
        set_cell_layers(blocks, 101, 100, [(0, FLAG_ALL & ~FLAG_WEST)])
        out = bytearray()
        for blk in blocks:
            if blk[0] is blk[1]:
                out += b'\x00' + struct.pack('<h', quant_h(blk[0][0][0]))
            else:
                from geolib.formats import enc_cell
                out.append(1)
                for c in blk:
                    out += struct.pack('<H', enc_cell(*c[0]))
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, '20_20.l2j')
            with open(path, 'wb') as f:
                f.write(out)
            rep = GeoDiagnosticEngine(cliff_threshold=48).analyze(path)
        cliffs = [i for i in rep["sample_issues"] if i["type"] == "CLIFF_FALL"]
        self.assertEqual(rep["stats"]["cliff_errors"], 1)
        self.assertEqual(cliffs[0]["details"]["dir"], "WEST")


if __name__ == '__main__':
    unittest.main()
