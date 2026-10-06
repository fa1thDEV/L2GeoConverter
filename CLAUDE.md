# L2GeoConverter — notes for AI agents

Lineage 2 geodata toolkit (Python 3.8+, core is stdlib only). Library code is
in `geolib/`; `geotool.py` is the CLI, `gui.py` the Tkinter entry point
(tabs live in `geolib/gui/`).

## Fast feedback

- Tests: `python -m pytest -m "not slow"` (~25 s). Full suite: `python -m pytest` (~6 min).
- Lint that CI enforces: `ruff check --select E9,F63,F7,F82 .`
- GUI tests need Tk and a display; on Linux run under `xvfb-run -a`.
- Tests that need a real client are skipped unless `L2_CLIENT_DIR` and
  `L2_GEODATA_DIR` are set.

## Inspecting geodata without writing scripts

Use the JSON tools instead of ad-hoc Python (one JSON object per call):

```bash
python geotool.py llm list                                   # tool schemas
python geotool.py llm info path=geodata/22_22.l2j
python geotool.py llm cell path=geodata/22_22.l2j x=-130824 y=94856
python geotool.py llm area path=geodata/22_22.l2j gx=100 gy=200 width=16 height=16 field=dirs
python geotool.py llm diagnose path=geodata/22_22.l2j max_issues=20
python geotool.py llm diff path_a=a/22_22.l2j path_b=b/22_22.l2g
python geotool.py llm unr_info path=client/Maps/22_22.unr
python geotool.py llm run_tests k=diagnose
```

The same tools are exposed as an MCP server (`python geotool.py mcp`,
registered in `.mcp.json` as `l2geo`), which caches parsed regions between
calls.

## Conventions

- Cell layers are `(z, nswe)`; NSWE bits are E=1, W=2, S=4, N=8. Heights are
  quantized to 8 units. Blocks are indexed `bx * 256 + by`, cells `cx * 8 + cy`.
- Flat blocks from `parse_region` share one list object across their 64
  cells: write through `geolib.diagnostics.set_cell_layers`, never in place.
- `diagnose --fix` never opens a closed NSWE flag (see docs/L2MAPCONV_SYNC.md).
