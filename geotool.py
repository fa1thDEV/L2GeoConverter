#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║  L2 Geodata Toolkit — convert, view, compare, verify, pathnode ║
╚══════════════════════════════════════════════════════════════╝

Interactive menu:  python3 geotool.py
Subcommands:
  convert <dir|files...> -o <dir> [-y]         converter PTS → L2J
  view   <dir> [--port N] [--spawns JSON] [--client DIR]  viewer (+ 3D / UNR)
  diff   <dirA> <dirB> [--region XX_YY]        compare two packs
  generate <client> -o <dir> [--region ...] [--format l2j|pts] [--protocol gd|286] [--doordata FILE]
                       [-j N] [--min-free-ram GB] [--max-cpu PCT]
                       gd also: interlude, hf, epilogue, glory
  check  <dir|files...>                        validation + stubs
  spawncheck <geodata> --npcpos FILE [-o JSON] npcpos vs geo (read-only)
  pathnode <geodata> [-o DIR] [--txt] [--region XX_YY ...] [-j N] [--min-free-ram GB] [--max-cpu PCT]
  verify <dir1> <dir2>                         PTS ↔ L2J check (any order)
  l2j2pts <file|dir> -o <dir> [--protocol gd|286]   reverse converter L2J → PTS
  l2g2l2j <dir|files...> -o <dir> [-y]         decrypt Lucera 2 .l2g → .l2j
  l2j2l2g <dir|files...> -o <dir> [-y]         encrypt .l2j → Lucera 2 .l2g
  diagnose <dir|files...> [-o <dir>] [--fix] [--json] validation and repair

Format specs: geolib/formats.py
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))

from geolib import (
    cmd_check, cmd_convert, cmd_diff, cmd_generate, cmd_l2j2pts,
    cmd_pathnode, cmd_spawncheck, cmd_verify, cmd_view,
    cmd_l2g2l2j, cmd_l2j2l2g, cmd_diagnose,
    cmd_l2g2pts, cmd_pts2l2g,
)
from geolib.doors import find_doordata
from geolib.formats import GeoError, PROTO_CLI_HELP, normalize_protocol
from geolib.resources import MAX_CPU_PCT, MIN_FREE_RAM_GB
from geolib.ui import BANNER, bold, cyan, dim


def ask(prompt, default=None):
    s = input(f'  {prompt}' + (f' [{dim(default)}]' if default else '') + ': ').strip().strip("'\"")
    return os.path.expanduser(s) if s else default


def ask_protocol(default='gd'):
    """PTS header: gd = official L2OFF (GD/Interlude/HF/Epilogue); 286 = official protocol 286."""
    raw = ask('PTS protocol (gd = official L2OFF layer-sum: GD/Interlude/HF/Epilogue; '
              '286 = official protocol 286 (cx+ml)*64)',
              default)
    try:
        return normalize_protocol(raw)
    except GeoError:
        print(f'  unknown protocol {raw!r} — using {default}')
        return default


def protocol_arg(s):
    try:
        return normalize_protocol(s)
    except GeoError as e:
        raise argparse.ArgumentTypeError(str(e))


def cpu_pct_arg(s):
    try:
        v = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError('CPU cap must be a number')
    if v < 1 or v > 100:
        raise argparse.ArgumentTypeError('CPU cap must be 1-100')
    return v


def _ensure_taichi(interactive_ok=True):
    """Check for Taichi — optional raycast accelerator (GPU on NVIDIA/CUDA,
    otherwise multithreaded CPU). Its absence is NOT an error: generation
    runs on pure Python with the same byte-for-byte result, just slower.
    If Taichi is missing — hint, and in an interactive TTY offer to install."""
    try:
        import taichi  # noqa: F401
        return
    except Exception:
        pass
    print(dim('\n  Taichi is not installed — generation will run on pure Python (CPU).'))
    print(dim('  The Taichi accelerator produces the same byte-for-byte result, but faster'))
    print(dim('  (GPU on NVIDIA/CUDA with f64 support, otherwise native multithreaded CPU).'))
    if not (interactive_ok and sys.stdin.isatty() and sys.stdout.isatty()):
        print(dim('  Install: pip install taichi\n'))
        return
    ans = input('  Install now (pip install taichi)? [y/N]: ').strip().lower()
    if ans not in ('y', 'yes', 'д', 'да'):
        print(dim('  Skipping. Later, manually: pip install taichi\n'))
        return
    import subprocess
    print(dim('  Installing taichi …'))
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'taichi'])
    except Exception as e:
        print(f'  ⚠ install failed: {e}')
        print(dim('  Continuing on pure Python. Later, manually: pip install taichi\n'))
        return
    try:
        import taichi  # noqa: F401  — check that it imports in this process
        print(dim('  Taichi installed — the accelerator will be used.\n'))
    except Exception:
        print(dim('  Installed, but does not import in the current process —'
                  ' restart geotool to enable it.\n'))


def _scan_regions(client_dir):
    """All Maps maps as filenames: XX_YY and XX_YY_Classic — separate squares."""
    import re as _re
    maps_dir = os.path.join(client_dir, 'Maps')
    if not os.path.isdir(maps_dir):
        maps_dir = os.path.join(client_dir, 'MAPS')
    if not os.path.isdir(maps_dir):
        return []
    listing = os.listdir(maps_dir)
    return sorted(m.group(1) for f in listing
                  for m in [_re.match(r'^(\d+_\d+.*?)\.unr$', f, _re.IGNORECASE)] if m)


def _pick_regions_tui(maps):
    """Interactive pick: arrows — navigate, Enter/Space — toggle,
    A — all, N — none, G — generate, Q — cancel."""
    import curses

    COLS = 5

    def run(scr):
        curses.curs_set(0)
        scr.keypad(True)
        sel = set()
        cur = 0
        n = len(maps)
        rows = (n + COLS - 1) // COLS
        top = 0                                    # first visible grid row
        while True:
            scr.erase()
            h, w = scr.getmaxyx()
            vis_rows = max(3, h - 4)
            crow, ccol = divmod(cur, COLS)
            if crow < top:
                top = crow
            elif crow >= top + vis_rows:
                top = crow - vis_rows + 1
            scr.addnstr(0, 0, f'Client squares: {n} · selected: {len(sel)}'
                        f'{" (Enter on G — all)" if not sel else ""}', w - 1,
                        curses.A_BOLD)
            if w < COLS * 18 + 1 or h < 6:        # window cannot fit the grid → text fallback
                return 'SMALL'
            for r in range(top, min(rows, top + vis_rows)):
                y = 1 + r - top
                for c in range(COLS):
                    i = r * COLS + c
                    if i >= n:
                        break
                    reg = maps[i]
                    box = '■' if i in sel else '·'
                    attr = curses.A_REVERSE if i == cur else curses.A_NORMAL
                    scr.addnstr(y, c * 18, f'{box} {reg}', min(17, w - 1 - c * 18), attr)
            scr.addnstr(h - 2, 0, '─' * min(78, w - 1), w - 1)
            scr.addnstr(h - 1, 0,
                        '←↑↓→ navigate · Enter/Space — toggle · '
                        'A — all · N — none · G — generate · Q — cancel',
                        w - 1, curses.A_DIM)
            key = scr.getch()
            if key in (curses.KEY_UP,) and cur >= COLS:
                cur -= COLS
            elif key == curses.KEY_DOWN and cur + COLS < n:
                cur += COLS
            elif key == curses.KEY_LEFT and cur > 0:
                cur -= 1
            elif key == curses.KEY_RIGHT and cur < n - 1:
                cur += 1
            elif key in (10, 13, curses.KEY_ENTER, ord(' ')):
                sel.symmetric_difference_update({cur})
            elif key in (ord('a'), ord('A'), ord('ф'), ord('Ф')):
                sel = set(range(n))
            elif key in (ord('n'), ord('N'), ord('т'), ord('Т')):
                sel = set()
            elif key in (ord('g'), ord('G'), ord('п'), ord('П')):
                return sorted(maps[i] for i in sel) if sel else None
            elif key in (27, ord('q'), ord('Q'), ord('й'), ord('Й')):
                return 'CANCEL'
    return curses.wrapper(run)


def _pick_regions(client_dir):
    """Pick squares: TUI with arrows; fallback — text input
    (numbers/ranges/names) if curses is unavailable (Windows) or not a TTY."""
    import re as _re
    maps = _scan_regions(client_dir)
    if not maps:
        return None
    if sys.stdin.isatty() and sys.stdout.isatty():
        try:
            import curses  # noqa: F401 — missing on Windows
            res = _pick_regions_tui(maps)
            if res != 'SMALL':                     # SMALL — window too small, text input below
                return res
        except ImportError:
            pass
        except Exception:
            pass                                   # broken TERM etc. — fallback
    print(f'\n  Client squares ({len(maps)}; XX_YY_Classic — a separate square):')
    per_row = 5
    for i in range(0, len(maps), per_row):
        row = ''
        for j, r in enumerate(maps[i:i + per_row], i + 1):
            row += f'{j:4d}) {r:<15} '
        print('  ' + row)
    raw = input('\n  Selection (Enter — all, numbers/ranges/names): ').strip()
    if not raw:
        return None
    chosen = []
    for tok in raw.replace(',', ' ').split():
        m = _re.match(r'^(\d+)-(\d+)$', tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            for k in range(min(a, b), max(a, b) + 1):
                if 1 <= k <= len(maps):
                    chosen.append(maps[k - 1])
        elif _re.match(r'^\d+_\d+', tok):          # map name (incl. _Classic)
            chosen.append(tok)
        elif tok.isdigit() and 1 <= int(tok) <= len(maps):
            chosen.append(maps[int(tok) - 1])
        else:
            print(f'  ⚠ did not understand “{tok}” — skipping')
    chosen = sorted(set(chosen))
    if not chosen:
        # input was given but nothing recognized — do not launch “all” by mistake
        print('  ⚠ nothing recognized — cancelled (Enter with no input = all).')
        return 'CANCEL'
    print(f'  selected: {len(chosen)} — {" ".join(chosen[:12])}' +
          (' …' if len(chosen) > 12 else ''))
    return chosen


def interactive():
    print(cyan(BANNER))
    last_dir = None  # last used path — hint for the next prompts
    while True:
      try:
        print(f'''
  {bold('1')}  Converter PTS → L2J / Конвертер PTS → L2J (XX_YY_conv.dat → XX_YY.l2j)
  {bold('2')}  Browser 2D/3D viewer / Веб-просмотрщик геодаты и мешей
  {bold('3')}  Compare two packs / Сравнение двух паков геодаты
  {bold('4')}  Check a pack / Валидация и поиск заглушек
  {bold('5')}  Verify PTS ↔ L2J / Поячеечная сверка PTS ↔ L2J
  {bold('6')}  Reverse converter L2J → PTS / Обратный конвертер L2J → PTS
  {bold('7')}  Generate from client / Генерация геодаты из клиента L2
  {bold('8')}  Compile pathnode.bin/.idx / Сборка нод путей pathnode (64-bit)
  {bold('9')}  Lucera 2: Decrypt .l2g → .l2j / Расшифровать геодату Lucera 2
  {bold('10')} Lucera 2: Encrypt .l2j → .l2g / Зашифровать геодату для Lucera 2
  {bold('11')} Diagnostics & Repair / Проверка и исправление геодаты
  {bold('0')}  Exit / Выход
''')
        ch = input('  choice / выбор: ').strip()
        if ch == '1':
            d = ask('Source (folder with *_conv.dat or a file)', last_dir)
            if not d:
                continue
            last_dir = d
            out = ask('Where to write .l2j', os.path.join(os.path.dirname(d) or '.', 'l2j'))
            cmd_convert([d], out)
        elif ch == '2':
            d = ask('Geodata folder', last_dir)
            if d:
                last_dir = d
                cmd_view(d)
        elif ch == '3':
            a = ask('Folder A', last_dir)
            b = ask('Folder B')
            if a and b:
                last_dir = a
                r = ask('Region for a detailed breakdown (Enter — summary report)', None)
                cmd_diff(a, b, r)
        elif ch == '4':
            d = ask('Folder or file', last_dir)
            if d:
                last_dir = d
                cmd_check([d])
        elif ch == '5':
            a = ask('First folder (PTS or L2J — order does not matter)', last_dir)
            b = ask('Second folder')
            if a and b:
                last_dir = a
                cmd_verify(a, b)
        elif ch == '6':
            src = ask('.l2j file or folder', last_dir)
            out = ask('Where to write *_conv.dat', (src or '.') + '_pts')
            if src:
                last_dir = src
                proto = ask_protocol()
                cmd_l2j2pts([src], out, protocol=proto)
        elif ch == '7':
            c = ask('L2 client folder (with Maps/Textures/StaticMeshes)', last_dir)
            if not c:
                continue
            last_dir = c
            fmt = ask('Output format (l2j or pts)', 'l2j')
            if (fmt or '').lower() not in ('l2j', 'pts'):
                fmt = 'l2j'
            else:
                fmt = fmt.lower()
            proto = 'gd'
            if fmt == 'pts':
                proto = ask_protocol()
            default_out = os.path.join(c, 'generated_pts' if fmt == 'pts' else 'generated_l2j')
            out = ask('Where to write ' + ('*_conv.dat' if fmt == 'pts' else '.l2j'), default_out)
            regions = _pick_regions(c)
            if regions == 'CANCEL':
                print('  cancelled.')
                continue
            _ensure_taichi()
            found = find_doordata(c)
            if found:
                doors = ask('doordata.txt', found)
            else:
                doors = ask('doordata.txt (Enter — skip; gate cells stay walled)', None)
            jobs_raw = ask('Workers (Enter = auto, keep 2 GB RAM free, ≤80% CPU)', 'auto')
            jobs_n = None
            if jobs_raw and str(jobs_raw).strip().lower() not in ('auto',):
                try:
                    jobs_n = int(jobs_raw)
                except ValueError:
                    print('  invalid worker count — using auto')
                    jobs_n = None
            cmd_generate(c, out, regions, out_fmt=fmt, protocol=proto,
                         doordata=doors, jobs=jobs_n)
        elif ch == '8':
            d = ask('PTS geodata folder (*_conv.dat)', last_dir)
            if not d:
                continue
            last_dir = d
            out = ask('Where to write pathnode.bin/.idx', d)
            txt_raw = ask('Also write pathnode.txt debug dump (large) (y/N)', 'n')
            write_txt = str(txt_raw or 'n').strip().lower() in ('y', 'yes')
            regs_raw = ask('Regions (Enter = all in folder / geo_index.txt)', None)
            regs = regs_raw.split() if regs_raw else None
            jobs_raw = ask('Link workers (Enter = auto, keep 2 GB RAM free, ≤80% CPU)', 'auto')
            jobs_n = None
            if jobs_raw and str(jobs_raw).strip().lower() not in ('auto',):
                try:
                    jobs_n = int(jobs_raw)
                except ValueError:
                    print('  invalid worker count — using auto')
                    jobs_n = None
            cmd_pathnode(d, out, write_txt, regs, jobs=jobs_n)
        elif ch == '9':
            src = ask('Lucera 2 .l2g file or folder', last_dir)
            if not src:
                continue
            last_dir = src
            out = ask('Where to write .l2j', (src if os.path.isdir(src) else os.path.dirname(src) or '.') + '_l2j')
            cmd_l2g2l2j([src], out)
        elif ch == '10':
            src = ask('.l2j file or folder', last_dir)
            if not src:
                continue
            last_dir = src
            out = ask('Where to write .l2g', (src if os.path.isdir(src) else os.path.dirname(src) or '.') + '_l2g')
            cmd_l2j2l2g([src], out)
        elif ch == '11':
            d = ask('Geodata file or folder (.l2g, .l2j, or _conv.dat)', last_dir)
            if not d:
                continue
            last_dir = d
            fix_ans = ask('Auto-repair and save fixed geodata? (y/N)', 'n')
            fix_dir = None
            if fix_ans.strip().lower() in ('y', 'yes'):
                fix_dir = ask('Output directory for repaired files', (d if os.path.isdir(d) else os.path.dirname(d) or '.') + '_fixed')
            cmd_diagnose([d], json_mode=False, fix_dir=fix_dir)
        elif ch == '0' or ch == '':
            return 0
      except EOFError:
        return 0
      except ValueError as e:
        print(f'  invalid input: {e}')


def main():
    # Machine-readable front ends: no banner, JSON only.
    if len(sys.argv) > 1 and sys.argv[1] in ('llm', 'mcp'):
        from geolib import jsontools
        return jsontools.cli_main(sys.argv[2:]) if sys.argv[1] == 'llm' else jsontools.mcp_main()
    ap = argparse.ArgumentParser(description='L2 Geodata Toolkit',
                                 epilog='JSON mode: `geotool.py llm list`; '
                                        'MCP server over stdio: `geotool.py mcp`.')
    sub = ap.add_subparsers(dest='cmd')
    p = sub.add_parser('convert'); p.add_argument('src', nargs='+'); p.add_argument('-o', '--out', required=True); p.add_argument('-y', '--yes', action='store_true')
    p = sub.add_parser('view'); p.add_argument('dir'); p.add_argument('--port', type=int, default=8777)
    p.add_argument('--spawns', help='JSON catalog of failed NPC spawns (pins on 2D/3D)')
    p.add_argument('--client', help='L2 client folder (Maps/StaticMeshes) for UNR mesh overlay')
    p = sub.add_parser('diff'); p.add_argument('dir_a'); p.add_argument('dir_b'); p.add_argument('--region')
    p = sub.add_parser('generate')
    p.add_argument('client')
    p.add_argument('-o', '--out', required=True)
    p.add_argument('--region', nargs='*')
    p.add_argument('--terrain-only', action='store_true')
    p.add_argument('--max-step', type=int, default=16)
    p.add_argument('-j', '--jobs', type=int,
                   help='Worker count. Omit for auto: add workers while >=2 GB RAM is free '
                        'and CPU headroom remains, drop one if free RAM falls below that')
    p.add_argument('--min-free-ram', type=float, default=MIN_FREE_RAM_GB,
                   help=f'GB of free RAM to keep when -j is omitted (default {MIN_FREE_RAM_GB:g})')
    p.add_argument('--max-cpu', type=cpu_pct_arg, default=MAX_CPU_PCT, metavar='PCT',
                   help=f'Cap generate CPU at this percent (1-100). Auto workers also '
                        f'stop at this share of CPU threads (default {MAX_CPU_PCT:g})')
    p.add_argument('--format', choices=('l2j', 'pts'), default='l2j',
                   help='l2j (default) or pts (*_conv.dat, no intermediate .l2j)')
    p.add_argument('--protocol', type=protocol_arg, default='gd',
                   help=PROTO_CLI_HELP + '. Ignored for --format l2j')
    p.add_argument('--doordata', help='doordata.txt (also L2_DOORDATA or <client>/Script/doordata.txt)')
    p = sub.add_parser('check'); p.add_argument('paths', nargs='+')
    p = sub.add_parser('spawncheck')
    p.add_argument('geodata', help='folder with *_conv.dat')
    p.add_argument('--npcpos', required=True, help='npcpos.txt (not modified)')
    p.add_argument('-o', '--out', help='JSON catalog of failures (viewer --spawns)')
    p = sub.add_parser('pathnode')
    p.add_argument('geodata', help='folder with *_conv.dat (and optional geo_index.txt)')
    p.add_argument('-o', '--out', help='output folder (default: the geodata folder)')
    p.add_argument('--txt', action='store_true', help='also write pathnode.txt (debug, large)')
    p.add_argument('--region', nargs='*', help='only these XX_YY maps (still emits the 10–29 × 10–26 zone grid)')
    p.add_argument('-j', '--jobs', type=int,
                   help='Link workers. Omit for auto: 80% of CPU threads, keep 2 GB RAM free')
    p.add_argument('--min-free-ram', type=float, default=MIN_FREE_RAM_GB,
                   help=f'GB of free RAM to keep when -j is omitted (default {MIN_FREE_RAM_GB:g})')
    p.add_argument('--max-cpu', type=cpu_pct_arg, default=MAX_CPU_PCT, metavar='PCT',
                   help=f'Cap pathnode CPU at this percent (1-100). Auto workers also '
                        f'stop at this share of CPU threads (default {MAX_CPU_PCT:g})')
    p = sub.add_parser('verify'); p.add_argument('pts_dir'); p.add_argument('l2j_dir')
    p = sub.add_parser('l2j2pts'); p.add_argument('src', nargs='+'); p.add_argument('-o', '--out', required=True); p.add_argument('-y', '--yes', action='store_true')
    p.add_argument('--protocol', type=protocol_arg, default='gd',
                   help=PROTO_CLI_HELP)
    p = sub.add_parser('l2g2l2j'); p.add_argument('src', nargs='+'); p.add_argument('-o', '--out', required=True); p.add_argument('-y', '--yes', action='store_true')
    p = sub.add_parser('l2j2l2g'); p.add_argument('src', nargs='+'); p.add_argument('-o', '--out', required=True); p.add_argument('-y', '--yes', action='store_true')
    p = sub.add_parser('l2g2pts'); p.add_argument('src', nargs='+'); p.add_argument('-o', '--out', required=True); p.add_argument('-y', '--yes', action='store_true')
    p.add_argument('--protocol', type=protocol_arg, default='gd', help=PROTO_CLI_HELP)
    p = sub.add_parser('pts2l2g'); p.add_argument('src', nargs='+'); p.add_argument('-o', '--out', required=True); p.add_argument('-y', '--yes', action='store_true')
    p = sub.add_parser('diagnose'); p.add_argument('paths', nargs='+')
    p.add_argument('-o', '--out', help='output directory for auto-repaired geodata')
    p.add_argument('--fix', action='store_true', help='auto-repair detected anomalies')
    p.add_argument('--json', action='store_true', help='output report in JSON format')
    p.add_argument('--cliff-threshold', type=int, default=48, help='Z drop limit for fatal cliffs')
    sub.add_parser('gui', help='Launch Graphical User Interface')
    ap.add_argument('--cli', action='store_true', help='Force interactive CLI text menu instead of GUI')
    args = ap.parse_args()
    if not args.cmd:
        if args.cli or '--cli' in sys.argv:
            return interactive()
        try:
            import gui
            return gui.main()
        except Exception:
            return interactive()
    if args.cmd == 'gui':
        try:
            import gui
            return gui.main()
        except Exception as e:
            print(f"Error launching GUI: {e}")
            return interactive()
    print(cyan(BANNER))
    if args.cmd == 'convert':
        return cmd_convert([os.path.expanduser(s) for s in args.src], os.path.expanduser(args.out), args.yes)
    x = os.path.expanduser
    if args.cmd == 'view':
        return cmd_view(x(args.dir), args.port, x(args.spawns) if args.spawns else None,
                        x(args.client) if args.client else None)
    if args.cmd == 'diff':
        return cmd_diff(x(args.dir_a), x(args.dir_b), args.region)
    if args.cmd == 'generate':
        _ensure_taichi(interactive_ok=False)
        return cmd_generate(x(args.client), x(args.out), args.region,
                            args.max_step, args.terrain_only, args.jobs,
                            args.format, args.protocol,
                            x(args.doordata) if args.doordata else None,
                            args.min_free_ram, args.max_cpu)
    if args.cmd == 'check':
        return cmd_check([x(pp) for pp in args.paths])
    if args.cmd == 'spawncheck':
        return cmd_spawncheck(x(args.geodata), x(args.npcpos),
                              x(args.out) if args.out else None)
    if args.cmd == 'pathnode':
        return cmd_pathnode(x(args.geodata),
                            x(args.out) if args.out else None,
                            args.txt, args.region, args.jobs,
                            args.min_free_ram, args.max_cpu)
    if args.cmd == 'verify':
        return cmd_verify(x(args.pts_dir), x(args.l2j_dir))
    if args.cmd == 'l2j2pts':
        return cmd_l2j2pts([x(s) for s in args.src], x(args.out), args.yes,
                           args.protocol)
    if args.cmd == 'l2g2l2j':
        return cmd_l2g2l2j([x(s) for s in args.src], x(args.out), args.yes)
    if args.cmd == 'l2j2l2g':
        return cmd_l2j2l2g([x(s) for s in args.src], x(args.out), args.yes)
    if args.cmd == 'l2g2pts':
        return cmd_l2g2pts([x(s) for s in args.src], x(args.out), args.yes, args.protocol)
    if args.cmd == 'pts2l2g':
        return cmd_pts2l2g([x(s) for s in args.src], x(args.out), args.yes)
    if args.cmd == 'diagnose':
        fix_dir = x(args.out) if args.out else None
        if args.fix and not fix_dir:
            fix_dir = 'repaired_geodata'
        return cmd_diagnose([x(pp) for pp in args.paths], json_mode=args.json, fix_dir=fix_dir, cliff_th=args.cliff_threshold)


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print(dim('\n  interrupted.'))
        sys.exit(130)
