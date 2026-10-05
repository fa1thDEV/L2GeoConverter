#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit test verifying that cliff repair does not block lower ground layers in arches/doorways."""

import os
import struct
import tempfile
import unittest

from geolib.formats import BLOCKS, enc_cell
from geolib.diagnostics import (
    GeoDiagnosticEngine, get_cell_layers, parse_region,
    FLAG_EAST, FLAG_WEST, FLAG_SOUTH, FLAG_NORTH, FLAG_ALL
)


class TestCliffArchDoorway(unittest.TestCase):

    def test_arch_doorway_ground_passable_after_repair(self):
        """
        Simulate an archway (e.g. in Giran):
        Cell (10, 10) is inside the arch:
          - Layer 0: Ground Z=100 (walkable, connects East to Cell (11, 10))
          - Layer 1: Arch Top Z=400 (roof of arch)
        Cell (11, 10) is outside the arch:
          - Layer 0: Ground Z=100 (walkable, connects West to Cell (10, 10))

        Cliff threshold = 48.
        The top of the arch (Z=400) drops 300 units to ground (Z=100).
        The top layer (Z=400) must have FLAG_EAST stripped.
        The ground layer (Z=100) on both sides MUST retain bidirectional movement!
        """
        with tempfile.TemporaryDirectory() as td:
            src_path = os.path.join(td, "20_20.l2j")
            dst_path = os.path.join(td, "20_20_repaired.l2j")

            # Build a 65536-block L2J file where block (1, 1) is complex/multi
            raw = bytearray()
            for bx in range(256):
                for by in range(256):
                    if bx == 1 and by == 1:
                        # Block (1,1): let's make it MULTILAYER (type 2)
                        raw.append(2)
                        for cx in range(8):
                            for cy in range(8):
                                gx = (bx << 3) + cx
                                gy = (by << 3) + cy
                                if gx == 10 and gy == 10:
                                    # Inside arch: 2 layers (Ground Z=96, Arch Top Z=384)
                                    raw.append(2)  # 2 layers
                                    raw.extend(struct.pack('<H', enc_cell(96, FLAG_ALL)))
                                    raw.extend(struct.pack('<H', enc_cell(384, FLAG_ALL)))
                                elif gx == 11 and gy == 10:
                                    # Outside arch: 1 layer (Ground Z=96)
                                    raw.append(1)  # 1 layer
                                    raw.extend(struct.pack('<H', enc_cell(96, FLAG_ALL)))
                                else:
                                    # Normal flat cell
                                    raw.append(1)
                                    raw.extend(struct.pack('<H', enc_cell(96, FLAG_ALL)))
                    else:
                        # Type 0 (flat at Z=96)
                        raw.append(0)
                        raw.extend(struct.pack('<h', 96))

            with open(src_path, 'wb') as f:
                f.write(raw)

            # Run repair
            engine = GeoDiagnosticEngine(cliff_threshold=48)
            res = engine.repair_and_save(src_path, dst_path)

            self.assertGreater(res["cliffs_sealed"], 0)

            # Inspect repaired layers
            repaired_blocks = parse_region(dst_path)
            cell_arch = get_cell_layers(repaired_blocks, 10, 10)
            cell_outside = get_cell_layers(repaired_blocks, 11, 10)

            # Ground level in arch (Z=96) must still have East open
            ground_arch = [l for l in cell_arch if l[0] == 96][0]
            self.assertTrue(ground_arch[1] & FLAG_EAST, "Ground inside arch must retain East movement")

            # Arch roof (Z=384) must have East blocked (cliff drop)
            roof_arch = [l for l in cell_arch if l[0] == 384][0]
            self.assertFalse(roof_arch[1] & FLAG_EAST, "Arch roof must NOT have East movement (drop into air)")

            # Ground level outside arch (Z=96) MUST retain West open into the arch!
            ground_outside = [l for l in cell_outside if l[0] == 96][0]
            self.assertTrue(ground_outside[1] & FLAG_WEST, "Ground outside arch MUST retain West entry through the doorway")


if __name__ == "__main__":
    unittest.main()
