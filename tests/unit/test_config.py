"""Unit tests for load_config — derived from spec CFG-01 and SAFE-05.

CFG-01 (spec §Search & browse AC4): unset CALIBRE_LIBRARY_PATH, or a dir with no
metadata.db, SHALL fail with a clear error naming the missing path.
SAFE-05 (spec §Data-safety net AC5): backup root defaults to
<library>/.calibre-mcp-backups/ and is overridable via CALIBRE_MCP_BACKUP_DIR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibre_mcp.config import load_config, load_smtp_config
from calibre_mcp.errors import ConfigError, SmtpNotConfiguredError


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


def _set_full_smtp_env(monkeypatch) -> None:
    monkeypatch.setenv("CALIBRE_MCP_SMTP_RELAY", "smtp.example.com")
    monkeypatch.setenv("CALIBRE_MCP_SMTP_PORT", "2525")
    monkeypatch.setenv("CALIBRE_MCP_SMTP_USERNAME", "alice")
    monkeypatch.setenv("CALIBRE_MCP_SMTP_PASSWORD", "s3cr3t")
    monkeypatch.setenv("CALIBRE_MCP_SMTP_ENCRYPTION", "SSL")
    monkeypatch.setenv("CALIBRE_MCP_SMTP_FROM", "alice@example.com")


@pytest.mark.unit
def test_full_smtp_env_parses_into_config(monkeypatch):
    _set_full_smtp_env(monkeypatch)

    config = load_smtp_config()

    assert config.relay == "smtp.example.com"
    assert config.port == 2525
    assert config.username == "alice"
    assert config.password == "s3cr3t"
    assert config.encryption == "SSL"
    assert config.sender == "alice@example.com"


@pytest.mark.unit
def test_missing_relay_raises_smtp_not_configured_naming_the_var(monkeypatch):
    _set_full_smtp_env(monkeypatch)
    monkeypatch.delenv("CALIBRE_MCP_SMTP_RELAY", raising=False)

    with pytest.raises(SmtpNotConfiguredError) as excinfo:
        load_smtp_config()

    assert "CALIBRE_MCP_SMTP_RELAY" in str(excinfo.value)


@pytest.mark.unit
def test_missing_username_raises_smtp_not_configured_naming_the_var(monkeypatch):
    _set_full_smtp_env(monkeypatch)
    monkeypatch.delenv("CALIBRE_MCP_SMTP_USERNAME", raising=False)

    with pytest.raises(SmtpNotConfiguredError) as excinfo:
        load_smtp_config()

    assert "CALIBRE_MCP_SMTP_USERNAME" in str(excinfo.value)


@pytest.mark.unit
def test_missing_password_raises_smtp_not_configured_naming_the_var(monkeypatch):
    _set_full_smtp_env(monkeypatch)
    monkeypatch.delenv("CALIBRE_MCP_SMTP_PASSWORD", raising=False)

    with pytest.raises(SmtpNotConfiguredError) as excinfo:
        load_smtp_config()

    assert "CALIBRE_MCP_SMTP_PASSWORD" in str(excinfo.value)


@pytest.mark.unit
def test_missing_sender_raises_smtp_not_configured_naming_the_var(monkeypatch):
    _set_full_smtp_env(monkeypatch)
    monkeypatch.delenv("CALIBRE_MCP_SMTP_FROM", raising=False)

    with pytest.raises(SmtpNotConfiguredError) as excinfo:
        load_smtp_config()

    assert "CALIBRE_MCP_SMTP_FROM" in str(excinfo.value)


@pytest.mark.unit
def test_smtp_not_configured_is_a_config_error(monkeypatch):
    monkeypatch.delenv("CALIBRE_MCP_SMTP_RELAY", raising=False)

    with pytest.raises(ConfigError):
        load_smtp_config()


@pytest.mark.unit
def test_default_encryption_and_port_when_unset(monkeypatch):
    monkeypatch.setenv("CALIBRE_MCP_SMTP_RELAY", "smtp.example.com")
    monkeypatch.delenv("CALIBRE_MCP_SMTP_PORT", raising=False)
    monkeypatch.setenv("CALIBRE_MCP_SMTP_USERNAME", "alice")
    monkeypatch.setenv("CALIBRE_MCP_SMTP_PASSWORD", "s3cr3t")
    monkeypatch.delenv("CALIBRE_MCP_SMTP_ENCRYPTION", raising=False)
    monkeypatch.setenv("CALIBRE_MCP_SMTP_FROM", "alice@example.com")

    config = load_smtp_config()

    assert config.encryption == "TLS"
    assert config.port == 25


@pytest.mark.unit
def test_password_never_exposed_by_repr_or_str(monkeypatch):
    _set_full_smtp_env(monkeypatch)

    config = load_smtp_config()

    assert "s3cr3t" not in repr(config)
    assert "s3cr3t" not in str(config)


@pytest.mark.unit
def test_load_smtp_config_not_called_at_startup(tmp_path, monkeypatch):
    """load_config() (startup) must succeed with zero SMTP env set."""
    library = _make_library(tmp_path)
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(library))
    for var in (
        "CALIBRE_MCP_SMTP_RELAY",
        "CALIBRE_MCP_SMTP_PORT",
        "CALIBRE_MCP_SMTP_USERNAME",
        "CALIBRE_MCP_SMTP_PASSWORD",
        "CALIBRE_MCP_SMTP_ENCRYPTION",
        "CALIBRE_MCP_SMTP_FROM",
    ):
        monkeypatch.delenv(var, raising=False)

    config = load_config()

    assert config.library_path == library
