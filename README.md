# L2GeoConverter

Lineage 2 geodata conversion, validation and client map generation toolkit.

Supports Lucera 2 (`.l2g`), standard Java emulators (`.l2j`), and official PTS/L2Off binary files (`_conv.dat`).

[Releases](https://github.com/fa1thDEV/L2GeoConverter/releases/latest) | [Russian documentation](README_RU.md)

---

## Features

- **Format conversion**: Bi-directional conversion between `.l2g` (Lucera 2 encrypted format), `.l2j` (standard 64k-block raw format), and PTS `_conv.dat` (NCSoft layer format, supporting `gd` and `286` protocols).
- **Integrity checks**: Scans for one-way NSWE border mismatches, steep cliff drops (|ΔZ| > 48) that cause players to fall through terrain, and layer clearances below 32 units. The `--fix` switch patches these values in place.
- **Client map extraction**: Reads `.unr` level packages alongside static mesh assets to build raw heightmaps and collision meshes without external Unreal tools.
- **Pathnode compiler**: 64-bit multi-threaded compiler emitting `pathnode.bin` and `pathnode.idx` from geodata with line-of-sight checks.
- **Local web viewer**: Embedded HTTP viewer on port 8777 showing 2D layer slicing, cell block types, and 3D wireframe mesh overlays.
- **Desktop UI**: Native Tkinter interface for file selection and batch operations.

---

## Usage

### Desktop GUI
Run `L2GeoConverter.exe` or `python gui.py`. A simple desktop window will open with file pickers for conversion, diagnostics, map generation, and the web viewer.

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

# Start the web viewer
python geotool.py view path/to/geodata/ --port 8777

# Generate geodata from game client
python geotool.py generate path/to/client/ -o ./output --region 20_20
```

On Windows, `GeoConverter.bat` is provided as a shortcut for drag-and-drop file processing and quick tasks.

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

Requirements: Python 3.8+ (standard library only).

To build the standalone Windows executable:
```bash
pip install pyinstaller
python -m PyInstaller --clean --onefile --name L2GeoConverter --collect-all geolib --add-data "assets;assets" geotool.py
```

---

## License

MIT
