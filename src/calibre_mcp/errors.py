"""Failure taxonomy.

One place for the failure types every layer maps to, so failures are explicit
and uniform (spec §Error Handling). Each exception carries the fields the
design names so callers can shape LLM-friendly, actionable messages.
"""

from __future__ import annotations


class CalibreMcpError(Exception):
    """Base class for every error this server raises."""


class ConfigError(CalibreMcpError):
    """Startup configuration is invalid (e.g. library path unset or no db)."""


class BookNotFoundError(CalibreMcpError):
    """A referenced book id does not exist in the library."""

    def __init__(self, book_id: int) -> None:
        self.book_id = book_id
        super().__init__(f"book {book_id} not found")


class InvalidInputError(CalibreMcpError):
    """Untrusted input failed validation before touching the db/subprocess."""

    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__(msg)


class LibraryLockedError(CalibreMcpError):
    """The library is locked by another process (e.g. the Calibre GUI)."""

    def __init__(self, stderr: str) -> None:
        self.stderr = stderr
        super().__init__(
            "library is locked by another process; close Calibre and retry"
        )


class CalibredbError(CalibreMcpError):
    """calibredb exited non-zero; carries the command, exit code, and stderr."""

    def __init__(self, cmd: list[str], exit_code: int, stderr: str) -> None:
        self.cmd = cmd
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"calibredb failed (exit {exit_code}): {stderr.strip()}")


class CalibredbNotFoundError(CalibreMcpError):
    """The calibredb binary is not installed / not on PATH."""

    def __init__(self) -> None:
        super().__init__("calibredb not installed or not on PATH")


class ConfirmationError(CalibreMcpError):
    """The supplied confirmation token does not match the requested change."""


class EbookConvertError(CalibreMcpError):
    """ebook-convert exited non-zero; carries the command, exit code, and stderr."""

    def __init__(self, cmd: list[str], exit_code: int, stderr: str) -> None:
        self.cmd = cmd
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"ebook-convert failed (exit {exit_code}): {stderr.strip()}")


class EbookConvertNotFoundError(CalibreMcpError):
    """The ebook-convert binary is not installed / not on PATH."""

    def __init__(self) -> None:
        super().__init__("ebook-convert not installed or not on PATH")


class CalibreSmtpError(CalibreMcpError):
    """calibre-smtp exited non-zero; carries the command, exit code, and stderr.

    stderr is expected to already be scrubbed of the SMTP password by the caller.
    """

    def __init__(self, cmd: list[str], exit_code: int, stderr: str) -> None:
        self.cmd = cmd
        self.exit_code = exit_code
        self.stderr = stderr
        super().__init__(f"calibre-smtp failed (exit {exit_code}): {stderr.strip()}")


class CalibreSmtpNotFoundError(CalibreMcpError):
    """The calibre-smtp binary is not installed / not on PATH."""

    def __init__(self) -> None:
        super().__init__("calibre-smtp not installed or not on PATH")


class EnrichmentSourceError(CalibreMcpError):
    """An outbound enrichment source (e.g. Open Library) failed (ENRICH-01).

    Raised when the external source is unreachable, times out, returns an HTTP
    error (>=400 other than a clean not-found), or sends an unparseable body.
    Carries a short human-readable reason and, optionally, the URL that failed
    (never any secret — these requests carry none).
    """

    def __init__(self, reason: str, url: str | None = None) -> None:
        self.reason = reason
        self.url = url
        detail = reason if url is None else f"{reason} ({url})"
        super().__init__(f"enrichment source failed: {detail}")


class SmtpNotConfiguredError(ConfigError):
    """A required CALIBRE_MCP_SMTP_* environment variable is unset."""

    def __init__(self, missing_var: str) -> None:
        self.missing_var = missing_var
        super().__init__(
            f"SMTP not configured; set {missing_var} (see CALIBRE_MCP_SMTP_* vars)"
        )
