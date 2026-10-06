# l2mapconv-public sync notes

Compared against [m49n/l2mapconv-public](https://github.com/m49n/l2mapconv-public)
at `bcc0bd2` (2026-10-05). l2mapconv is C++ (Recast/Detour); this toolkit
reimplements the geodata-relevant parts in Python, so changes are ported by
behaviour, not by code.

## Geodata generation / export

| l2mapconv change | Status here |
|---|---|
| `4903fb0` PTS header: first u32 = serialized cells (layer sum); a multilayer block with exactly 64 layers counts as complex | Already matched: `pack_pts_header` protocol `gd`, `l2j2pts_bytes` writes 64-layer multilayer blocks as complex |
| `e2877dd` reject heights outside int16 / packed range `[-16384, 16376]` | Covered differently: `_enc_layer` / `quant_h` clamp to the packed range |
| `e2877dd` max 64 layers per column | Covered: `_span_layers` caps at 120 (parser limit 125) |
| `e2877dd` NSWE: discarded (null-area) spans are never a landing layer | Already matched: neighbour layers come from accepted floors only (`_span_layers`) |
| `7dadb28` resolve Unreal asset references case-insensitively | **Ported**: `MeshLibrary.get` falls back to a case-insensitive mesh name match (`tests/test_mesh_library.py`) |
| Decryption Ver111 / Ver121 | Already matched (`geolib/unreal.py`) |

## Review of this repository (`docs/research/L2G_CLIFF_FIX_REVIEW.md` upstream)

| Finding | Status here |
|---|---|
| Arch fix: lower passage preserved | Kept; regression test `test_arch_lower_passage_preserved` |
| Small-step asymmetry repair force-opens a closed flag without the original collision | **Fixed**: the open side is closed instead |
| Upper layer only on the neighbour is never paired, so its drop stays open | **Fixed**: layers are paired by nearest height from both cells (`_repair_boundary`) |
| `analyze` only looked East/South, so W/N drops were never reported | **Fixed**: all four directions |
| ResourceWarning: unclosed files | **Fixed** across `geolib` and tests |
| Keep reversible L2G packing separate from automatic repair | Already separate (repair only runs in `diagnose --fix`); the GUI repair checkbox now defaults to off |

## Not ported

- Tiled Recast/Detour navmesh and the Pathfinding Lab: experimental upstream,
  C++/Java toolchain, and not a server geodata format.
- Territory/radar rendering, live P542 materials, water and shadows: viewer
  features, not geodata.
- Essence P542 package specifics (material deserializers for licensee ≥ 37):
  only needed for textured rendering; geometry parsing already handles the
  tested licensee 37 maps (e.g. `14_24.unr`, file version 123).
