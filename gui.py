#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 Geodata Converter - Graphical User Interface
(c) fa1thDEV & L2GeoConverter Contributors

Entry point only: the window and its tabs live in geolib/gui/.
"""

import os
import sys

# Ensure geolib can be imported
sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from geolib.gui import L2GeoConverterGUI, main  # noqa: E402,F401


if __name__ == "__main__":
    main()
