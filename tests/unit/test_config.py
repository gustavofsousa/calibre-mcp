"""Unit tests for load_config — derived from spec CFG-01 and SAFE-05.

CFG-01 (spec §Search & browse AC4): unset CALIBRE_LIBRARY_PATH, or a dir with no
metadata.db, SHALL fail with a clear error naming the missing path.
SAFE-05 (spec §Data-safety net AC5): backup root defaults to
<library>/.calibre-mcp-backups/ and is overridable via CALIBRE_MCP_BACKUP_DIR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibre_mcp.config import load_config
from calibre_mcp.errors import ConfigError


def _make_library(tmp_path: Path) -> Path:
    """Create a dir containing an (empty) metadata.db, like a real library."""
    library = tmp_path / "library"
    library.mkdir()
    (library / "metadata.db").write_bytes(b"")
    return library


@pytest.mark.unit
def test_valid_path_resolves_library_and_db(tmp_path, monkeypatch):
    library = _make_library(tmp_path)
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library))
    monkeypatch.delenv("CALIBRE_MCP_BACKUP_DIR", raising=False)

    config = load_config()

    assert config.library_path == library
    assert config.db_path == library / "metadata.db"


@pytest.mark.unit
def test_unset_env_raises_config_error_naming_the_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("CALIBRE_LIBRARY_PATH", raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_config()

    assert "CALIBRE_LIBRARY_PATH" in str(excinfo.value)


@pytest.mark.unit
def test_dir_without_metadata_db_raises_config_error_naming_the_path(
    tmp_path, monkeypatch
):
    library = tmp_path / "library"
    library.mkdir()  # no metadata.db inside
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library))

    with pytest.raises(ConfigError) as excinfo:
        load_config()

    assert str(library) in str(excinfo.value)


@pytest.mark.unit
def test_backup_root_defaults_to_library_subdir(tmp_path, monkeypatch):
    library = _make_library(tmp_path)
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library))
    monkeypatch.delenv("CALIBRE_MCP_BACKUP_DIR", raising=False)

    config = load_config()

    assert config.backup_root == library / ".calibre-mcp-backups"


@pytest.mark.unit
def test_custom_backup_dir_overrides_default(tmp_path, monkeypatch):
    library = _make_library(tmp_path)
    custom_backup = tmp_path / "elsewhere" / "backups"
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library))
    monkeypatch.setenv("CALIBRE_MCP_BACKUP_DIR", str(custom_backup))

    config = load_config()

    assert config.backup_root == custom_backup
