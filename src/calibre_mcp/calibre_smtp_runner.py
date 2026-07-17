"""The single ``calibre-smtp`` subprocess call site (EMAIL-01, AD-014, AD-015).

Outward-facing: sends a book's file as an email attachment via an SMTP relay.
Mirrors ``CalibredbRunner._run``'s discipline (arg-list, ``shell=False``,
failure->taxonomy) with one addition: the relay password is a secret that must
never be logged, returned, or left un-scrubbed in an error message, even
though the CLI itself requires it as a plain argument (AD-015 known
limitation: visible in the process arg list / ``ps``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .config import SmtpConfig
from .errors import CalibreSmtpError, CalibreSmtpNotFoundError

_TIMEOUT_SECONDS = 120
_PASSWORD_PLACEHOLDER = "***"


class CalibreSmtpRunner:
    """Sends one email (compose mode) via ``calibre-smtp``."""

    def __init__(self, binary: str = "calibre-smtp") -> None:
        self._binary = binary

    def send(
        self,
        cfg: SmtpConfig,
        sender: str,
        recipient: str,
        subject: str,
        body: str,
        attachment: Path,
    ) -> None:
        """Send ``attachment`` to ``recipient`` via the relay in ``cfg``.

        Missing binary -> CalibreSmtpNotFoundError; non-zero exit or timeout ->
        CalibreSmtpError with stderr scrubbed of the password. The password
        never appears in the raised exception's message/attributes.
        """
        cmd = [
            self._binary,
            "-a",
            str(attachment),
            "-s",
            subject,
            "--relay",
            cfg.relay,
            "--port",
            str(cfg.port),
            "-u",
            cfg.username,
            "-p",
            cfg.password,
            "-e",
            cfg.encryption,
            sender,
            recipient,
            body,
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
                timeout=_TIMEOUT_SECONDS,
            )
        except FileNotFoundError as exc:
            raise CalibreSmtpNotFoundError() from exc
        except subprocess.TimeoutExpired as exc:
            stderr = self._scrub(
                f"calibre-smtp timed out after {_TIMEOUT_SECONDS}s", cfg.password
            )
            scrubbed_cmd = self._scrub_cmd(cmd, cfg.password)
            raise CalibreSmtpError(scrubbed_cmd, -1, stderr) from exc

        if proc.returncode != 0:
            stderr = self._scrub(proc.stderr, cfg.password)
            raise CalibreSmtpError(
                self._scrub_cmd(cmd, cfg.password), proc.returncode, stderr
            )

    @staticmethod
    def _scrub(text: str, password: str) -> str:
        if not password:
            return text
        return text.replace(password, _PASSWORD_PLACEHOLDER)

    @staticmethod
    def _scrub_cmd(cmd: list[str], password: str) -> list[str]:
        return [_PASSWORD_PLACEHOLDER if arg == password else arg for arg in cmd]
