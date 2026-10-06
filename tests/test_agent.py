#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI-agent front ends: JSON tools, LLM CLI and MCP stdio server."""

import io
import json
import os
import struct
import tempfile
import unittest
from contextlib import redirect_stdout

from geolib import agent
from geolib.formats import BLOCKS, enc_cell, quant_h


def _region_l2j(z=-3000):
    """Flat region; block (0,0) is complex with a one-way East cell at (0,0)."""
    out = bytearray()
    for b in range(BLOCKS):
        if b == 0:
            out.append(1)
            for c in range(64):
                out += struct.pack('<H', enc_cell(z, 0x01 if c == 0 else 0x0F))
        else:
            out += b'\x00' + struct.pack('<h', quant_h(z))
    return bytes(out)


class AgentToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.td = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.td.name, '20_18.l2j')
        with open(cls.path, 'wb') as f:
            f.write(_region_l2j())

    @classmethod
    def tearDownClass(cls):
        cls.td.cleanup()

    def ok(self, name, **args):
        out = agent.call(name, args)
        self.assertTrue(out['ok'], out)
        return out['result']

    def test_info(self):
        r = self.ok('info', path=self.path)
        self.assertEqual(r['region'], '20_18')
        self.assertEqual(r['blocks'], {'flat': BLOCKS - 1, 'complex': 1, 'multilayer': 0})
        self.assertEqual(r['z_range'], [-3000, -3000])

    def test_cell_by_world_and_geo(self):
        # region 20_18 starts at world (0, 0)
        r = self.ok('cell', path=self.path, x=5, y=5)
        self.assertEqual(r['geo'], [0, 0])
        self.assertEqual(r['layers'], [{'z': -3000, 'nswe': 1, 'dirs': 'E'}])
        self.assertEqual(r['block_type'], 'complex')
        self.assertEqual(self.ok('cell', path=self.path, gx=0, gy=0), r)

    def test_area_dirs(self):
        r = self.ok('area', path=self.path, gx=0, gy=0, width=2, height=2, field='dirs')
        self.assertEqual(r['rows'], [['E', 'NSWE'], ['NSWE', 'NSWE']])

    def test_validate_convert_diff_roundtrip(self):
        dst = os.path.join(self.td.name, 'out', '20_18.l2g')
        self.ok('convert', src=self.path, dst=dst)
        self.assertTrue(self.ok('validate', path=dst)['valid'])
        pts = os.path.join(self.td.name, 'out', '20_18_conv.dat')
        self.ok('convert', src=dst, dst=pts)
        self.assertTrue(self.ok('validate', path=pts)['valid'])
        self.assertTrue(self.ok('diff', path_a=self.path, path_b=dst)['identical'])

    def test_errors_are_reported_not_raised(self):
        self.assertFalse(agent.call('cell', {'path': self.path})['ok'])
        self.assertFalse(agent.call('cell', {'path': self.path, 'gx': 5000, 'gy': 0})['ok'])
        self.assertFalse(agent.call('cell', {'path': 'missing.l2j', 'gx': 0, 'gy': 0})['ok'])
        self.assertIn('unknown args', agent.call('info', {'path': self.path, 'bogus': 1})['error'])
        self.assertIn('unknown tool', agent.call('nope')['error'])

    def test_cli_outputs_single_json_line(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = agent.cli_main(['cell', f'path={self.path}', 'gx=0', 'gy=0'])
        self.assertEqual(rc, 0)
        lines = buf.getvalue().strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])['result']['geo'], [0, 0])

    def test_mcp_session(self):
        reqs = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
             'params': {'protocolVersion': '2025-06-18', 'capabilities': {}}},
            {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
             'params': {'name': 'cell', 'arguments': {'path': self.path, 'gx': 0, 'gy': 0}}},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
             'params': {'name': 'cell', 'arguments': {'path': 'missing.l2j'}}},
            {'jsonrpc': '2.0', 'id': 5, 'method': 'unknown/method'},
        ]
        stdin = io.StringIO('\n'.join(json.dumps(r) for r in reqs) + '\nnot json\n')
        stdout = io.StringIO()
        agent.mcp_main(stdin, stdout)
        resp = [json.loads(ln) for ln in stdout.getvalue().splitlines()]
        by_id = {r['id']: r for r in resp}
        self.assertEqual(len(resp), 6)  # notification gets no reply
        self.assertEqual(by_id[1]['result']['serverInfo']['name'], 'l2geoconverter')
        names = {t['name'] for t in by_id[2]['result']['tools']}
        self.assertLessEqual({'info', 'cell', 'area', 'diagnose', 'diff'}, names)
        self.assertFalse(by_id[3]['result']['isError'])
        self.assertEqual(json.loads(by_id[3]['result']['content'][0]['text'])['geo'], [0, 0])
        self.assertTrue(by_id[4]['result']['isError'])
        self.assertEqual(by_id[5]['error']['code'], -32601)
        self.assertEqual(by_id[None]['error']['code'], -32700)


if __name__ == '__main__':
    unittest.main()
