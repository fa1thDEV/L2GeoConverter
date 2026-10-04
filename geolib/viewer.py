#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Browser viewer: local HTTP server + API."""

import glob
import json
import os
import re
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .formats import GeoError, block_type, parse_region, summarize
from .page import HTML_PAGE
from .render import render_png
from .ui import bold, dim, green, red
from .unrview import guess_client, pack_region_unr
from .meshes import MeshLibrary

CACHE_CAPACITY = 2  # regions in memory: current and previous


class ViewerState:
    def __init__(self, primary, spawns=None, client_dir=None):
        self.primary = primary
        self.spawns = spawns or []
        self.client_dir = client_dir
        self.cache = {}
        self.unr_cache = {}
        self.geom_cache = {}
        self.mismatch_cache = {}
        self.mesh_lib = None
        self.meta_lock = threading.Lock()   # protects cache and locks
        self.locks = {}                     # path → Lock: parsing does not block other regions
        self.unr_locks = {}
        self.unr_build_lock = threading.Lock()

    def files(self):
        # name stem → path; 27_24_Classic is a separate region from 27_24,
        # the front takes coordinates from the first two numbers in the name
        out = {}
        for f in sorted(glob.glob(os.path.join(self.primary, '*.l2j')) +
                        glob.glob(os.path.join(self.primary, '*_conv.dat'))):
            base = os.path.basename(f)
            if not re.match(r'^\d+_\d+', base):
                continue
            stem = base[:-len('_conv.dat')] if base.endswith('_conv.dat') else base[:-len('.l2j')]
            out.setdefault(stem, f)
        return out

    def parsed(self, name):
        # region name → file via files(): suffixed names are found too
        candidates = [p for p in [self.files().get(name)] if p]
        for p in candidates:
            if os.path.exists(p):
                key = (p, os.path.getmtime(p))
                with self.meta_lock:
                    v = self.cache.get(key)
                    if v is not None:
                        return v
                    lk = self.locks.setdefault(p, threading.Lock())
                # lock on a specific file: two requests do not parse one region
                # twice, but parsing does not delay requests to other regions
                with lk:
                    with self.meta_lock:
                        v = self.cache.get(key)
                        if v is not None:
                            return v
                    v = parse_region(p)
                    with self.meta_lock:
                        while len(self.cache) >= CACHE_CAPACITY:
                            self.cache.pop(next(iter(self.cache)))
                        self.cache[key] = v
                    return v
        return None

    def unr_payload(self, name):
        if not self.client_dir:
            raise GeoError('no client folder (Maps/StaticMeshes)')
        with self.meta_lock:
            hit = self.unr_cache.get(name)
            if hit is not None:
                return hit
            lk = self.unr_locks.setdefault(name, threading.Lock())
        with lk:
            with self.meta_lock:
                hit = self.unr_cache.get(name)
                if hit is not None:
                    return hit
            with self.unr_build_lock:
                with self.meta_lock:
                    hit = self.unr_cache.get(name)
                    if hit is not None:
                        return hit
                self._ensure_mesh_lib()
                body, _meta = pack_region_unr(self.client_dir, name, self.mesh_lib)
                with self.meta_lock:
                    while len(self.unr_cache) >= 2:
                        self.unr_cache.pop(next(iter(self.unr_cache)))
                    self.unr_cache[name] = body
                return body

    def _ensure_mesh_lib(self):
        if self.mesh_lib is None and self.client_dir:
            from .unrview import client_dirs
            _maps, usx = client_dirs(self.client_dir)
            if usx:
                self.mesh_lib = MeshLibrary(usx)
                self.mesh_lib.MAX_PACKAGES = 16
        return self.mesh_lib

    def generate_geom(self, name):
        if not self.client_dir:
            raise GeoError('no client folder (Maps/StaticMeshes)')
        with self.meta_lock:
            hit = self.geom_cache.get(name)
            if hit is not None:
                return hit
            lk = self.unr_locks.setdefault('geom:' + name, threading.Lock())
        with lk:
            with self.meta_lock:
                hit = self.geom_cache.get(name)
                if hit is not None:
                    return hit
            from .generate import prepare_generate_geometry
            self._ensure_mesh_lib()
            g = prepare_generate_geometry(self.client_dir, name, lib=self.mesh_lib)
            with self.meta_lock:
                while len(self.geom_cache) >= 2:
                    self.geom_cache.pop(next(iter(self.geom_cache)))
                self.geom_cache[name] = g
            return g

    def mismatch_grid(self, name):
        blocks = self.parsed(name)
        if blocks is None:
            raise GeoError('region not found')
        key = (name, os.path.getmtime(self.files()[name]))
        with self.meta_lock:
            hit = self.mismatch_cache.get(key)
            if hit is not None:
                return hit
        from .mismatch import region_mismatch_grid
        grid = region_mismatch_grid(self.generate_geom(name), blocks)
        with self.meta_lock:
            while len(self.mismatch_cache) >= 2:
                self.mismatch_cache.pop(next(iter(self.mismatch_cache)))
            self.mismatch_cache[key] = grid
        return grid


def make_handler(state):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, obj, code=200):
            body = json.dumps(obj, separators=(',', ':')).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _bin(self, body, ctype='application/octet-stream'):
            self.send_response(200)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                self._route(urlparse(self.path).path)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as e:  # a bad request must not kill the thread without a response
                try:
                    self._json({'err': f'{type(e).__name__}: {e}'}, 400)
                except OSError:
                    pass

        def _route(self, path):
            if path == '/':
                body = HTML_PAGE.encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path == '/api/meta':
                self._json({'primary': state.primary, 'nspawns': len(state.spawns),
                            'client': state.client_dir or ''})
            elif path.startswith('/api/unr/'):
                name = path.split('/')[-1]
                if not re.match(r'^\d+_\d+', name):
                    return self._json({'err': 'bad region name'}, 400)
                if not state.client_dir:
                    return self._json({'err': 'no client Maps folder — pass --client'}, 400)
                try:
                    body = state.unr_payload(name)
                except GeoError as e:
                    return self._json({'err': str(e)}, 404)
                except Exception as e:
                    return self._json({'err': f'{type(e).__name__}: {e}'}, 500)
                return self._bin(body)
            elif path.startswith('/api/mismatch/cell/'):
                parts = path.split('/')
                if len(parts) != 7:
                    return self._json({'err': 'expected /api/mismatch/cell/<region>/<gx>/<gy>'}, 400)
                _, _, _, _, name, gx, gy = parts
                gx, gy = int(gx), int(gy)
                if not re.match(r'^\d+_\d+', name):
                    return self._json({'err': 'bad region name'}, 400)
                if not (0 <= gx < 2048 and 0 <= gy < 2048):
                    return self._json({'err': 'cell outside region'}, 400)
                if not state.client_dir:
                    return self._json({'err': 'no client Maps folder — pass --client'}, 400)
                blocks = state.parsed(name)
                if blocks is None:
                    return self._json({'err': 'region not found'}, 404)
                from .mismatch import cell_mismatch
                try:
                    rec = cell_mismatch(state.generate_geom(name), blocks, gx, gy)
                except GeoError as e:
                    return self._json({'err': str(e)}, 404)
                return self._json(rec)
            elif path.startswith('/api/mismatch/'):
                name = path.split('/')[-1]
                if not re.match(r'^\d+_\d+', name):
                    return self._json({'err': 'bad region name'}, 400)
                if not state.client_dir:
                    return self._json({'err': 'no client Maps folder — pass --client'}, 400)
                try:
                    grid = state.mismatch_grid(name)
                except GeoError as e:
                    return self._json({'err': str(e)}, 404)
                except Exception as e:
                    return self._json({'err': f'{type(e).__name__}: {e}'}, 500)
                return self._json(grid)
            elif path == '/api/spawns':
                self._json({'spawns': state.spawns})
            elif path == '/api/regions':
                out = []
                for name, f in state.files().items():
                    size = os.path.getsize(f)
                    stub = size in (196608, 393234)
                    out.append({'name': name, 'size': size, 'stub': stub})
                self._json(out)
            elif path.startswith('/api/region/'):
                name = path.split('/')[-1]
                q = parse_qs(urlparse(self.path).query)
                blocks = state.parsed(name)
                if blocks is None:
                    return self._json({'err': 'region not found'}, 404)
                li = int(q.get('layer', ['-1'])[0])
                if li >= 0:
                    # slice: N-th from the top layer of each cell; blocks without it → null
                    t, hmax = [], []
                    for blk in blocks:
                        best = None
                        for cell in blk:
                            if len(cell) > li:
                                h = sorted((l[0] for l in cell), reverse=True)[li]
                                if best is None or h > best:
                                    best = h
                        t.append(block_type(blk))
                        hmax.append(best)
                    self._json({'t': t, 'hmax': hmax, 'slice': li})
                else:
                    t, hmin, hmax, lm, smin = summarize(blocks)
                    srt = sorted(smin)
                    self._json({'t': t, 'hmin': hmin, 'hmax': hmax, 'lm': lm,
                                'nf': t.count(0), 'nc': t.count(1), 'nm': t.count(2),
                                'gmin': min(hmin), 'gmax': max(hmax),
                                # 2nd percentile: pits/mines do not wash out the palette
                                'gsmin': srt[len(srt) // 50]})
            elif path.startswith('/api/block/'):
                parts = path.split('/')
                if len(parts) != 6:
                    return self._json({'err': 'expected /api/block/<region>/<bx>/<by>'}, 400)
                _, _, _, name, bx, by = parts
                bx, by = int(bx), int(by)
                if not (0 <= bx <= 255 and 0 <= by <= 255):
                    return self._json({'err': 'block coordinates outside 0..255'}, 400)
                blocks = state.parsed(name)
                if blocks is None:
                    return self._json({'err': 'region not found'}, 404)
                blk = blocks[bx * 256 + by]
                self._json({'type': block_type(blk),
                            'cells': [[list(l) for l in cell] for cell in blk]})
            elif path.startswith('/api/render/'):
                name = path.split('/')[-1]
                q = parse_qs(urlparse(self.path).query)
                blocks = state.parsed(name)
                if blocks is None:
                    return self._json({'err': 'region not found'}, 404)
                li = int(q.get('layer', ['-1'])[0])
                body = render_png(blocks, li)
                fname = name + ('' if li < 0 else f'_layer{li + 1}') + '.png'
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Content-Disposition', f'attachment; filename="{fname}"')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif path.startswith('/api/nswe/'):
                name = path.split('/')[-1]
                q = parse_qs(urlparse(self.path).query)
                blocks = state.parsed(name)
                if blocks is None:
                    return self._json({'err': 'region not found'}, 404)
                bx0 = max(0, min(255, int(q.get('bx0', ['0'])[0])))
                by0 = max(0, min(255, int(q.get('by0', ['0'])[0])))
                bx1 = max(0, min(255, int(q.get('bx1', ['255'])[0])))
                by1 = max(0, min(255, int(q.get('by1', ['255'])[0])))
                li = int(q.get('layer', ['-1'])[0])
                out = {}
                for bx in range(bx0, bx1 + 1):
                    for by in range(by0, by1 + 1):
                        blk = blocks[bx * 256 + by]
                        vals = []
                        for cell in blk:
                            if li < 0:
                                # surface: NSWE of the highest layer
                                vals.append(max(cell, key=lambda l: l[0])[1])
                            elif len(cell) > li:
                                vals.append(sorted(cell, key=lambda l: -l[0])[li][1])
                            else:
                                vals.append(None)
                        out[f'{bx}_{by}'] = vals
                self._json({'b': out})
            else:
                self._json({'err': 'not found'}, 404)
    return H


def cmd_view(primary, port=8777, spawns_path=None, client_dir=None):
    spawns = []
    if spawns_path:
        if not os.path.isfile(spawns_path):
            print(red(f'  ✗ spawn catalog not found: {spawns_path}'))
            return 1
        with open(spawns_path, encoding='utf-8') as f:
            spawns = json.load(f).get('spawns', [])
        print(dim(f'  spawn markers: {len(spawns)} from {spawns_path}'))
    if not client_dir:
        client_dir = guess_client(primary)
    state = ViewerState(primary, spawns, client_dir)
    if client_dir:
        print(dim(f'  UNR overlay: {client_dir}'))
    else:
        print(dim('  UNR overlay: no Maps folder (pass --client <L2 client>)'))
    if not state.files():
        print(red(f'  ✗ no geodata files in {primary}.'))
        return 1
    try:
        srv = ThreadingHTTPServer(('127.0.0.1', port), make_handler(state))
    except OSError as e:
        print(red(f'  ✗ could not bind port {port}: {e}'))
        print(dim('    the viewer may already be running — specify another port: --port N'))
        return 1
    url = f'http://127.0.0.1:{port}/'
    print(f'  {green("✓")} viewer: {bold(url)}  (Ctrl+C — exit)')
    threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print(dim('\n  stopped.'))
    return 0
