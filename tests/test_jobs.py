#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Auto worker scaling from free RAM and CPU headroom."""

import unittest

from geolib.generate import (
    MAX_CPU_PCT, MIN_FREE_RAM_GB, _avail_ram_gb, _cpu_rate_units,
    _pool_status_lines, cpu_worker_cap, want_worker_delta,
)


class WorkerDeltaTests(unittest.TestCase):
    def test_always_starts_first_worker(self):
        self.assertEqual(want_worker_delta(0, True, 0.2, min_free=2.0, max_n=8), 1)

    def test_scale_up_when_free_ram_ok(self):
        self.assertEqual(want_worker_delta(2, True, 3.5, min_free=2.0, max_n=8), 1)

    def test_hold_at_cpu_cap(self):
        self.assertEqual(want_worker_delta(8, True, 9.0, min_free=2.0, max_n=8), 0)

    def test_scale_down_when_under_floor(self):
        self.assertEqual(want_worker_delta(4, True, 1.4, min_free=2.0, max_n=8), -1)

    def test_keep_last_worker_even_if_ram_tight(self):
        self.assertEqual(want_worker_delta(1, True, 0.2, min_free=2.0, max_n=8), 0)

    def test_hold_when_queue_empty(self):
        self.assertEqual(want_worker_delta(3, False, 8.0, min_free=2.0, max_n=8), 0)

    def test_avail_ram_probe(self):
        gb = _avail_ram_gb()
        self.assertIsNotNone(gb)
        self.assertGreater(gb, 0)
        self.assertEqual(MIN_FREE_RAM_GB, 2.0)
        self.assertEqual(MAX_CPU_PCT, 80.0)


class CpuCapTests(unittest.TestCase):
    def test_worker_cap_80_percent(self):
        self.assertEqual(cpu_worker_cap(80, n_cpu=8), 6)
        self.assertEqual(cpu_worker_cap(80, n_cpu=16), 12)
        self.assertEqual(cpu_worker_cap(80, n_cpu=4), 3)
        self.assertEqual(cpu_worker_cap(80, n_cpu=1), 1)

    def test_worker_cap_100_uses_every_thread(self):
        self.assertEqual(cpu_worker_cap(100, n_cpu=8), 8)

    def test_worker_cap_never_zero(self):
        self.assertEqual(cpu_worker_cap(1, n_cpu=2), 1)

    def test_windows_cpu_rate_units(self):
        self.assertEqual(_cpu_rate_units(80), 8000)
        self.assertEqual(_cpu_rate_units(100), 10000)
        self.assertEqual(_cpu_rate_units(1), 100)


class PoolStatusLinesTests(unittest.TestCase):
    def test_header_and_per_map_bar(self):
        lines = _pool_status_lines(
            3, 10, {'16_25': (128, 256)}, extra='  j=2', elapsed=60,
            max_maps=20)
        self.assertEqual(len(lines), 2)
        self.assertIn('generate', lines[0])
        self.assertIn('(3/10)', lines[0])
        self.assertIn('j=2', lines[0])
        self.assertIn('16_25', lines[1])
        self.assertIn('(128/256)', lines[1])
        self.assertIn('█', lines[1])

    def test_starting_workers(self):
        lines = _pool_status_lines(0, 10, {}, elapsed=0, max_maps=20)
        self.assertTrue(any('starting workers' in ln for ln in lines))

    def test_overflow_truncated(self):
        active = {f'{10 + i}_20': (i, 256) for i in range(6)}
        lines = _pool_status_lines(0, 20, active, max_maps=2)
        self.assertEqual(len(lines), 4)  # header + 2 maps + overflow
        self.assertTrue(any('10_20' in ln for ln in lines))
        self.assertTrue(any('11_20' in ln for ln in lines))
        self.assertFalse(any('12_20' in ln for ln in lines))
        self.assertTrue(any('+4 more' in ln for ln in lines))


if __name__ == '__main__':
    unittest.main()
