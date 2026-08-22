"""Pure filesystem discovery for folder import (BULK-03, AD-021).

The only place that walks a directory tree — no ``calibredb``, no ``sqlite3``,
no side effects beyond reading the filesystem. Confines the "filesystem-walk"
I/O kind to one pure module (AD-021), mirroring ``bulk_edit.py``'s pure-module
role, so ``library.py`` orchestrates and the tool layer never walks directly.
"""

from __future__ import annotations

import os
from pathlib import Path

# Curated whitelist of unambiguous ebook-container formats (spec Assumptions).
# Ambiguous document/metadata formats (txt, html, rtf, doc, opf, ...) are
# deliberately excluded — usually folder noise, not user ebook content.
EBOOK_EXTENSIONS = frozenset(
    {
        ".epub",
        ".mobi",
        ".azw",
        ".azw3",
        ".azw4",
        ".kfx",
        ".fb2",
        ".fbz",
        ".pdf",
        ".djvu",
        ".cbz",
        ".cbr",
        ".cbc",
        ".lit",
        ".lrf",
        ".pdb",
        ".prc",
        ".snb",
        ".tcr",
    }
)


def scan_ebook_files(root: Path) -> list[Path]:
    """Return every ebook-candidate file under ``root``, recursively (BIMPORT-01).

    Whitelist match is by case-insensitive suffix; hidden entries (dotfiles and
    dotdirs) are excluded — hidden directories are pruned in-place so an entire
    hidden subtree (e.g. ``.git``) is skipped, not just its files. Symlinks are
    never followed (``followlinks=False``). Result is sorted by path string for
    deterministic downstream reporting (BIMPORT-07).
    """
    matches: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            if Path(name).suffix.lower() in EBOOK_EXTENSIONS:
                matches.append(Path(dirpath) / name)
    return sorted(matches, key=str)
