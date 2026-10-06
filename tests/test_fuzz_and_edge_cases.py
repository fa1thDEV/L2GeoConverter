import unittest
import struct
import io
import os
from geolib.formats import (
    quant_h, dec_h, enc_cell,
    L2GCodec, sniff_format, parse_region, GeoError
)
from geolib.editor import (
    shift_z_blocks, delete_z_range_blocks, recalculate_slope_flags,
    L2ClientMemoryScanner
)
from geolib.diagnostics import (
    GeoDiagnosticEngine, geo_to_world, world_to_geo, get_cell_layers, set_cell_layers
)
from tests.support import slow

class TestGeoFormats(unittest.TestCase):
    def test_height_quantization(self):
        # 1. Height quantization boundaries
        self.assertEqual(dec_h(enc_cell(-16384, 0)), -16384)
        self.assertEqual(quant_h(-32768), -16384)
        
        self.assertEqual(dec_h(enc_cell(16376, 0)), 16376)
        self.assertEqual(quant_h(32767), 16376)
        
        self.assertEqual(quant_h(0), 0)
        
        # odd / even integers
        self.assertEqual(quant_h(1), 0)
        self.assertEqual(quant_h(2), 0)
        self.assertEqual(quant_h(7), 0)
        self.assertEqual(quant_h(8), 8)
        self.assertEqual(quant_h(-1), -8)
        self.assertEqual(quant_h(-7), -8)
        self.assertEqual(quant_h(-8), -8)
        self.assertEqual(quant_h(-9), -16)

    def test_l2g_codec_roundtrip(self):
        # 2. L2GCodec encryption/decryption roundtrip
        payloads = [
            b"", # zero-length - L2GCodec encrypt handles it, wait. decrypt requires at least 4 bytes. 
            b"123", # non-block-aligned (size 3)
            b"A" * 10000, # large payload
        ]
        for p in payloads:
            enc = L2GCodec.encrypt(p)
            dec = L2GCodec.decrypt(enc)
            self.assertEqual(p, dec)
            
    def test_malformed_stream(self):
        # Malformed L2G (less than 4 bytes)
        with self.assertRaises(GeoError):
            L2GCodec.decrypt(b"123")
        
        # parse_region on fake file
        fake_path = "20_18_fake.l2j"
        with open(fake_path, "wb") as f:
            f.write(b"\x05" * 1000) # invalid block type
            
        with self.assertRaises(GeoError):
            parse_region(fake_path)
            
        if os.path.exists(fake_path):
            os.remove(fake_path)

class TestGeoEditor(unittest.TestCase):
    def setUp(self):
        self.blocks = [[[(100, 15)]] * 64 for _ in range(65536)]
        
    @slow
    def test_shift_z_blocks_extreme(self):
        # We need to copy otherwise flat blocks might be shared.
        # setUp creates shared lists.
        shift_z_blocks(self.blocks, 50000)
        self.assertEqual(self.blocks[0][0][0][0], 16376) # clamped max
        
        shift_z_blocks(self.blocks, -100000)
        self.assertEqual(self.blocks[0][0][0][0], -16384) # clamped min

    @slow
    def test_delete_z_range_blocks(self):
        # Multi-layer cell
        self.blocks[0][0] = [(100, 15), (200, 15), (300, 15)]
        
        # partial removal
        delete_z_range_blocks(self.blocks, 150, 250)
        self.assertEqual(len(self.blocks[0][0]), 2)
        self.assertEqual(self.blocks[0][0][0][0], 100)
        self.assertEqual(self.blocks[0][0][1][0], 300)
        
        # complete removal (should keep at least one if keep_at_least_one=True)
        delete_z_range_blocks(self.blocks, -1000, 1000, keep_at_least_one=True)
        self.assertEqual(len(self.blocks[0][0]), 1)
        self.assertEqual(self.blocks[0][0][0][0], 100)
        self.assertEqual(self.blocks[0][0][0][1], 0) # FLAG_NONE
        
        # zero-layer edge case (if keep_at_least_one=False)
        self.blocks[0][0] = [(100, 15), (200, 15)]
        delete_z_range_blocks(self.blocks, -1000, 1000, keep_at_least_one=False)
        self.assertEqual(len(self.blocks[0][0]), 0)

    @slow
    def test_recalculate_slope_flags(self):
        self.blocks[0][0] = [(100, 15)]
        self.blocks[0][1] = [(150, 15)] # delta 50 > max_climb_z (default 24)
        # Note: cell 0 (0,0) and cell 1 (0,1) means South-North?
        # Actually cx=0, cy=0 and cx=0, cy=1 is South.
        recalculate_slope_flags(self.blocks, max_climb_z=24)
        
        self.assertEqual(self.blocks[0][0][0][1] & 4, 0) # No South
        self.assertEqual(self.blocks[0][1][0][1] & 8, 0) # No North

    def test_client_memory_scanner(self):
        scanner = L2ClientMemoryScanner()
        # Should degrade safely
        res = scanner.read_player_coords()
        self.assertIsNone(res)
        scanner.close()

class TestGeoDiagnostics(unittest.TestCase):
    @slow
    def test_multi_layer_archway_cliff_resolution(self):
        engine = GeoDiagnosticEngine(cliff_threshold=48, min_clearance=32)
        blocks = [[[(0, 15)]] * 64 for _ in range(65536)]
        
        # Archway: Cell (1,0) has ground=0, roof=100.
        blocks[0][8] = [(0, 15), (100, 15)]
        
        # (2,0) has ground=0, roof=200.
        blocks[0][16] = [(0, 15), (200, 15)]
        
        path = "20_18_test.l2j"
        import geolib.editor as editor
        editor.save_edited_region(blocks, path, target_format="l2j")
        
        res = engine.repair_and_save(path, "20_18_test_repaired.l2j")
        self.assertTrue(res["cliffs_sealed"] > 0)
        
        # Verify that (1,0) roof layer at 100 lost FLAG_EAST.
        repaired_blocks = parse_region("20_18_test_repaired.l2j")
        
        # (1,0) is block 0, cell 8
        cell_1_0 = repaired_blocks[0][8]
        # (2,0) is block 0, cell 16
        cell_2_0 = repaired_blocks[0][16]
        
        # Check ground remains walkable
        self.assertEqual(cell_1_0[0][0], 0)
        self.assertEqual(cell_1_0[0][1] & 1, 1) # FLAG_EAST is preserved
        
        self.assertEqual(cell_2_0[0][0], 0)
        self.assertEqual(cell_2_0[0][1] & 2, 2) # FLAG_WEST is preserved
        
        # Check cliff was sealed on the roof
        self.assertEqual(cell_1_0[1][0], 96)
        self.assertEqual(cell_1_0[1][1] & 1, 0) # FLAG_EAST is cleared
        
        if os.path.exists(path):
            os.remove(path)
        if os.path.exists("20_18_test_repaired.l2j"):
            os.remove("20_18_test_repaired.l2j")

    def test_coord_conversion_roundtrip(self):
        for rx in (10, 20, 26):
            for ry in (10, 18, 25):
                for gx in (0, 1024, 2047):
                    for gy in (0, 1024, 2047):
                        wx, wy, _ = geo_to_world(rx, ry, gx, gy)
                        rgx, rgy = world_to_geo(rx, ry, wx, wy)
                        self.assertEqual(gx, rgx)
                        self.assertEqual(gy, rgy)

if __name__ == '__main__':
    unittest.main()
