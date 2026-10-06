#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for Lucera 2 .l2g codec, format conversion, and diagnostics."""

import os
import struct
import tempfile
import unittest

from geolib.formats import L2GCodec, BLOCKS, dec_h, dec_nswe, enc_cell
from geolib.convert import l2j2pts_bytes, l2g2l2j_file, l2j2l2g_file, validate_l2j_bytes
from geolib.diagnostics import GeoDiagnosticEngine, cmd_diagnose
from tests.support import slow


class TestLucera2L2G(unittest.TestCase):

    def test_codec_roundtrip(self):
        # Create a synthetic L2J payload with 65536 flat blocks
        synthetic_l2j = bytearray()
        for b in range(BLOCKS):
            synthetic_l2j.append(0)  # FLAT
            synthetic_l2j.extend(struct.pack('<h', (b % 1000) * 8))

        data = bytes(synthetic_l2j)
        encrypted = L2GCodec.encrypt(data)
        self.assertEqual(len(encrypted), len(data) + 4)

        decrypted = L2GCodec.decrypt(encrypted)
        self.assertEqual(decrypted, data)

    def test_l2g_conversion_pipeline(self):
        with tempfile.TemporaryDirectory() as td:
            # Build minimal 65536 block L2J file
            l2j_path = os.path.join(td, "20_20.l2j")
            l2g_path = os.path.join(td, "20_20.l2g")
            restored_l2j_path = os.path.join(td, "20_20_restored.l2j")

            raw_l2j = bytearray()
            for _ in range(BLOCKS):
                raw_l2j.append(0)
                raw_l2j.extend(struct.pack('<h', 0))
            open(l2j_path, 'wb').write(raw_l2j)

            # Convert L2J -> L2G
            l2j2l2g_file(l2j_path, l2g_path)
            self.assertTrue(os.path.isfile(l2g_path))

            # Convert L2G -> L2J
            l2g2l2j_file(l2g_path, restored_l2j_path)
            self.assertTrue(os.path.isfile(restored_l2j_path))

            restored_data = open(restored_l2j_path, 'rb').read()
            self.assertEqual(restored_data, bytes(raw_l2j))

    @slow
    def test_ai_diagnostics_cliff_repair(self):
        with tempfile.TemporaryDirectory() as td:
            geo_path = os.path.join(td, "20_20.l2j")
            fixed_path = os.path.join(td, "20_20_fixed.l2j")

            # Create a complex region with a hazardous cliff drop (>48 units)
            raw = bytearray()
            for b in range(BLOCKS):
                raw.append(1)  # complex
                for cell_idx in range(64):
                    # Introduce a cliff on cell 0 vs cell 1
                    h = -100 if cell_idx == 0 else 0
                    nswe = 15  # all directions open
                    raw.extend(struct.pack('<H', enc_cell(h, nswe)))

            open(geo_path, 'wb').write(raw)

            engine = GeoDiagnosticEngine(cliff_threshold=48)
            report = engine.analyze(geo_path)
            self.assertGreater(report["stats"]["cliff_errors"], 0)

            # Repair and verify fix
            fix_res = engine.repair_and_save(geo_path, fixed_path)
            self.assertGreater(fix_res["cliffs_sealed"], 0)

            # Re-analyze repaired file
            post_report = engine.analyze(fixed_path)
            self.assertEqual(post_report["stats"]["cliff_errors"], 0)


if __name__ == '__main__':
    unittest.main()
