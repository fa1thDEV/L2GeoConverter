#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare generated geodata layers to a Z-ray through client collision."""

from .generate import CELLS, _column, _span_layers

# L2J stores height in 8-unit steps; allow a bit more than LAYER_MERGE (24).
MATCH_Z = 32


def _geo_cell_zs(blocks, gx, gy):
    bx, cx = divmod(gx, 8)
    by, cy = divmod(gy, 8)
    cell = blocks[bx * 256 + by][cx * 8 + cy]
    return [h for h, _n in cell]


def _unr_cell_zs(geom, gx, gy):
    west, north = geom['west'], geom['north']
    px = west + gx * 16 + 8
    py = north + gy * 16 + 8
    cell = gy * CELLS + gx
    fl, ce = _column(px, py, geom['fc_grid'].get(cell, ()), geom['fc'])
    return _span_layers(fl, ce, [geom['hcell'][gy][gx]])


def _diff_zs(geo_zs, unr_zs):
    miss = [z for z in unr_zs if not any(abs(z - g) <= MATCH_Z for g in geo_zs)]
    extra = [z for z in geo_zs if not any(abs(z - u) <= MATCH_Z for u in unr_zs)]
    return miss, extra


def cell_mismatch(geom, blocks, gx, gy):
    """One cell: UNR walkable floors vs geo layers."""
    geo = _geo_cell_zs(blocks, gx, gy)
    unr = _unr_cell_zs(geom, gx, gy)
    miss, extra = _diff_zs(geo, unr)
    return {
        'gx': gx, 'gy': gy,
        'geo': geo, 'unr': unr,
        'miss': miss, 'extra': extra,
    }


def region_mismatch_grid(geom, blocks):
    """256×256 block-center samples. Sparse list of disagreeing blocks.

    Samples cell (4,4) of each block — fast enough for the viewer overlay.
    miss = UNR floor with no geo layer; extra = geo layer with no UNR floor.
    Canopy materials with EnableCollision off never become layers. Solid
    disconnected floors (roofs, dungeon slabs) are kept in generate."""
    hits = []
    nmiss = nextra = 0
    for bx in range(256):
        for by in range(256):
            gx, gy = bx * 8 + 4, by * 8 + 4
            geo = _geo_cell_zs(blocks, gx, gy)
            unr = _unr_cell_zs(geom, gx, gy)
            miss, extra = _diff_zs(geo, unr)
            if not miss and not extra:
                continue
            nmiss += len(miss)
            nextra += len(extra)
            hits.append({
                'bx': bx, 'by': by,
                'miss': len(miss), 'extra': len(extra),
                'unr': unr, 'geo': geo,
            })
    return {
        'nmiss': nmiss, 'nextra': nextra, 'nblocks': len(hits),
        'merge': MATCH_Z, 'sample': 'block-center',
        'b': hits,
    }
