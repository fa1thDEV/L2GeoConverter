#!/usr/bin/env python3
"""Build spawn-failure catalog JSON for the geodata viewer."""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
from pathlib import Path

REGION = 32768


def region_of(wx, wy):
    rx = math.floor(wx / REGION) + 20
    ry = math.floor(wy / REGION) + 18
    return f"{rx}_{ry}", rx, ry


def geo_size(geodir, region):
    p = geodir / f"{region}_conv.dat"
    if not p.is_file():
        return None, True
    sz = p.stat().st_size
    return sz, sz in (196608, 393234) or sz < 600000


def main():
    ap = argparse.ArgumentParser(description='Build spawn-failure catalog JSON for the viewer')
    ap.add_argument('--err', required=True, help='NPC err log (Cannot generate random position…)')
    ap.add_argument('--npcpos', required=True, help='npcpos.txt')
    ap.add_argument('--geodata', required=True, help='folder with *_conv.dat')
    ap.add_argument('-o', '--out', required=True, help='output JSON')
    args = ap.parse_args()
    err_path = Path(args.err)
    npc_path = Path(args.npcpos)
    geodir = Path(args.geodata)
    out_path = Path(args.out)

    err = err_path.read_text(encoding="utf-8", errors="replace")
    counts = collections.defaultdict(lambda: collections.Counter())
    centers = {}
    for m in re.finditer(r"Cannot generate random position in territory\[([^\]]+)\]", err):
        counts[m.group(1)]["pos"] += 1
    for m in re.finditer(r"Cannot generate random position sky in territory\[([^\]]+)\]", err):
        counts[m.group(1)]["sky"] += 1
    for m in re.finditer(
        r"CenterPos\(([-0-9]+),([-0-9]+),([-0-9]+)\) of territory\[([^\]]+)\] is not inside",
        err,
    ):
        name = m.group(4)
        counts[name]["center"] += 1
        centers[name] = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    for m in re.finditer(r"Cannot generate random postion in npcmaker, 1st territory\[([^\]]+)\]", err):
        counts[m.group(1)]["maker"] += 1
    for m in re.finditer(r"picking random pos from null random pos \[([^\]]+)\]", err):
        counts[m.group(1)]["roam"] += 1

    raw = npc_path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] == b"\xff\xfe" else raw.decode("utf-8", errors="replace")
    terr = {}
    for m in re.finditer(
        r"territory_begin\s*\[([^\]]+)\]\s*\{(.+?)\}\s*territory_end",
        text,
        re.S,
    ):
        name, body = m.group(1), m.group(2)
        verts = []
        for vx in re.finditer(r"\{(-?\d+);(-?\d+);(-?\d+);(-?\d+)\}", body):
            verts.append((int(vx.group(1)), int(vx.group(2)), int(vx.group(3)), int(vx.group(4))))
        if verts:
            terr[name] = verts

    spawns = []
    buckets = collections.Counter()
    for name, c in sorted(counts.items()):
        verts = terr.get(name, [])
        if verts:
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            zmin = min(v[2] for v in verts)
            zmax = max(v[3] for v in verts)
            cx = sum(xs) // len(xs)
            cy = sum(ys) // len(ys)
        else:
            zmin = zmax = cx = cy = None
        if name in centers:
            wx, wy, geo_z = centers[name]
        else:
            wx, wy, geo_z = cx, cy, None
        if wx is None:
            continue
        region, rx, ry = region_of(wx, wy)
        gsz, stubby = geo_size(geodir, region)
        side, delta = "unknown", None
        if geo_z is not None and zmin is not None:
            if geo_z > zmax:
                side, delta = "above", geo_z - zmax
            elif geo_z < zmin:
                side, delta = "below", zmin - geo_z
            else:
                side, delta = "in_z", 0
        ocean = geo_z is not None and -4720 <= geo_z <= -4580
        old_ti = (
            "1725" in name
            or name.startswith("gludio25_")
            or "gludio_npc1725" in name
            or region == "17_25"
        )
        broken = zmax is not None and (zmax > 50000 or (zmin is not None and zmin > 10000))
        if c["sky"] and not c["pos"] and not c["center"]:
            bucket, action = "skip_sky", "ignore"
        elif old_ti:
            bucket, action = "skip_old_ti", "ignore"
        elif broken:
            bucket, action = "skip_broken", "ignore"
        elif ocean and (stubby or region == "17_25"):
            bucket, action = "skip_stub", "ignore"
        elif ocean:
            bucket, action = "hole", "move_xy"
        elif delta is not None and delta <= 200:
            bucket, action = "near_z", "widen_z"
        elif delta is not None and delta > 200:
            bucket, action = "wrong_floor", "check_floor"
        elif c["sky"]:
            bucket, action = "skip_sky", "ignore"
        else:
            bucket, action = "no_geo_hit", "move_xy"
        buckets[bucket] += 1
        gx = int((wx - (rx - 20) * REGION) // 16)
        gy = int((wy - (ry - 18) * REGION) // 16)
        spawns.append({
            "name": name,
            "region": region,
            "wx": wx,
            "wy": wy,
            "geo_z": geo_z,
            "zmin": zmin,
            "zmax": zmax,
            "delta": delta,
            "side": side,
            "bucket": bucket,
            "action": action,
            "geo_bytes": gsz,
            "bx": max(0, min(255, gx // 8)),
            "by": max(0, min(255, gy // 8)),
            "cx": gx % 8,
            "cy": gy % 8,
            "poly": [[v[0], v[1]] for v in verts],
            "counts": dict(c),
        })

    out_path.write_text(json.dumps({
        "source": str(err_path),
        "geodata": str(geodir),
        "counts": dict(buckets),
        "spawns": spawns,
    }, indent=1), encoding="utf-8")
    print("wrote", out_path, "spawns", len(spawns))
    print("buckets:")
    for k, n in buckets.most_common():
        print(f"  {n:4} {k}")
    print("regions:", len({s["region"] for s in spawns}))
    print("\nnear_z (widen window) by region:")
    byr = collections.Counter(s["region"] for s in spawns if s["bucket"] == "near_z")
    for r, n in byr.most_common():
        print(f"  {n:3} {r}")
    print("\nhole (move XY) by region:")
    byr = collections.Counter(s["region"] for s in spawns if s["bucket"] == "hole")
    for r, n in byr.most_common():
        print(f"  {n:3} {r}")
    print("\nwrong_floor by region:")
    byr = collections.Counter(s["region"] for s in spawns if s["bucket"] == "wrong_floor")
    for r, n in byr.most_common(12):
        print(f"  {n:3} {r}")


if __name__ == "__main__":
    main()
