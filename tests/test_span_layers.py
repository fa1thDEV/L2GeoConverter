#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""_span_layers clearance: mesh undersides vs terrain under a canopy."""

import unittest

import geolib.generate as generate
from geolib.generate import AGENT_HEIGHT, LAYER_MERGE, _span_layers


class SpanLayersTests(unittest.TestCase):
    def test_terrain_only(self):
        self.assertEqual(_span_layers([], [], [-4648]), [-4648])

    def test_mesh_underside_culled_by_own_top(self):
        # slab 40u thick: top 100, underside 60. Production classifies both as
        # floors (unsigned slope); underside cannot stand (gap 40 < AGENT_HEIGHT).
        self.assertEqual(_span_layers([100, 60], [], [-4648]), [100, -4648])

    def test_mesh_floor_needs_agent_height(self):
        # floor at 0 with a ceiling at 100 — cannot stand
        self.assertEqual(_span_layers([0], [100], [-4648]), [-4648])
        # ceiling at 128 — exactly AGENT_HEIGHT, walkable
        self.assertEqual(_span_layers([0], [128], [-4648]), [0, -4648])

    def test_terrain_not_burned_by_canopy_ceiling(self):
        # boulder/canopy underside over ground must not punch a hole
        canopy = [-4648 + 50]
        self.assertEqual(_span_layers([], canopy, [-4648]), [-4648])

    def test_terrain_suppressed_by_accepted_floor_above(self):
        # a stair/floor closer than AGENT_HEIGHT hides the ghost ground layer
        floor = [-4648 + 40]
        self.assertEqual(_span_layers(floor, [], [-4648]), floor)

    def test_flush_mesh_floors_merge(self):
        a, b = 200, 200 - (LAYER_MERGE - 1)
        self.assertEqual(_span_layers([a, b], [], [-4648]), [a, -4648])

    def test_two_storeys_kept(self):
        upper, lower = 400, 400 - AGENT_HEIGHT
        self.assertEqual(_span_layers([upper, lower], [], [-4648]),
                         [upper, lower, -4648])

    def test_layer_cap(self):
        floors = list(range(10000, 10000 - 200 * AGENT_HEIGHT, -AGENT_HEIGHT))
        self.assertEqual(len(_span_layers(floors, [], [-4648])), 120)

    def test_disconnected_roof_kept_by_span(self):
        # Roof far above terrain: clearance OK, no connectivity test.
        roof = [-4648 + 400]
        self.assertEqual(_span_layers(roof, [], [-4648]), [roof[0], -4648])


class NoIslandPruneTests(unittest.TestCase):
    def test_prune_removed(self):
        self.assertFalse(hasattr(generate, '_prune_unreachable'))
        self.assertFalse(hasattr(generate, 'MIN_ISLAND'))
