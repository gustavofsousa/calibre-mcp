"""Data-safety net: metadata backups + recoverable trash (SAFE-01..04, AD-011/009).

Every mutation is preceded by a recoverable snapshot of ``metadata.db``, and
every delete first copies the book's files to a managed trash folder. These are
pure filesystem side effects, kept out of the facade so the ordering contract
(backup BEFORE any ``calibredb`` write) is easy to enforce and test.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .sqlite_reader import Book

DEFAULT_RETENTION = 20
_TRASH_DIR = "trash"


@dataclass
class TrashResult:
    """Outcome of trashing a book's files before removal (SAFE-03)."""

    dest: Path
    copied: list[str] = field(default_factory=list)

    @property
    def any_copied(self) -> bool:
        return bool(self.copied)


def _timestamp() -> str:
    # Microsecond precision keeps rapidly-created snapshots unique and makes the
    # filename sort chronologically (used by retention pruning).
    return datetime.now().strftime("%Y%m%d-%H%M%S-%f")


def backup_metadata_db(
    db_path: Path,
    backup_root: Path,
    retention: int = DEFAULT_RETENTION,
) -> Path:
    """Copy ``metadata.db`` into ``backup_root`` and prune to ``retention``.

    Returns the created snapshot path. Raises ``OSError`` (aborting before the
    caller runs any ``calibredb`` write) if the backup dir cannot be created or
    written (SAFE-04). Prunes only the oldest surplus beyond ``retention``
    (SAFE-02).
    """
    db_path = Path(db_path)
    backup_root = Path(backup_root)

    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        dest = _unique_snapshot_path(backup_root, _timestamp())
        shutil.copy2(db_path, dest)
    except OSError as exc:
        raise OSError(
            f"cannot back up metadata.db to {backup_root}; write aborted: {exc}"
        ) from exc

    _prune(backup_root, retention)
    return dest


def _unique_snapshot_path(backup_root: Path, ts: str) -> Path:
    """Never overwrite an existing snapshot: break same-microsecond ties.

    Guarantees a snapshot is really created for every write (SAFE-01) even when
    two backups land in the same microsecond. The zero-padded suffix keeps names
    lexicographically grouped for chronological retention pruning.
    """
    dest = backup_root / f"metadata-{ts}.db"
    counter = 1
    while dest.exists():
        dest = backup_root / f"metadata-{ts}-{counter:03d}.db"
        counter += 1
    return dest


def _prune(backup_root: Path, retention: int) -> None:
    """Delete only the oldest snapshots beyond the retention cap (SAFE-02)."""
    snapshots = sorted(backup_root.glob("metadata-*.db"))  # oldest first by name
    surplus = max(0, len(snapshots) - retention)
    for old in snapshots[:surplus]:
        old.unlink()


def trash_book_files(
    book: Book,
    library_path: Path,
    backup_root: Path,
) -> TrashResult:
    """Copy a book's files to ``backup_root/trash/<id>-<ts>/`` before removal.

    Copies the top-level files in the book's library directory. If those files
    are missing, returns a ``TrashResult`` reporting nothing was copied WITHOUT
    raising, so the recycle-bin path is never blocked (SAFE-03, design Risks).
    """
    library_path = Path(library_path)
    backup_root = Path(backup_root)
    dest = backup_root / _TRASH_DIR / f"{book.id}-{_timestamp()}"

    src = library_path / book.path
    if not src.is_dir():
        return TrashResult(dest=dest, copied=[])

    files = [p for p in src.iterdir() if p.is_file()]
    if not files:
        return TrashResult(dest=dest, copied=[])

    dest.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for f in files:
        shutil.copy2(f, dest / f.name)
        copied.append(f.name)

    return TrashResult(dest=dest, copied=copied)
