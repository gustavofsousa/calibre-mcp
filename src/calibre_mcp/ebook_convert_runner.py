"""The single ``ebook-convert`` subprocess call site (CONV-01, AD-014).

Mirrors ``CalibredbRunner._run``'s discipline: arg-list, ``shell=False``,
failure->taxonomy. No shell interpolation of source/target paths.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .errors import EbookConvertError, EbookConvertNotFoundError

_TIMEOUT_SECONDS = 300


class EbookConvertRunner:
    """Runs ``ebook-convert`` to produce a new format file from a source."""

    def __init__(self, binary: str = "ebook-convert") -> None:
        self._binary = binary

    def convert(self, source: Path, target_ext: str, out_dir: Path) -> Path:
        """Convert ``source`` into ``<out_dir>/<source.stem>.<target_ext>``.

        Returns the produced path. Missing binary -> EbookConvertNotFoundError;
        non-zero exit or timeout -> EbookConvertError carrying stderr; never a
        false success (CONV-01 AC-5).
        """
        target = Path(out_dir) / f"{Path(source).stem}.{target_ext}"
        cmd = [self._binary, str(source), str(target)]
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
            raise EbookConvertNotFoundError() from exc
        except subprocess.TimeoutExpired as exc:
            raise EbookConvertError(
                cmd, -1, f"ebook-convert timed out after {_TIMEOUT_SECONDS}s"
            ) from exc

        if proc.returncode != 0:
            raise EbookConvertError(cmd, proc.returncode, proc.stderr)
        return target
