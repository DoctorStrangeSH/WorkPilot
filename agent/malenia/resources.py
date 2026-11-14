"""Small, dependency-free resource monitoring for the Malenia MVP."""

from __future__ import annotations

import ctypes
import os
import time
from dataclasses import asdict, dataclass


GIB = 1024 ** 3


@dataclass(frozen=True)
class ResourceSnapshot:
    total_memory_bytes: int
    available_memory_bytes: int
    used_memory_percent: float
    logical_processors: int
    cpu_usage_percent: float
    mode: str
    recommended_parallel_jobs: int

    def to_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


def classify_memory(total_bytes: int, available_bytes: int) -> tuple[str, int]:
    """Choose a conservative mode from available physical memory."""
    if total_bytes <= 0:
        return "economy", 1

    available = max(0, min(available_bytes, total_bytes))
    available_ratio = available / total_bytes

    if available < 2 * GIB or available_ratio < 0.12:
        return "emergency", 1
    if available < 4 * GIB or available_ratio < 0.25:
        return "economy", 1
    return "normal", 2


def _windows_memory() -> tuple[int, int]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError("GlobalMemoryStatusEx failed")
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _posix_memory() -> tuple[int, int]:
    page_size = os.sysconf("SC_PAGE_SIZE")
    total_pages = os.sysconf("SC_PHYS_PAGES")
    available_pages = os.sysconf("SC_AVPHYS_PAGES")
    return int(page_size * total_pages), int(page_size * available_pages)


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", ctypes.c_ulong),
        ("dwHighDateTime", ctypes.c_ulong),
    ]


def _windows_cpu_times() -> tuple[int, int]:
    idle = _FILETIME()
    kernel = _FILETIME()
    user = _FILETIME()
    if not ctypes.windll.kernel32.GetSystemTimes(
        ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
    ):
        raise OSError("GetSystemTimes failed")

    def value(item: _FILETIME) -> int:
        return (item.dwHighDateTime << 32) | item.dwLowDateTime

    return value(idle), value(kernel) + value(user)


def _cpu_usage_percent() -> float:
    """Sample system-wide CPU utilization; Windows is the primary target."""
    if os.name != "nt":
        return 0.0
    try:
        idle_before, total_before = _windows_cpu_times()
        time.sleep(0.12)
        idle_after, total_after = _windows_cpu_times()
    except (AttributeError, OSError):
        return 0.0

    idle_delta = max(0, idle_after - idle_before)
    total_delta = max(0, total_after - total_before)
    if total_delta == 0:
        return 0.0
    return round(max(0.0, min(100.0, (1 - idle_delta / total_delta) * 100)), 1)


class ResourceManager:
    """Read-only resource monitor; it never terminates user applications."""

    def snapshot(self) -> ResourceSnapshot:
        try:
            total, available = _windows_memory() if os.name == "nt" else _posix_memory()
        except (AttributeError, OSError, ValueError):
            total, available = 0, 0

        mode, jobs = classify_memory(total, available)
        used_percent = (
            round(((total - available) / total) * 100, 1) if total > 0 else 0.0
        )
        return ResourceSnapshot(
            total_memory_bytes=total,
            available_memory_bytes=available,
            used_memory_percent=used_percent,
            logical_processors=os.cpu_count() or 1,
            cpu_usage_percent=_cpu_usage_percent(),
            mode=mode,
            recommended_parallel_jobs=jobs,
        )
