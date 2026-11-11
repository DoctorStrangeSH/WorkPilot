"""Small, dependency-free resource monitoring for the WorkPilot MVP."""

from __future__ import annotations

import ctypes
import os
from dataclasses import asdict, dataclass


GIB = 1024 ** 3


@dataclass(frozen=True)
class ResourceSnapshot:
    total_memory_bytes: int
    available_memory_bytes: int
    used_memory_percent: float
    logical_processors: int
    mode: str
    recommended_parallel_jobs: int

    def to_dict(self) -> dict[str, int | float | str]:
        return asdict(self)


def classify_memory(total_bytes: int, available_bytes: int) -> tuple[str, int]:
    """Choose a conservative mode from available physical memory.

    These thresholds are initial safety defaults, not measured performance
    claims. They can be tuned after profiling on the target computer.
    """
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
            mode=mode,
            recommended_parallel_jobs=jobs,
        )
