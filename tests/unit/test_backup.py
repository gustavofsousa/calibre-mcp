"""Unit tests for the backup/trash safety net — derived from spec SAFE-01..04.

SAFE-01: every mutation copies metadata.db to backups/metadata-<ts>.db first.
SAFE-02: beyond the retention cap (default 20) only the oldest surplus is pruned.
SAFE-03: remove copies the book's files to backups/trash/<id>-<ts>/; missing
         files report a no-copy outcome without raising (design Risks).
SAFE-04: an unwritable backup dir aborts (raises) before any write.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from calibre_mcp.backup import backup_metadata_db, trash_book_files


@dataclass
class _FakeBook:
    id: int
    path: str


def _make_db(tmp_path: Path, content: bytes = b"DBDATA") -> Path:
    db = tmp_path / "metadata.db"
    db.write_bytes(content)
    return db


@pytest.mark.unit
def test_backup_creates_snapshot_with_same_content(tmp_path):
    # SAFE-01: a metadata-*.db snapshot is created holding the db's bytes.
    db = _make_db(tmp_path, b"HELLO")
    backup_root = tmp_path / "backups"

    dest = backup_metadata_db(db, backup_root)

    assert dest.exists()
    assert dest.parent == backup_root
    assert dest.name.startswith("metadata-") and dest.suffix == ".db"
    assert dest.read_bytes() == b"HELLO"


@pytest.mark.unit
def test_retention_keeps_only_newest_cap_and_prunes_oldest(tmp_path):
    # SAFE-02: after 25 backups with cap 20, exactly the 20 newest survive.
    db = _make_db(tmp_path)
    backup_root = tmp_path / "backups"

    created = [backup_metadata_db(db, backup_root, retention=20) for _ in range(25)]

    remaining = sorted(backup_root.glob("metadata-*.db"))
    assert len(remaining) == 20
    # the 5 oldest (first created) are gone; the 20 newest remain
    for old in created[:5]:
        assert not old.exists()
    for kept in created[5:]:
        assert kept.exists()


@pytest.mark.unit
def test_unwritable_backup_dir_aborts_before_write(tmp_path):
    # SAFE-04: backup dir cannot be created (a file blocks the path) -> raise,
    # no snapshot produced.
    db = _make_db(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"")  # a FILE where a directory is needed
    backup_root = blocker / "backups"

    with pytest.raises(OSError):
        backup_metadata_db(db, backup_root)

    assert not backup_root.exists()


@pytest.mark.unit
def test_trash_copies_book_files(tmp_path):
    # SAFE-03: the book's files are copied to backups/trash/<id>-<ts>/.
    library = tmp_path / "library"
    book_dir = library / "Author/Title (7)"
    book_dir.mkdir(parents=True)
    (book_dir / "book.epub").write_bytes(b"EPUB")
    (book_dir / "cover.jpg").write_bytes(b"JPG")
    backup_root = tmp_path / "backups"

    book = _FakeBook(id=7, path="Author/Title (7)")
    result = trash_book_files(book, library, backup_root)

    assert result.any_copied
    assert sorted(result.copied) == ["book.epub", "cover.jpg"]
    assert result.dest.parent == backup_root / "trash"
    assert result.dest.name.startswith("7-")
    assert (result.dest / "book.epub").read_bytes() == b"EPUB"


@pytest.mark.unit
def test_trash_missing_files_reports_no_copy_without_raising(tmp_path):
    # SAFE-03 / Risks: book files absent -> no-copy outcome, never blocks removal.
    library = tmp_path / "library"
    library.mkdir()
    backup_root = tmp_path / "backups"

    book = _FakeBook(id=9, path="Author/Gone (9)")  # directory does not exist
    result = trash_book_files(book, library, backup_root)

    assert not result.any_copied
    assert result.copied == []
