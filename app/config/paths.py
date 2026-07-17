"""
Platform paths for Ghost Downloader 3 CLI.

Replaces the original Qt-based paths with pure-Python equivalents.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _data_dir() -> Path:
    """Return the application data directory.

    Priority:
    1. ``$GHOST_DOWNLOADER_DATA`` environment variable
    2. ``~/.local/share/GhostDownloader`` (Linux/macOS)
    3. ``%APPDATA%/GhostDownloader`` (Windows)
    """
    env = os.environ.get("GHOST_DOWNLOADER_DATA")
    if env:
        return Path(env)

    if sys.platform == "win32":
        base = os.environ.get("APPDATA", os.path.expanduser("~"))
        return Path(base) / "GhostDownloader"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "GhostDownloader"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local" / "share"
        return base / "GhostDownloader"


# Resolve on import so it's available as a module-level constant
executableDir = Path(".")

APP_DATA_DIR = str(_data_dir())

PORTABLE_PATH = executableDir / "GhostDownloader"
USER_PATH = _data_dir()


def isPortable() -> bool:
    return APP_DATA_DIR == str(PORTABLE_PATH)


def migrate(target: Path) -> None:
    """Migrate config from the old location to *target*."""
    from loguru import logger
    logger.remove()
    source = Path(APP_DATA_DIR)
    target.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copytree(source, target, dirs_exist_ok=True)
    if isPortable():
        source.rename(source.with_suffix(".bak"))
