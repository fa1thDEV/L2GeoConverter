#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Host resource management for `generate`: RAM probing, worker auto-scaling
and the process-tree CPU cap (Windows job object / POSIX affinity)."""

import os
import sys


WORKER_RAM_GB = 2.5    # peak-memory estimate per worker on a city region
MIN_FREE_RAM_GB = 2.0  # auto-scale: keep at least this much physical RAM free
MAX_CPU_PCT = 80.0     # auto workers + process-tree CPU cap (Taichi cannot fill the rest)

_CPU_CAP_APPLIED = None  # pct already applied in this process (interactive re-entry)
_CPU_CAP_JOB = None      # Windows job handle; must stay alive or the cap is released


def _windows_mem():
    """(total_gb, avail_gb) from GlobalMemoryStatusEx, or None."""
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [('dwLength', ctypes.c_ulong),
                        ('dwMemoryLoad', ctypes.c_ulong),
                        ('ullTotalPhys', ctypes.c_ulonglong),
                        ('ullAvailPhys', ctypes.c_ulonglong),
                        ('ullTotalPageFile', ctypes.c_ulonglong),
                        ('ullAvailPageFile', ctypes.c_ulonglong),
                        ('ullTotalVirtual', ctypes.c_ulonglong),
                        ('ullAvailVirtual', ctypes.c_ulonglong),
                        ('ullAvailExtendedVirtual', ctypes.c_ulonglong)]
        ms = MS()
        ms.dwLength = ctypes.sizeof(MS)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return ms.ullTotalPhys / 1e9, ms.ullAvailPhys / 1e9
    except Exception:
        return None


def _total_ram_gb():
    """Total RAM (GB), cross-platform, no dependencies. None if unknown."""
    try:
        return os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE') / 1e9
    except (ValueError, AttributeError, OSError):
        pass
    win = _windows_mem()
    return win[0] if win else None


def _avail_ram_gb():
    """Currently free physical RAM (GB). None if unknown."""
    try:
        kb = None
        with open('/proc/meminfo', encoding='ascii') as f:
            for line in f:
                if line.startswith('MemAvailable:') or (
                        kb is None and line.startswith('MemFree:')):
                    kb = int(line.split()[1])
                    if line.startswith('MemAvailable:'):
                        break
        if kb is not None:
            return kb / 1e6
    except Exception:
        pass
    win = _windows_mem()
    return win[1] if win else None


def _auto_jobs():
    """Static fallback: half the cores, half the RAM / WORKER_RAM_GB."""
    cores = os.cpu_count() or 4
    half_cores = max(1, cores // 2)
    total = _total_ram_gb()
    if total:
        mem_jobs = max(1, int(total * 0.5 / WORKER_RAM_GB))
        return min(half_cores, mem_jobs)
    return half_cores


def cpu_worker_cap(pct=None, n_cpu=None):
    """Max auto workers so generate leaves CPU headroom (at least one)."""
    if pct is None:
        pct = MAX_CPU_PCT
    pct = max(1.0, min(100.0, float(pct)))
    n = n_cpu if n_cpu is not None else (os.cpu_count() or 4)
    n = max(1, int(n))
    return max(1, min(n, int(n * pct / 100.0)))


def _cpu_rate_units(pct):
    """Windows Job Object CpuRate: hundredths of a percent (1..10000)."""
    return max(1, min(10000, int(round(float(pct) * 100))))


def _windows_job_cpu_cap(pct):
    """Hard-cap this process tree at pct% CPU. Handle stored in _CPU_CAP_JOB."""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32
    JOB_OBJECT_CPU_RATE_CONTROL_ENABLE = 0x1
    JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP = 0x4
    JobObjectCpuRateControlInformation = 15

    class JOBOBJECT_CPU_RATE_CONTROL_INFORMATION(ctypes.Structure):
        _fields_ = [('ControlFlags', wintypes.DWORD),
                    ('CpuRate', wintypes.DWORD)]

    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    k32.CreateJobObjectW.restype = ctypes.c_void_p
    k32.SetInformationJobObject.argtypes = [
        ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    job = k32.CreateJobObjectW(None, None)
    if not job:
        return False
    info = JOBOBJECT_CPU_RATE_CONTROL_INFORMATION()
    info.ControlFlags = (JOB_OBJECT_CPU_RATE_CONTROL_ENABLE
                         | JOB_OBJECT_CPU_RATE_CONTROL_HARD_CAP)
    info.CpuRate = _cpu_rate_units(pct)
    if not k32.SetInformationJobObject(
            job, JobObjectCpuRateControlInformation,
            ctypes.byref(info), ctypes.sizeof(info)):
        k32.CloseHandle(job)
        return False
    if not k32.AssignProcessToJobObject(job, k32.GetCurrentProcess()):
        k32.CloseHandle(job)
        return False
    global _CPU_CAP_JOB
    _CPU_CAP_JOB = job
    return True


def _affinity_cpu_cap(pct):
    """Restrict this process (and children) to pct% of its allowed CPUs."""
    n = os.cpu_count() or 1
    keep = cpu_worker_cap(pct, n_cpu=n)
    if keep >= n:
        return True
    if sys.platform == 'win32':
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.GetProcessAffinityMask.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t),
            ctypes.POINTER(ctypes.c_size_t)]
        k32.GetProcessAffinityMask.restype = ctypes.c_int
        k32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        k32.SetProcessAffinityMask.restype = ctypes.c_int
        proc = k32.GetCurrentProcess()
        process_mask = ctypes.c_size_t()
        system_mask = ctypes.c_size_t()
        if not k32.GetProcessAffinityMask(
                proc, ctypes.byref(process_mask), ctypes.byref(system_mask)):
            return False
        allowed = process_mask.value
        new_mask = 0
        bit = 1
        taken = 0
        while allowed and taken < keep:
            if allowed & bit:
                new_mask |= bit
                taken += 1
                allowed &= ~bit
            bit <<= 1
        if taken < 1 or new_mask == 0:
            return False
        return bool(k32.SetProcessAffinityMask(proc, new_mask))
    try:
        current = os.sched_getaffinity(0)
        chosen = set(sorted(current)[:keep])
        if not chosen:
            return False
        os.sched_setaffinity(0, chosen)
        return True
    except (AttributeError, OSError):
        return False


def apply_cpu_cap(pct=MAX_CPU_PCT):
    """Cap generate + workers at pct% CPU. Idempotent. True if an OS cap stuck."""
    global _CPU_CAP_APPLIED
    pct = max(1.0, min(100.0, float(pct)))
    if pct >= 100:
        return False
    if _CPU_CAP_APPLIED is not None:
        return True
    ok = False
    if sys.platform == 'win32':
        try:
            ok = _windows_job_cpu_cap(pct)
        except Exception:
            ok = False
    if not ok:
        try:
            ok = _affinity_cpu_cap(pct)
        except Exception:
            ok = False
    if ok:
        _CPU_CAP_APPLIED = pct
    return ok


def want_worker_delta(n_active, pending, avail_gb, min_free=MIN_FREE_RAM_GB,
                      max_n=None):
    """+1 start another, -1 stop the newest, 0 hold.

    Always keep at least one worker while work remains. Scale up while
    free RAM ≥ min_free; scale down while free RAM < min_free.
    """
    max_n = max_n or cpu_worker_cap()
    if n_active < 1 and pending:
        return 1
    if avail_gb is None:
        cap = min(max_n, _auto_jobs())
        if pending and n_active < cap:
            return 1
        return 0
    if avail_gb < min_free and n_active > 1:
        return -1
    if pending and n_active < max_n and avail_gb >= min_free:
        return 1
    return 0
