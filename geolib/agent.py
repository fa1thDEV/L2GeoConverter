#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Machine-readable tools for AI agents (LLM CLI mode and MCP server).

Every tool takes JSON-able keyword arguments and returns a JSON-able dict.
Library output (colours, progress bars) is captured, never mixed into the
result. Two front ends share the same registry:

  python geotool.py llm list                       # tool schemas
  python geotool.py llm cell path=20_20.l2j x=-130824 y=94856
  python geotool.py mcp                            # MCP server over stdio

Parsed regions are cached (keyed by path, mtime and size), so repeated
queries against the same file in one MCP session are instant.
"""

import collections
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import time

from .formats import (
    BLOCKS, GeoError, L2GCodec, PROTO_GD, block_type, parse_region,
    region_of, sniff_format, summarize,
)

SERVER_NAME = 'l2geoconverter'
SERVER_VERSION = '1.0'
MCP_PROTOCOL = '2025-06-18'

CELLS = 2048
REGION_UNITS = 32768
MAX_AREA = 128
_DIR_LETTERS = (('N', 8), ('S', 4), ('W', 2), ('E', 1))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class ToolError(Exception):
    """Bad arguments or unusable input — reported as a tool error."""


# ───────────────────────────── helpers ─────────────────────────────

_CACHE = collections.OrderedDict()
_CACHE_SIZE = 4


def _blocks(path):
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ToolError(f'file not found: {path}')
    if not sniff_format(path):
        raise ToolError(f'not a geodata file (.l2j / .l2g / .dat): {path}')
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    hit = _CACHE.get(key)
    if hit is not None:
        _CACHE.move_to_end(key)
        return hit
    blocks = parse_region(path)
    _CACHE[key] = blocks
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return blocks


def _origin(path):
    rx, ry = region_of(path)
    return rx, ry, (rx - 20) * REGION_UNITS, (ry - 18) * REGION_UNITS


def _dirs(nswe):
    return ''.join(c for c, bit in _DIR_LETTERS if nswe & bit) or '-'


def _layers(blocks, gx, gy):
    blk = blocks[(gx >> 3) * 256 + (gy >> 3)]
    return blk[(gx & 7) * 8 + (gy & 7)]


def _resolve_cell(path, gx=None, gy=None, x=None, y=None):
    rx, ry, west, north = _origin(path)
    if x is not None and y is not None:
        gx, gy = (int(x) - west) >> 4, (int(y) - north) >> 4
    if gx is None or gy is None:
        raise ToolError('give either gx/gy (cell 0..2047) or x/y (world)')
    gx, gy = int(gx), int(gy)
    if not (0 <= gx < CELLS and 0 <= gy < CELLS):
        raise ToolError(f'cell ({gx}, {gy}) is outside region {rx}_{ry}')
    return gx, gy


def _world(path, gx, gy):
    _, _, west, north = _origin(path)
    return west + gx * 16 + 8, north + gy * 16 + 8


def _l2j_bytes(path):
    from .convert import pts2l2j_bytes
    data = open_bytes(path)
    fmt = sniff_format(path)
    if fmt == 'l2g':
        return L2GCodec.decrypt(data)
    if fmt == 'pts':
        return pts2l2j_bytes(data)[0]
    return data


def open_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


# ───────────────────────────── tools ─────────────────────────────

def tool_info(path):
    blocks = _blocks(path)
    types, hmin, hmax, lmax, _ = summarize(blocks)
    rx, ry, west, north = _origin(path)
    counts = collections.Counter(types)
    return {
        'path': os.path.abspath(path),
        'format': sniff_format(path),
        'region': f'{rx}_{ry}',
        'world_bounds': {'x': [west, west + REGION_UNITS], 'y': [north, north + REGION_UNITS]},
        'blocks': {'flat': counts[0], 'complex': counts[1], 'multilayer': counts[2]},
        'z_range': [min(hmin), max(hmax)],
        'max_layers_per_cell': max(lmax),
        'size_bytes': os.path.getsize(path),
    }


def tool_cell(path, gx=None, gy=None, x=None, y=None):
    blocks = _blocks(path)
    gx, gy = _resolve_cell(path, gx, gy, x, y)
    blk = blocks[(gx >> 3) * 256 + (gy >> 3)]
    wx, wy = _world(path, gx, gy)
    return {
        'geo': [gx, gy],
        'world_center': [wx, wy],
        'block': [gx >> 3, gy >> 3],
        'block_type': ('flat', 'complex', 'multilayer')[block_type(blk)],
        'layers': [{'z': z, 'nswe': n, 'dirs': _dirs(n)} for z, n in _layers(blocks, gx, gy)],
    }


def tool_area(path, gx=None, gy=None, x=None, y=None, width=16, height=16,
              field='z', layer='top'):
    """Rows (gy) of columns (gx) starting at the given corner cell."""
    blocks = _blocks(path)
    gx, gy = _resolve_cell(path, gx, gy, x, y)
    width, height = int(width), int(height)
    if not (1 <= width <= MAX_AREA and 1 <= height <= MAX_AREA):
        raise ToolError(f'width/height must be 1..{MAX_AREA}')
    if field not in ('z', 'nswe', 'dirs', 'layers'):
        raise ToolError("field must be 'z', 'nswe', 'dirs' or 'layers'")
    if layer not in ('top', 'bottom'):
        raise ToolError("layer must be 'top' or 'bottom'")
    rows = []
    for yy in range(gy, min(gy + height, CELLS)):
        row = []
        for xx in range(gx, min(gx + width, CELLS)):
            ls = _layers(blocks, xx, yy)
            if field == 'layers':
                row.append(len(ls))
                continue
            z, n = max(ls) if layer == 'top' else min(ls)
            row.append(z if field == 'z' else n if field == 'nswe' else _dirs(n))
        rows.append(row)
    return {'origin_geo': [gx, gy], 'field': field, 'layer': layer,
            'axes': 'rows[gy][gx], +x East, +y South', 'rows': rows}


def tool_diagnose(path, max_issues=50, cliff_threshold=48, min_clearance=32):
    from .diagnostics import GeoDiagnosticEngine
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ToolError(f'file not found: {path}')
    eng = GeoDiagnosticEngine(cliff_threshold=int(cliff_threshold),
                              min_clearance=int(min_clearance))
    return eng.analyze(path, max_issues=int(max_issues))


def tool_diff(path_a, path_b, max_samples=50, z_tolerance=16):
    a, b = _blocks(path_a), _blocks(path_b)
    if region_of(path_a) != region_of(path_b):
        raise ToolError('files belong to different regions')
    max_samples, z_tolerance = int(max_samples), int(z_tolerance)
    stats = collections.Counter()
    samples = []
    for bi in range(BLOCKS):
        if a[bi] == b[bi]:
            continue
        stats['blocks'] += 1
        bx, by = divmod(bi, 256)
        for ci in range(64):
            la, lb = a[bi][ci], b[bi][ci]
            if la == lb:
                continue
            kinds = []
            if len(la) != len(lb):
                kinds.append('layer_count')
            ta, tb = max(la), max(lb)
            if abs(ta[0] - tb[0]) > z_tolerance:
                kinds.append('height')
            if ta[1] != tb[1]:
                kinds.append('nswe')
            if not kinds:
                kinds.append('minor')
            stats['cells'] += 1
            for k in kinds:
                stats[k] += 1
            if len(samples) < max_samples:
                gx, gy = bx * 8 + ci // 8, by * 8 + ci % 8
                samples.append({'geo': [gx, gy], 'world': list(_world(path_a, gx, gy)),
                                'kinds': kinds,
                                'a': [[z, _dirs(n)] for z, n in la],
                                'b': [[z, _dirs(n)] for z, n in lb]})
    return {'identical': stats['cells'] == 0,
            'differing_blocks': stats['blocks'], 'differing_cells': stats['cells'],
            'by_kind': {k: stats[k] for k in ('layer_count', 'height', 'nswe', 'minor')},
            'samples': samples}


def tool_validate(path):
    from .convert import validate_l2j_bytes, validate_pts_bytes
    path = os.path.abspath(os.path.expanduser(path))
    fmt = sniff_format(path)
    if not fmt or not os.path.isfile(path):
        raise ToolError(f'not a geodata file: {path}')
    data = open_bytes(path)
    try:
        if fmt == 'pts':
            validate_pts_bytes(data)
        else:
            validate_l2j_bytes(L2GCodec.decrypt(data) if fmt == 'l2g' else data)
    except GeoError as e:
        return {'valid': False, 'format': fmt, 'error': str(e)}
    return {'valid': True, 'format': fmt}


def tool_convert(src, dst, protocol=PROTO_GD):
    from .convert import l2j2pts_bytes
    src, dst = (os.path.abspath(os.path.expanduser(p)) for p in (src, dst))
    out_fmt = sniff_format(dst)
    if not out_fmt:
        raise ToolError('dst must end in .l2j, .l2g or .dat')
    if not os.path.isfile(src) or not sniff_format(src):
        raise ToolError(f'not a geodata file: {src}')
    l2j = _l2j_bytes(src)
    if out_fmt == 'l2g':
        out = L2GCodec.encrypt(l2j)
    elif out_fmt == 'pts':
        rx, ry = region_of(dst) if re.match(r'^\d+_\d+', os.path.basename(dst)) else region_of(src)
        out = l2j2pts_bytes(l2j, rx, ry, protocol)[0]
    else:
        out = l2j
    os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(out)
    return {'src': src, 'dst': dst, 'format': out_fmt, 'size_bytes': len(out)}


def tool_unr_info(path, collision=True):
    from .meshes import level_extra_triangles
    from .unreal import Package, read_properties
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ToolError(f'file not found: {path}')
    pkg = Package(path)
    classes = collections.Counter(pkg.class_name(e) for e in pkg.exports)
    res = {
        'path': path, 'version': pkg.version, 'licensee': pkg.licensee,
        'names': len(pkg.names), 'exports': len(pkg.exports), 'imports': len(pkg.imports),
        'classes': dict(classes.most_common(30)),
        'terrain': [],
    }
    for ti in pkg.find_exports('TerrainInfo'):
        pr = read_properties(pkg, ti)
        tm = pr.get('TerrainMap')
        res['terrain'].append({
            'location': pr.get('Location'), 'scale': pr.get('TerrainScale'),
            'heightmap': pkg.obj_name(tm) if isinstance(tm, int) else None,
            'heightmap_package': pkg.import_package(tm) if isinstance(tm, int) else None,
        })
    if collision:
        solid, blocking = level_extra_triangles(pkg)
        res['collision'] = {'bsp_solid_triangles': len(solid),
                            'blocking_triangles': len(blocking),
                            'static_mesh_actors': classes.get('StaticMeshActor', 0)}
    return res


def tool_run_tests(k=None, slow=False, files=None, timeout=900):
    """Run the project's pytest suite; returns pass/fail counts and failures."""
    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', '-rf']
    if not slow:
        cmd += ['-m', 'not slow']
    if k:
        cmd += ['-k', str(k)]
    if files:
        cmd += [str(f) for f in (files if isinstance(files, list) else [files])]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=_ROOT, capture_output=True, text=True,
                           timeout=int(timeout))
    except FileNotFoundError:
        raise ToolError('pytest is not installed (pip install -r requirements-dev.txt)')
    except subprocess.TimeoutExpired:
        raise ToolError(f'tests exceeded {timeout}s')
    out = p.stdout + p.stderr
    summary = next((ln.strip('= ') for ln in reversed(out.splitlines())
                    if re.search(r'\d+ (passed|failed|errors?|deselected|skipped)|no tests ran', ln)), '')
    if p.returncode == 5:                # pytest: nothing collected / selected
        summary = f'no tests selected ({summary})'
    counts = {k2: int(v) for v, k2 in re.findall(r'(\d+) (passed|failed|skipped|deselected|errors?)', summary)}
    return {'ok': p.returncode == 0, 'summary': summary, 'counts': counts,
            'failed': re.findall(r'^FAILED (\S+)', out, re.M),
            'seconds': round(time.time() - t0, 1),
            'tail': out[-4000:] if p.returncode else ''}


# ───────────────────────────── registry ─────────────────────────────

_PATH = {'type': 'string', 'description': 'Geodata file: XX_YY.l2j, XX_YY.l2g or XX_YY_conv.dat'}
_CELL = {
    'gx': {'type': 'integer', 'description': 'Cell X inside the region (0..2047)'},
    'gy': {'type': 'integer', 'description': 'Cell Y inside the region (0..2047)'},
    'x': {'type': 'integer', 'description': 'World X (alternative to gx)'},
    'y': {'type': 'integer', 'description': 'World Y (alternative to gy)'},
}

TOOLS = {
    'info': (tool_info, 'Region summary: format, block type counts, Z range, max layers.',
             {'path': _PATH}, ['path']),
    'cell': (tool_cell, 'All layers (z, NSWE flags) of one cell, by cell or world coordinates.',
             dict(path=_PATH, **_CELL), ['path']),
    'area': (tool_area, f'Grid of up to {MAX_AREA}x{MAX_AREA} cells (top/bottom layer z, nswe, dirs or layer count).',
             dict(path=_PATH, **_CELL,
                  width={'type': 'integer', 'default': 16},
                  height={'type': 'integer', 'default': 16},
                  field={'type': 'string', 'enum': ['z', 'nswe', 'dirs', 'layers'], 'default': 'z'},
                  layer={'type': 'string', 'enum': ['top', 'bottom'], 'default': 'top'}),
             ['path']),
    'diagnose': (tool_diagnose, 'Find one-way flags, cliff drops, layer squeezes and out-of-range Z (read only).',
                 {'path': _PATH, 'max_issues': {'type': 'integer', 'default': 50},
                  'cliff_threshold': {'type': 'integer', 'default': 48},
                  'min_clearance': {'type': 'integer', 'default': 32}}, ['path']),
    'diff': (tool_diff, 'Cell-by-cell comparison of two geodata files of the same region.',
             {'path_a': _PATH, 'path_b': _PATH,
              'max_samples': {'type': 'integer', 'default': 50},
              'z_tolerance': {'type': 'integer', 'default': 16}}, ['path_a', 'path_b']),
    'validate': (tool_validate, 'Structural validation of a geodata file.', {'path': _PATH}, ['path']),
    'convert': (tool_convert, 'Convert between .l2j, .l2g and _conv.dat (format from extensions).',
                {'src': _PATH, 'dst': _PATH,
                 'protocol': {'type': 'string', 'default': 'gd', 'description': 'PTS header protocol: gd or 286'}},
                ['src', 'dst']),
    'unr_info': (tool_unr_info, 'Inspect a client .unr map: version, classes, TerrainInfo, collision counts.',
                 {'path': {'type': 'string', 'description': 'Maps/XX_YY.unr'},
                  'collision': {'type': 'boolean', 'default': True}}, ['path']),
    'run_tests': (tool_run_tests, 'Run the test suite (fast subset by default) and report failures.',
                  {'k': {'type': 'string', 'description': 'pytest -k expression'},
                   'slow': {'type': 'boolean', 'default': False, 'description': 'include slow full-region tests'},
                   'files': {'type': 'array', 'items': {'type': 'string'}},
                   'timeout': {'type': 'integer', 'default': 900}}, []),
}


def tool_schemas():
    return [{'name': name, 'description': desc,
             'inputSchema': {'type': 'object', 'properties': props, 'required': req,
                             'additionalProperties': False}}
            for name, (_, desc, props, req) in TOOLS.items()]


def call(name, args=None):
    """Run a tool → {'ok': True, 'result': ...} or {'ok': False, 'error': ...}."""
    if name not in TOOLS:
        return {'ok': False, 'error': f'unknown tool {name!r}; available: {", ".join(TOOLS)}'}
    fn, _, props, req = TOOLS[name]
    args = dict(args or {})
    unknown = sorted(set(args) - set(props))
    missing = [r for r in req if r not in args]
    if unknown or missing:
        return {'ok': False, 'error': f'unknown args {unknown}, missing args {missing}'}
    log = io.StringIO()
    t0 = time.time()
    try:
        with contextlib.redirect_stdout(log):
            result = fn(**args)
        out = {'ok': True, 'result': result}
    except (ToolError, GeoError, OSError, ValueError) as e:
        out = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    except Exception as e:  # keep the server alive on unexpected failures
        out = {'ok': False, 'error': f'{type(e).__name__}: {e}'}
    out['ms'] = int((time.time() - t0) * 1000)
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', log.getvalue()).strip()
    if text:
        out['log'] = text[-2000:]
    return out


# ───────────────────────────── LLM CLI ─────────────────────────────

def _parse_value(v):
    try:
        return json.loads(v)
    except ValueError:
        return v


def cli_main(argv):
    """geotool.py llm <tool> key=value ... | llm list | llm <tool> --json '{...}'"""
    if not argv or argv[0] in ('list', '-h', '--help'):
        print(json.dumps({'ok': True, 'tools': tool_schemas(),
                          'usage': 'geotool.py llm <tool> key=value ... (values parsed as JSON when possible)'},
                         ensure_ascii=False))
        return 0
    name, rest = argv[0], argv[1:]
    args = {}
    if rest and rest[0] == '--json':
        args = json.loads(rest[1] if len(rest) > 1 else sys.stdin.read())
    else:
        for item in rest:
            if '=' not in item:
                print(json.dumps({'ok': False, 'error': f'expected key=value, got {item!r}'}))
                return 2
            k, v = item.split('=', 1)
            args[k.lstrip('-').replace('-', '_')] = _parse_value(v)
    out = call(name, args)
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out['ok'] else 1


# ───────────────────────────── MCP server ─────────────────────────────

def _mcp_handle(msg):
    method = msg.get('method')
    mid = msg.get('id')
    if mid is None:                      # notification (e.g. notifications/initialized)
        return None
    if method == 'initialize':
        client = (msg.get('params') or {}).get('protocolVersion') or MCP_PROTOCOL
        result = {'protocolVersion': client,
                  'capabilities': {'tools': {'listChanged': False}},
                  'serverInfo': {'name': SERVER_NAME, 'version': SERVER_VERSION},
                  'instructions': 'Lineage 2 geodata tools. Paths are local files; '
                                  'regions are cached between calls.'}
    elif method == 'ping':
        result = {}
    elif method == 'tools/list':
        result = {'tools': tool_schemas()}
    elif method == 'tools/call':
        params = msg.get('params') or {}
        out = call(params.get('name'), params.get('arguments') or {})
        payload = out['result'] if out['ok'] else {'error': out['error']}
        if 'log' in out:
            payload = {'result': payload, 'log': out['log']} if out['ok'] else dict(payload, log=out['log'])
        result = {'content': [{'type': 'text', 'text': json.dumps(payload, ensure_ascii=False)}],
                  'isError': not out['ok']}
        if out['ok'] and isinstance(out['result'], dict):
            result['structuredContent'] = out['result']
    else:
        return {'jsonrpc': '2.0', 'id': mid,
                'error': {'code': -32601, 'message': f'method not found: {method}'}}
    return {'jsonrpc': '2.0', 'id': mid, 'result': result}


def mcp_main(stdin=None, stdout=None):
    """Newline-delimited JSON-RPC 2.0 over stdio (MCP stdio transport)."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            resp = {'jsonrpc': '2.0', 'id': None,
                    'error': {'code': -32700, 'message': 'parse error'}}
        else:
            resp = _mcp_handle(msg) if isinstance(msg, dict) else {
                'jsonrpc': '2.0', 'id': None,
                'error': {'code': -32600, 'message': 'invalid request'}}
        if resp is not None:
            stdout.write(json.dumps(resp, ensure_ascii=False) + '\n')
            stdout.flush()
    return 0
