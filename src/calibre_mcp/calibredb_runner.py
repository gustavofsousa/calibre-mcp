"""The single ``calibredb`` subprocess call site (SEARCH-01, EDIT-02, ADD, REM-02).

Every mutation and search that needs Calibre's own logic goes through here.
``_run`` is the ONLY place ``subprocess`` is invoked; it always uses an argument
list with ``shell=False`` (kills command injection from metadata/path values)
and classifies failures into the error taxonomy. Reads never come here — they go
through ``SqliteReader``.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import (
    CalibredbError,
    CalibredbNotFoundError,
    LibraryLockedError,
)

# calibredb prints this to stderr (exit 1) when a search matches nothing — that
# is an empty result, not a failure.
_NO_MATCH = "no books matching the search expression"
_ADDED_IDS = re.compile(r"Added book ids:\s*([\d,]+)")
_DUPLICATE = "already exist in the database"
# Substrings Calibre uses when the library is held by another process.
_LOCK_INDICATORS = (
    "another calibre",
    "is running",
    "cannot acquire lock",
    "database is locked",
)


def _format_field_value(name: str, value: Any) -> str:
    """Render one ``--field name:value`` value the way calibredb expects it.

    List-valued fields are joined field-specifically: ``authors`` with
    ``" & "``, other list fields (tags/languages) with ``,`` (AD-022).
    ``calibredb set_metadata --field "authors:A,B"`` mashes co-authors into a
    single author entity ``"A|B"``; ``" & "`` creates two distinct authors,
    matching how Calibre itself displays/stores multi-author credits.
    """
    if isinstance(value, list):
        separator = " & " if name == "authors" else ","
        return separator.join(value)
    if name == "rating":
        # INVARIANT: callers speak Calibre's stored 0-10 scale (what the reader
        # returns), but calibredb's --field rating takes STARS and stores N*2.
        # Halving here is what keeps a write equal to its re-read (8 -> 4 stars
        # -> stored 8); half stars are accepted (7 -> "3.5").
        return f"{value / 2:g}"
    return str(value)


@dataclass
class AddResult:
    """Outcome of ``calibredb add`` (ADD-01/03)."""

    book_id: int | None
    duplicate: bool


class CalibredbRunner:
    """Runs ``calibredb`` subcommands against one library."""

    def __init__(self, library_path: Path, binary: str = "calibredb") -> None:
        self._library_path = Path(library_path)
        self._binary = binary

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """The only subprocess call site: arg-list, ``shell=False``."""
        cmd = [
            self._binary,
            *args,
            "--with-library",
            str(self._library_path),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
        except FileNotFoundError as exc:
            raise CalibredbNotFoundError() from exc

        if proc.returncode != 0:
            self._raise_for_error(cmd, proc.returncode, proc.stderr)
        return proc

    @staticmethod
    def _raise_for_error(cmd: list[str], returncode: int, stderr: str) -> None:
        low = stderr.lower()
        if any(indicator in low for indicator in _LOCK_INDICATORS):
            raise LibraryLockedError(stderr)
        raise CalibredbError(cmd, returncode, stderr)

    def search(self, query: str) -> list[int]:
        """Return matching book ids (SEARCH-01); no matches -> empty list."""
        try:
            proc = self._run(["search", query])
        except CalibredbError as exc:
            if _NO_MATCH in exc.stderr.lower():
                return []
            raise
        out = proc.stdout.strip()
        if not out:
            return []
        return [int(piece) for piece in out.split(",") if piece.strip()]

    def set_metadata(self, book_id: int, fields: dict[str, Any]) -> None:
        """Apply ``fields`` via one ``--field`` per pair (EDIT-02)."""
        args = ["set_metadata", str(book_id)]
        for name, value in fields.items():
            args += ["--field", f"{name}:{_format_field_value(name, value)}"]
        self._run(args)

    def add(self, path: Path) -> AddResult:
        """Import ``path`` and return the new id, or a duplicate outcome.

        Parses ``Added book ids: N`` from stdout (ADD-01); recognizes Calibre's
        duplicate message (ADD-03). If neither is present, raises rather than
        guessing an id (design Risks).
        """
        proc = self._run(["add", str(path)])
        output = f"{proc.stdout}\n{proc.stderr}"
        match = _ADDED_IDS.search(output)
        if match:
            first_id = match.group(1).split(",")[0]
            return AddResult(book_id=int(first_id), duplicate=False)
        if _DUPLICATE in output:
            return AddResult(book_id=None, duplicate=True)
        raise CalibredbError(
            ["add", str(path)],
            proc.returncode,
            f"could not parse added book id from: {output.strip()}",
        )

    def remove(self, book_id: int) -> None:
        """Remove a book WITHOUT ``--permanent`` (recycle bin) (REM-02, AD-009)."""
        self._run(["remove", str(book_id)])

    def add_format(self, book_id: int, path: Path) -> None:
        """Attach ``path`` as a new format on ``book_id``, additive (CONV-01).

        ``--dont-replace`` guarantees an existing format is never overwritten;
        failure is classified by the existing ``_raise_for_error``.
        """
        self._run(["add_format", "--dont-replace", str(book_id), str(path)])
