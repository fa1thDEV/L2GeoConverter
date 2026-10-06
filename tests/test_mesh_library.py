#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MeshLibrary name resolution (UE2 names are case-insensitive)."""

import unittest
from types import SimpleNamespace
from unittest import mock

from geolib import meshes
from geolib.meshes import MeshLibrary


class _FakePackage:
    def __init__(self, names):
        self._exports = [SimpleNamespace(name=n) for n in names]

    def find_exports(self, class_name):
        return self._exports if class_name == 'StaticMesh' else []


class MeshLookupTests(unittest.TestCase):
    def _lib(self, names):
        lib = MeshLibrary('/nonexistent')
        lib.packages['rocks'] = _FakePackage(names)
        return lib

    def test_mesh_name_case_insensitive(self):
        lib = self._lib(['rock01'])
        with mock.patch.object(meshes, 'parse_staticmesh',
                               side_effect=lambda pkg, ex: ex.name):
            self.assertEqual(lib.get('Rocks', 'Rock01'), 'rock01')
            # cached under one key regardless of spelling
            self.assertEqual(lib.get('ROCKS', 'ROCK01'), 'rock01')

    def test_exact_match_preferred(self):
        lib = self._lib(['rock01', 'Rock01'])
        with mock.patch.object(meshes, 'parse_staticmesh',
                               side_effect=lambda pkg, ex: ex.name):
            self.assertEqual(lib.get('Rocks', 'Rock01'), 'Rock01')

    def test_missing_mesh_is_none(self):
        lib = self._lib(['rock01'])
        self.assertIsNone(lib.get('Rocks', 'Tree01'))
        self.assertIn(('rocks', 'tree01'), lib.failed)


if __name__ == '__main__':
    unittest.main()
