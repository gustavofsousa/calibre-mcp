"""Startup configuration & validation (CFG-01, SAFE-05).

Resolve and validate the Calibre library path once at startup, and resolve the
backup root. Fail fast with a ConfigError that names the offending path so the
host can surface an actionable message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

LIBRARY_PATH_ENV = "CALIBRE_LIBRARY_PATH"
BACKUP_DIR_ENV = "CALIBRE_MCP_BACKUP_DIR"
BACKUP_DIR_NAME = ".calibre-mcp-backups"


@dataclass(frozen=True)
class Config:
    """Validated startup configuration."""

    library_path: Path
    db_path: Path
    backup_root: Path


def load_config() -> Config:
    """Read and validate configuration from the environment.

    Raises ConfigError when CALIBRE_LIBRARY_PATH is unset or points at a
    directory with no metadata.db (CFG-01). The backup root defaults to
    <library>/.calibre-mcp-backups/ and is overridable via
    CALIBRE_MCP_BACKUP_DIR (SAFE-05).
    """
    raw_library_path = os.environ.get(LIBRARY_PATH_ENV)
    if not raw_library_path:
        raise ConfigError(
            f"{LIBRARY_PATH_ENV} is unset; set it to your Calibre library directory"
        )

    library_path = Path(raw_library_path)
    db_path = library_path / "metadata.db"
    if not db_path.is_file():
        raise ConfigError(
            f"no Calibre library found at {library_path}: "
            f"missing metadata.db ({db_path})"
        )

    raw_backup_dir = os.environ.get(BACKUP_DIR_ENV)
    backup_root = (
        Path(raw_backup_dir) if raw_backup_dir else library_path / BACKUP_DIR_NAME
    )

    return Config(
        library_path=library_path,
        db_path=db_path,
        backup_root=backup_root,
    )
