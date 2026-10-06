# -*- coding: utf-8 -*-
"""Shared test markers.

* ``slow``: heavy full-region tests (seconds each). Skip them for a fast
  edit/test loop with ``pytest -m "not slow"``; plain ``unittest`` runs them.
* ``needs_client``: tests that read a real Lineage 2 client + server
  geodata. Point L2_CLIENT_DIR / L2_GEODATA_DIR at them; otherwise skipped.
"""

import os
import unittest

try:
    import pytest
    slow = pytest.mark.slow
except ImportError:  # unittest without pytest: marker is a no-op
    def slow(obj):
        return obj

CLIENT_DIR = os.environ.get('L2_CLIENT_DIR', r"E:\EndlessWar-proyecto\2-Juego - para pruebas")
GEO_DIR = os.environ.get('L2_GEODATA_DIR', r"E:\EndlessWar-proyecto\1-Server-copilado\gameserver\geodata")
HAS_REAL_CLIENT = (os.path.isdir(os.path.join(CLIENT_DIR, 'Maps'))
                   and os.path.isdir(GEO_DIR))

needs_client = unittest.skipUnless(
    HAS_REAL_CLIENT,
    'real L2 client not found (set L2_CLIENT_DIR and L2_GEODATA_DIR)')
