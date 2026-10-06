# Contributing

Python 3.8+, core is stdlib only. Library code is in `geolib/`; `geotool.py`
is the CLI, `gui.py` the Tkinter entry point (tabs live in `geolib/gui/`).

## Checks

- Tests: `python -m pytest -m "not slow"` (~25 s). Full suite: `python -m pytest` (~6 min).
- Lint enforced by CI: `ruff check --select E9,F63,F7,F82 .`
- GUI tests need Tk and a display; on Linux run them under `xvfb-run -a`.
- Tests that need a real client are skipped unless `L2_CLIENT_DIR` and
  `L2_GEODATA_DIR` are set.

## Conventions

- Cell layers are `(z, nswe)`; NSWE bits are E=1, W=2, S=4, N=8. Heights are
  quantized to 8 units. Blocks are indexed `bx * 256 + by`, cells `cx * 8 + cy`.
- Flat blocks from `parse_region` share one list object across their 64
  cells: write through `geolib.diagnostics.set_cell_layers`, never in place.
- `diagnose --fix` never opens a closed NSWE flag (see docs/L2MAPCONV_SYNC.md).
- Quick inspection without scripts: `python geotool.py llm list` (JSON mode).
