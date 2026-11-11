"""Configuration helpers for the local WorkPilot runtime."""

from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "WorkPilot"


def data_directory() -> Path:
    """Return a per-user data directory without touching browser profiles."""
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def database_path() -> Path:
    return data_directory() / "workpilot.sqlite3"
