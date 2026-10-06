<p align="center">
  <img src="assets/logo.png" alt="L2 Geodata Converter" width="560">
</p>

# L2GeoConverter

Lineage 2 geodata conversion, validation and client map generation toolkit.

Supports Lucera 2 (`.l2g`), standard Java emulators (`.l2j`), and official PTS/L2Off binary files (`_conv.dat`).

[Releases](https://github.com/fa1thDEV/L2GeoConverter/releases/latest) | [Visual Guide & Mechanics](docs/GUIDE.md) | [Manual en Español](docs/MANUAL-GEOCONVERTER_ES.md) | [Russian documentation](README_RU.md)

---

## Features

- **Format conversion**: Bi-directional conversion between `.l2g` (Lucera 2 encrypted format), `.l2j` (standard 64k-block raw format), and PTS `_conv.dat` (NCSoft layer format, supporting `gd` and `286` protocols).
- **Integrity checks & auto-repair**: Scans for one-way NSWE border mismatches, steep cliff drops (|ΔZ| > 48) that cause players to fall through terrain, and layer clearances below 32 units. The `--fix` switch patches these values in place.
- **Pack diffing**: Cell-by-cell comparison between two geodata directories (supports `.l2j`, `.l2g`, and `_conv.dat`). Identifies surface discrepancies, elevation offsets (|Δh| > 16), and NSWE directional divergence with ASCII mismatch maps.
- **Spawn validator**: Audits `npcpos.txt` spawn records against geodata layers to detect NPCs falling through terrain, spawning in the ocean, or embedded inside walls.
- **Client map extraction**: Reads `.unr` level packages alongside static mesh assets using raycasting and stair-step clearance filters to prevent false floors or impassable steps.
- **Pathnode compiler**: 64-bit multi-threaded compiler emitting `pathnode.bin` and `pathnode.idx` from geodata with line-of-sight checks.
- **Local web viewer**: Embedded HTTP viewer on port 8777 showing 2D layer slicing, cell block types, and 3D wireframe mesh overlays.
- **Desktop UI**: Native Tkinter interface with tabs for format conversion, auto-repair diagnostics, UNR generation, pack diffing, spawn validation, and the web viewer.

---

## Usage

### Desktop GUI
Run `L2GeoConverter.exe` or `python gui.py`. A simple desktop window will open with file pickers for conversion, diagnostics, map generation, pack comparison, spawn validation, and the web viewer.

### Command Line
You can also run the CLI entrypoint directly:

```bash
# Convert PTS to L2J
python geotool.py convert path/to/20_20_conv.dat -o ./output -y

# Decrypt Lucera 2 .l2g to standard .l2j
python geotool.py l2g2l2j path/to/16_20.l2g -o ./output -y

# Encrypt .l2j to Lucera 2 .l2g
python geotool.py l2j2l2g path/to/16_20.l2j -o ./output -y

# Convert L2J to PTS (_conv.dat)
python geotool.py l2j2pts path/to/20_20.l2j -o ./output -y

# Run validation checks
python geotool.py diagnose path/to/geodata/

# Run validation and save patched files
python geotool.py diagnose path/to/geodata/ --fix -o ./repaired/

# Export diagnostics to JSON
python geotool.py diagnose path/to/geodata/ --json

# Compare two geodata packs
python geotool.py diff path/to/packA path/to/packB [--region 20_20]

# Validate NPC spawns against geodata
python geotool.py spawncheck path/to/geodata --npcpos path/to/npcpos.txt [-o report.json]

# Start the web viewer
python geotool.py view path/to/geodata/ --port 8777

# Generate geodata from game client
python geotool.py generate path/to/client/ -o ./output --region 20_20
```

On Windows, `GeoConverter.bat` is provided as a shortcut for drag-and-drop file processing and quick tasks.

---

## Visual Guide & Geodata Mechanics

### 1. NSWE Directional Flags & Creating Invisible Barriers

In Lineage 2 geodata, each cell (16x16 world units) stores an elevation ($Z$) and a 4-bit bitmask determining which neighboring cells a character can move into:

| Bit | Flag | Direction | Hex Value | Description |
|---|---|---|---|---|
| bit 0 | `FLAG_EAST` | +X | `0x01` | Allows step East |
| bit 1 | `FLAG_WEST` | -X | `0x02` | Allows step West |
| bit 2 | `FLAG_SOUTH` | +Y | `0x04` | Allows step South |
| bit 3 | `FLAG_NORTH` | -Y | `0x08` | Allows step North |
| bits 0-3 | `FLAG_ALL` | Any | `0x0F` | Completely open ground |
| 0 bits | `FLAG_NONE` | None | `0x00` | Solid obstacle / pillar |

<p align="center">
  <img src="docs/images/02_invisible_barriers.png" alt="NSWE Flags & Invisible Barriers" width="900">
</p>

#### How to construct an Invisible Wall
1. **Directional Boundary Wall**: Leave the elevation $Z$ of both cells identical (e.g., $Z=100$), but strip the crossing bitmask:
   - On Cell A $(gx, gy)$: `nswe &= ~FLAG_EAST` (`0x01`).
   - On Cell B $(gx+1, gy)$: `nswe &= ~FLAG_WEST` (`0x02`).
   The player's client renders open, flat terrain, but the server collision matrix rejects movement packets attempting to cross the boundary.
2. **Solid Column**: Set the target cell's bitmask to `0x00` (`FLAG_NONE`). Characters cannot enter this 16x16 coordinate column from any angle.
3. **One-Way Traps (`NSWE_ASYMMETRY`)**: If Cell A allows East movement but Cell B forbids West return, a player walking into Cell B becomes permanently stuck. The diagnostic engine scans for this asymmetry; `--fix` closes the open side (it never opens a closed flag, since the original collision is not available to prove the passage is real).

---

### 2. Cliff Drops & Archway Preservation (Giran Fix)

<p align="center">
  <img src="docs/images/03_cliff_repair.png" alt="Cliff Falls & Archways" width="900">
</p>

* **Hazardous Cliff Drops (`CLIFF_FALL`)**: When adjacent cells differ in elevation by $|\Delta Z| > 48$ with an open passage flag toward the drop, players fall off cliffs and clip through the terrain into the ocean. The repair engine strips the drop flag on the upper cell.
* **Archway Doorway Preservation**: In city portals and arches (e.g., Giran, Dion), the arch cell has multiple layers (ground $Z=96$, arch roof $Z=384$) adjacent to an outdoor street cell ($Z=96$). Naive repair algorithms that block both cells unintentionally strip the outdoor ground flag and brick the gate. L2GeoConverter applies cliff blocking **strictly to the higher layer towards the drop**, preserving 100% ground walkability through doorways.

---

### 3. Block Structure & Vertical Clearance

<p align="center">
  <img src="docs/images/04_block_types.png" alt="Block Types & Multilayer Clearance" width="900">
</p>

* **Type 0 (Flat)**: Single $Z$ coordinate for all 64 cells in the block. Encoded in 2 bytes.
* **Type 1 (Complex)**: 64 independent cells, each with individual $Z$ and 4-bit NSWE.
* **Type 2 (Multilayer)**: Variable number of layers per cell (bridges, castles, multi-floor dungeons). Consecutive layers must maintain at least 32 units of vertical clearance to prevent camera clipping and character rubberbanding.

---

## Technical Details

### Lucera 2 (.l2g) format
Lucera 2 wraps standard 65,536-block L2J data in a rolling XOR/subtraction stream cipher with a 4-byte header:
1. `key = read_u32_le(0) ^ 0x814467AB`
2. Decryption loop updates the running key with signed 8-bit arithmetic: `key = (key - decrypted_byte) & 0xFFFFFFFF`.
3. Checksum verification checks that the final remainder matches the header digest.

### Known Limitations
- The client map generator (`generate`) requires direct access to client packages (`Maps`, `StaticMeshes`). Complex multi-material meshes with dynamic collision properties may need manual touch-ups after generation.
- Raycasting performance on large client folders benefits significantly from Taichi (`pip install taichi`), but runs on CPU fallback if not installed.
- Pathnode generation on large maps is memory intensive. It is recommended to have at least 4 GB of free RAM when running multi-threaded pathnode builds.

---

## Building from source

Requirements: Python 3.8+. The core toolkit uses only the standard library; optional extras:

```bash
pip install -r requirements.txt        # Pillow: GUI image scaling (Tkinter must be present)
pip install -r requirements-accel.txt  # Taichi + NumPy: faster `generate` raycasting
```

### Running the tests

```bash
pip install -r requirements-dev.txt
python -m pytest -m "not slow"   # fast loop (~20 s)
python -m pytest                 # full suite, including heavy full-region tests
```

Tests that parse a real Lineage 2 client are skipped unless `L2_CLIENT_DIR` (client root with `Maps/`, `Textures/`, `StaticMeshes/`) and `L2_GEODATA_DIR` (server geodata folder) point at one. CI runs lint plus the test suite on Linux and Windows for every push.

### Standalone executable

To build the standalone Windows executable:
```bash
pip install pyinstaller
python -m PyInstaller --clean --onefile --name L2GeoConverter --collect-all geolib --add-data "assets;assets" geotool.py
```

---

## License

MIT
