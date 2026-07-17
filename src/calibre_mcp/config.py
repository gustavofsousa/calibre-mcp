"""Startup configuration & validation (CFG-01, SAFE-05).

Resolve and validate the Calibre library path once at startup, and resolve the
backup root. Fail fast with a ConfigError that names the offending path so the
host can surface an actionable message.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError, SmtpNotConfiguredError

LIBRARY_PATH_ENV = "CALIBRE_LIBRARY_PATH"
BACKUP_DIR_ENV = "CALIBRE_MCP_BACKUP_DIR"
BACKUP_DIR_NAME = ".calibre-mcp-backups"

SMTP_RELAY_ENV = "CALIBRE_MCP_SMTP_RELAY"
SMTP_PORT_ENV = "CALIBRE_MCP_SMTP_PORT"
SMTP_USERNAME_ENV = "CALIBRE_MCP_SMTP_USERNAME"
SMTP_PASSWORD_ENV = "CALIBRE_MCP_SMTP_PASSWORD"
SMTP_ENCRYPTION_ENV = "CALIBRE_MCP_SMTP_ENCRYPTION"
SMTP_FROM_ENV = "CALIBRE_MCP_SMTP_FROM"

_DEFAULT_ENCRYPTION = "TLS"
_DEFAULT_PORT_BY_ENCRYPTION = {"SSL": 465, "TLS": 25, "NONE": 25}


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


@dataclass(frozen=True)
class SmtpConfig:
    """SMTP relay config for email_book (EMAIL-01, AD-015).

    password is env-only and must never be logged or returned in tool output;
    __repr__ masks it so accidental logging/printing never leaks it.
    """

    relay: str
    port: int
    username: str
    password: str
    encryption: str
    sender: str

    def __repr__(self) -> str:
        return (
            f"SmtpConfig(relay={self.relay!r}, port={self.port!r}, "
            f"username={self.username!r}, password='***', "
            f"encryption={self.encryption!r}, sender={self.sender!r})"
        )


def load_smtp_config() -> SmtpConfig:
    """Read and validate SMTP relay config from CALIBRE_MCP_SMTP_* env vars.

    Not called at startup — lazy, called only when email_book runs, so the
    server boots without SMTP configured. Raises SmtpNotConfiguredError naming
    the first missing required var (relay, username, password, sender).
    Encryption defaults to TLS; port defaults per encryption (465 for SSL,
    25 otherwise) when unset.
    """
    relay = os.environ.get(SMTP_RELAY_ENV)
    if not relay:
        raise SmtpNotConfiguredError(SMTP_RELAY_ENV)

    username = os.environ.get(SMTP_USERNAME_ENV)
    if not username:
        raise SmtpNotConfiguredError(SMTP_USERNAME_ENV)

    password = os.environ.get(SMTP_PASSWORD_ENV)
    if not password:
        raise SmtpNotConfiguredError(SMTP_PASSWORD_ENV)

    sender = os.environ.get(SMTP_FROM_ENV)
    if not sender:
        raise SmtpNotConfiguredError(SMTP_FROM_ENV)

    encryption = os.environ.get(SMTP_ENCRYPTION_ENV) or _DEFAULT_ENCRYPTION

    raw_port = os.environ.get(SMTP_PORT_ENV)
    port = (
        int(raw_port)
        if raw_port
        else _DEFAULT_PORT_BY_ENCRYPTION.get(encryption.upper(), 25)
    )

    return SmtpConfig(
        relay=relay,
        port=port,
        username=username,
        password=password,
        encryption=encryption,
        sender=sender,
    )
