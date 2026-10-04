#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI styling: colors, banner, progress bar."""

import os
import re
import sys

# Windows: enable ANSI processing in conhost (no-op on Win10+ Terminal
# and other OSes) and do not crash on characters outside the console
# encoding (cp1251/cp866).
if sys.platform == 'win32':
    os.system('')
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors='replace')
    except (AttributeError, ValueError):
        pass


def _is_console():
    """True if stdout is a real console (isatty can be False in some
    PowerShell -File / python -u launches on Windows)."""
    try:
        if sys.stdout.isatty():
            return True
    except Exception:
        pass
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        h = ctypes.windll.kernel32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        mode = ctypes.c_ulong()
        if not ctypes.windll.kernel32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        ctypes.windll.kernel32.SetConsoleMode(h, mode.value | 0x0004)  # VT
        return True
    except Exception:
        return False


USE_COLOR = _is_console() and os.environ.get('NO_COLOR') is None


def c(code, t):
    return f'\033[{code}m{t}\033[0m' if USE_COLOR else str(t)


def bold(t):   return c('1', t)
def dim(t):    return c('2', t)
def red(t):    return c('31', t)
def green(t):  return c('32', t)
def yellow(t): return c('33', t)
def cyan(t):   return c('36', t)


BANNER = '''
    ██████╗ ███████╗ ██████╗ ████████╗ ██████╗  ██████╗ ██╗     
   ██╔════╝ ██╔════╝██╔═══██╗╚══██╔══╝██╔═══██╗██╔═══██╗██║     
   ██║  ███╗█████╗  ██║   ██║   ██║   ██║   ██║██║   ██║██║     
   ██║   ██║██╔══╝  ██║   ██║   ██║   ██║   ██║██║   ██║██║     
   ╚██████╔╝███████╗╚██████╔╝   ██║   ╚██████╔╝╚██████╔╝███████╗
    ╚═════╝ ╚══════╝ ╚═════╝    ╚═╝    ╚═════╝  ╚═════╝ ╚══════╝

                         L2 Geodata Toolkit                     
       convert · view · compare · check · verify · pathnode     

'''


_ANSI = re.compile(r'\033\[[0-9;]*m')


def vlen(s):
    """Visible string length — excluding ANSI color codes."""
    return len(_ANSI.sub('', s))


def vtrunc(s, width):
    """Truncate to `width` VISIBLE characters without splitting ANSI
    sequences (escape codes are copied for free and do not count toward width)."""
    out, vis, i, n = [], 0, 0, len(s)
    while i < n:
        m = _ANSI.match(s, i)
        if m:
            out.append(m.group())
            i = m.end()
            continue
        if vis >= width:
            break
        out.append(s[i])
        vis += 1
        i += 1
    return ''.join(out)


def term_width(default=100):
    try:
        return os.get_terminal_size().columns
    except OSError:                                   # not a tty (pipe/redirect)
        return default


def term_height(default=40):
    try:
        return os.get_terminal_size().lines
    except OSError:                                   # not a tty (pipe/redirect)
        return default


def status(text):
    """Redraw a single status line over the current one.

    Truncate to the real terminal width (ANSI is not counted and not split) and
    erase the tail of the previous frame via \\x1b[K — instead of padding the
    line with spaces, which is never enough after a long previous frame.
    Scales to any number of active lines: what does not fit is cut by width,
    not by a magic constant."""
    line = vtrunc(text, max(1, term_width() - 1))
    if USE_COLOR:
        sys.stdout.write('\r' + line + '\033[0m\033[K')  # color reset + erase-to-EOL
    else:
        sys.stdout.write('\r' + line + ' ' * 12)         # non-tty: old behavior
    sys.stdout.flush()


# Unified bar format for ALL sites (single and in a block): one bar width,
# one label column, one percent and (done/total) format. Change here — changes
# everywhere.
BAR_W = 28                                           # █░ strip width
LABEL_W = 13                                          # label column ('conversion', 'XX_YY_Classic')


def bar_line(label, done, total, tail=''):
    """One bar line in the unified format:

        <label>  ████████░░░░  44.5% (137/308)<tail>

    tail — optional tail (ETA/suffix), already with its own spacing.
    Label is always exactly LABEL_W visible characters (long ones truncated with …),
    fraction is clamped to [0,1] — the bar does not overflow when d>t."""
    frac = min(1.0, max(0.0, done / total)) if total else 1.0
    fill = int(BAR_W * frac)
    bar = '█' * fill + '░' * (BAR_W - fill)
    lbl = str(label).strip()
    lbl = lbl[:LABEL_W - 1] + '…' if len(lbl) > LABEL_W else lbl.ljust(LABEL_W)
    return f'  {lbl} {cyan(bar)} {frac:6.1%} ({done}/{total}){tail}'


class LiveBlock:
    """Live multi-line status block: header + an arbitrary number of lines.

    Each frame is redrawn IN PLACE: the cursor is raised by the height of the
    previous block and each line is rewritten with \\x1b[K. There can be as
    many lines as needed (one per worker) — we do not cut by count,
    unlike a “single line” everything had to be crammed into and truncated.

    Invariant: after render() the cursor is in column 0 immediately BELOW the block.
    An individual line is still trimmed to terminal width — otherwise wrapping
    would break the per-line count and the cursor would “drift”."""

    def __init__(self):
        self._prev = 0                               # height of the previous frame’s block

    def render(self, lines):
        if not USE_COLOR:                            # non-tty / no ANSI: one \r line
            text = '   '.join(_ANSI.sub('', ln).rstrip() for ln in lines if str(ln).strip())
            sys.stdout.write('\r' + vtrunc(text, max(1, term_width() - 1)) + ' ' * 8)
            sys.stdout.flush()
            return
        w = max(1, term_width() - 1)
        buf = []
        if self._prev:
            buf.append(f'\033[{self._prev}A')        # up to the first line of the block
        buf.append('\r')
        for ln in lines:
            # \033[0m at the end: if vtrunc cut the line inside a cyan bar,
            # its closing reset would be lost and the color would “bleed” onward.
            buf.append('\033[K' + vtrunc(ln, w) + '\033[0m\n')  # erase line, write, down
        extra = self._prev - len(lines)
        for _ in range(extra):                       # block shrank — blank the remainder
            buf.append('\033[K\n')
        if extra > 0:
            buf.append(f'\033[{extra}A')             # return exactly under the block
        self._prev = len(lines)
        sys.stdout.write(''.join(buf))
        sys.stdout.flush()

    def stop(self):
        """Cursor is already under the block — just forget its height."""
        self._prev = 0


def fmt_dur(sec):
    """Seconds → compact duration (2m 05s / 1h 12m)."""
    sec = int(max(0, sec))
    if sec < 60:
        return f'{sec}s'
    if sec < 3600:
        return f'{sec // 60}m {sec % 60:02d}s'
    return f'{sec // 3600}h {(sec % 3600) // 60:02d}m'


def progress(done, total, prefix='', suffix=''):
    """Progress bar with automatic remaining-time estimate (ETA).

    Start time is recorded on the first tick (keyed by prefix); ETA =
    average-per-unit × remainder. suffix, if set, replaces ETA."""
    import time
    key = prefix or '_'
    starts = progress._starts
    if done <= 1:                                # start of a cycle — new countdown
        starts[key] = time.monotonic()
    elif key not in starts:
        starts[key] = time.monotonic()
    if suffix:
        tail = '  ' + suffix
    elif 1 <= done < total:
        elapsed = time.monotonic() - starts[key]
        tail = '  ~' + fmt_dur(elapsed / done * (total - done)) if elapsed > 0.3 else ''
    else:
        tail = ''
    status(bar_line(prefix, done, total, tail))
    if done == total:
        starts.pop(key, None)
        sys.stdout.write('\n')


progress._starts = {}
