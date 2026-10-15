"""Integration tests for the CalibreLibrary facade — mutations (T9).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` so the backup dir starts empty and each mutation's own
backup is observable.

EDIT-01: plan (no token) returns a current->proposed diff + token, no write.
EDIT-02: apply (token) backs up, applies, and returns the re-read record.
EDIT-03: a mismatched token is refused (ConfirmationError), no write.
EDIT-04: a field outside the whitelist is rejected, listing the allowed fields.
EDIT-05: a calibredb failure surfaces stderr and never reports success.
EDIT-06: an unknown book id raises "not found" at the plan step, no write.
EDIT-07: series_index without series, or rating outside 0-10, rejected at plan.
ADD-01:  add backs up, imports, and returns the new id + metadata.
ADD-02:  a nonexistent path is rejected before any subprocess (and before backup).
ADD-03:  a duplicate is surfaced, not hidden behind a fake id.
ADD-04:  a calibredb add failure surfaces stderr.
REM-01:  review (no token) returns details + token, nothing deleted.
REM-02:  apply trashes files, backs up, removes via recycle bin, reports trash.
REM-03:  an unknown id raises "not found" (no-op), never a false success.
REM-04:  a calibredb remove failure never claims removal; trash leftovers remain.
REM-05:  a mismatched token is refused, nothing deleted.
SAFE-03: when the book's files are missing, trash reports no copy (still removes).
SAFE-04: backup failure aborts the mutation BEFORE any calibredb write.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp import library as library_module
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import (
    BookNotFoundError,
    CalibredbError,
    ConfirmationError,
    InvalidInputError,
)
from calibre_mcp.library import CalibreLibrary
from sample_books import sample_epub_sources


def _sample_epub(tmp_path: Path, name: str = "sample.epub") -> Path:
    """Copy one synthetic sample .epub into a temp path."""
    sources = sample_epub_sources()
    dest = tmp_path / name
    shutil.copy2(sources[0], dest)
    return dest


@pytest.fixture
def backup_root(tmp_path: Path) -> Path:
    # A backup root OUTSIDE the library dir so it starts empty and is isolated.
    return tmp_path / "backups"


@pytest.fixture
def config(scratch_library: Path, backup_root: Path) -> Config:
    return Config(
        library_path=scratch_library,
        db_path=scratch_library / "metadata.db",
        backup_root=backup_root,
    )


@pytest.fixture
def facade(config: Config) -> CalibreLibrary:
    return CalibreLibrary(config)


def _seed_book(scratch_library: Path, tmp_path: Path, name: str = "seed.epub") -> int:
    """Add a book directly via the runner (no facade backup) and return its id."""
    result = CalibredbRunner(scratch_library).add(_sample_epub(tmp_path, name))
    assert result.book_id is not None
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# --------------------------------------------------------------------- EDIT


@pytest.mark.integration
def test_update_plan_returns_diff_and_token_without_writing(
    facade, scratch_library, tmp_path
):
    # EDIT-01: no token -> diff + token, and the library is untouched.
    book_id = _seed_book(scratch_library, tmp_path)

    plan = facade.update_metadata(book_id, {"tags": ["scifi", "classic"]})

    assert plan["status"] == "plan"
    assert plan["diff"]["tags"]["proposed"] == ["scifi", "classic"]
    assert "tags" in plan["diff"] and "current" in plan["diff"]["tags"]
    assert plan["confirmation_token"]
    # nothing was written
    assert facade.get_book(book_id).tags == []


@pytest.mark.integration
def test_update_apply_with_token_writes_and_rereads(
    facade, scratch_library, backup_root, tmp_path
):
    # EDIT-02: token match -> backup, apply, re-read reflects the change.
    book_id = _seed_book(scratch_library, tmp_path)
    plan = facade.update_metadata(book_id, {"tags": ["scifi", "classic"]})

    applied = facade.update_metadata(
        book_id, {"tags": ["scifi", "classic"]}, token=plan["confirmation_token"]
    )

    assert applied["status"] == "applied"
    assert set(applied["book"].tags) == {"scifi", "classic"}
    assert facade.get_book(book_id).tags  # persisted
    assert len(_snapshots(backup_root)) == 1  # backup taken before the write


@pytest.mark.integration
def test_update_token_mismatch_refuses_and_does_not_write(
    facade, scratch_library, tmp_path
):
    # EDIT-03: a wrong token is refused; nothing is written.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(ConfirmationError):
        facade.update_metadata(book_id, {"tags": ["x"]}, token="deadbeefdeadbeef")

    assert facade.get_book(book_id).tags == []


@pytest.mark.integration
def test_update_rejects_field_outside_whitelist(facade, scratch_library, tmp_path):
    # EDIT-04: an unknown field is rejected, listing the allowed fields, no token.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError) as excinfo:
        facade.update_metadata(book_id, {"bogus_field": "x"})

    assert "bogus_field" in str(excinfo.value)
    assert "allowed" in str(excinfo.value)


@pytest.mark.integration
def test_update_series_index_without_series_rejected(facade, scratch_library, tmp_path):
    # EDIT-07: series_index without series is rejected at the plan step.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError):
        facade.update_metadata(book_id, {"series_index": 2.0})


@pytest.mark.integration
def test_update_rating_out_of_range_rejected(facade, scratch_library, tmp_path):
    # EDIT-07: a rating outside 0-10 is rejected at the plan step.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError):
        facade.update_metadata(book_id, {"rating": 11})
    with pytest.raises(InvalidInputError):
        facade.update_metadata(book_id, {"rating": -1})


@pytest.mark.integration
def test_update_unknown_book_raises_not_found_no_write(facade, backup_root):
    # EDIT-06: a missing id fails at the plan step with no write attempted.
    with pytest.raises(BookNotFoundError) as excinfo:
        facade.update_metadata(999999, {"tags": ["x"]})

    assert excinfo.value.book_id == 999999
    assert _snapshots(backup_root) == []  # no backup, no write


@pytest.mark.integration
def test_update_calibredb_failure_surfaces_stderr_no_false_success(
    facade, scratch_library, backup_root, tmp_path, monkeypatch
):
    # EDIT-05: a non-zero calibredb exit propagates with stderr; no false success.
    book_id = _seed_book(scratch_library, tmp_path)
    plan = facade.update_metadata(book_id, {"tags": ["x"]})

    def _boom(*_a, **_k):
        raise CalibredbError(["set_metadata"], 1, "calibredb boom: bad value")

    monkeypatch.setattr(facade._runner, "set_metadata", _boom)

    token = plan["confirmation_token"]
    with pytest.raises(CalibredbError) as excinfo:
        facade.update_metadata(book_id, {"tags": ["x"]}, token=token)

    assert "boom" in excinfo.value.stderr
    assert len(_snapshots(backup_root)) == 1  # backup happened BEFORE the failed write


# ---------------------------------------------------------------------- ADD


@pytest.mark.integration
def test_add_imports_and_returns_id_and_metadata(facade, backup_root, tmp_path):
    # ADD-01: backup then import then return the new id + metadata.
    result = facade.add_book(_sample_epub(tmp_path))

    assert result["status"] == "added"
    assert isinstance(result["book_id"], int)
    assert result["book"].id == result["book_id"]
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_add_nonexistent_path_rejected_before_subprocess(facade, backup_root):
    # ADD-02: a path that is not a file is rejected before calibredb (and backup).
    with pytest.raises(InvalidInputError):
        facade.add_book("/no/such/file.epub")

    assert _snapshots(backup_root) == []  # validated before backup/subprocess


@pytest.mark.integration
def test_add_duplicate_surfaced_not_hidden(facade, tmp_path):
    # ADD-03: re-adding the same file is reported as duplicate, not a fake id.
    epub = _sample_epub(tmp_path)
    facade.add_book(epub)

    second = facade.add_book(epub)

    assert second["status"] == "duplicate"
    assert second["duplicate"] is True
    assert second["book_id"] is None


@pytest.mark.integration
def test_import_one_added_branch_returns_real_id_and_book(facade, tmp_path):
    # BIMPORT-06 (via shared core): success -> real book_id + re-read metadata.
    epub = _sample_epub(tmp_path)

    result = facade._import_one(epub)

    assert result["duplicate"] is False
    assert isinstance(result["book_id"], int)
    assert result["book"].id == result["book_id"]


@pytest.mark.integration
def test_import_one_duplicate_branch_never_returns_fake_id(facade, tmp_path):
    # BIMPORT-05 (via shared core): a re-add is surfaced as duplicate, no id.
    epub = _sample_epub(tmp_path)
    facade._import_one(epub)

    result = facade._import_one(epub)

    assert result == {"duplicate": True, "book_id": None}


@pytest.mark.integration
def test_add_calibredb_failure_surfaces_stderr(facade, tmp_path, monkeypatch):
    # ADD-04: a calibredb add failure propagates with its stderr.
    epub = _sample_epub(tmp_path)

    def _boom(*_a, **_k):
        raise CalibredbError(["add"], 1, "calibredb boom: unsupported file")

    monkeypatch.setattr(facade._runner, "add", _boom)

    with pytest.raises(CalibredbError) as excinfo:
        facade.add_book(epub)

    assert "boom" in excinfo.value.stderr


# ------------------------------------------------------------------- REMOVE


@pytest.mark.integration
def test_remove_review_returns_details_and_token_without_deleting(
    facade, scratch_library, tmp_path
):
    # REM-01: no token -> review (title/authors/formats + recoverable note) + token.
    book_id = _seed_book(scratch_library, tmp_path)

    review = facade.remove_book(book_id)

    assert review["status"] == "review"
    assert review["title"]
    assert review["recoverable"] is True
    assert "trash" in review["note"] and "recycle bin" in review["note"]
    assert review["confirmation_token"]
    facade.get_book(book_id)  # still present (no BookNotFoundError)


@pytest.mark.integration
def test_remove_apply_trashes_backs_up_and_removes(
    facade, scratch_library, backup_root, tmp_path
):
    # REM-02: order = trash files -> backup db -> recycle-bin remove; report trash.
    book_id = _seed_book(scratch_library, tmp_path)
    review = facade.remove_book(book_id)

    removed = facade.remove_book(book_id, token=review["confirmation_token"])

    assert removed["status"] == "removed"
    assert removed["files_copied"] is True
    trash_dir = Path(removed["trash_location"])
    assert trash_dir.is_dir() and any(trash_dir.iterdir())  # files really copied
    assert len(_snapshots(backup_root)) == 1  # metadata.db backed up
    with pytest.raises(BookNotFoundError):  # gone from the library
        facade.get_book(book_id)


@pytest.mark.integration
def test_remove_unknown_id_raises_not_found_no_false_success(facade, backup_root):
    # REM-03: a missing id is a no-op not-found, never a false "removed".
    with pytest.raises(BookNotFoundError) as excinfo:
        facade.remove_book(999999)

    assert excinfo.value.book_id == 999999
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_remove_token_mismatch_refuses_and_keeps_book(
    facade, scratch_library, tmp_path
):
    # REM-05: a wrong token is refused; the book stays.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(ConfirmationError):
        facade.remove_book(book_id, token="deadbeefdeadbeef")

    facade.get_book(book_id)  # still present


@pytest.mark.integration
def test_remove_missing_files_reports_no_copy_but_removes(
    facade, scratch_library, tmp_path
):
    # SAFE-03: if the book's files are gone, trash reports no copy and removal
    # still proceeds (the recycle-bin path is never blocked).
    book_id = _seed_book(scratch_library, tmp_path)
    book = facade.get_book(book_id)
    shutil.rmtree(scratch_library / book.path)  # wipe the book's files
    review = facade.remove_book(book_id)

    removed = facade.remove_book(book_id, token=review["confirmation_token"])

    assert removed["status"] == "removed"
    assert removed["files_copied"] is False
    with pytest.raises(BookNotFoundError):
        facade.get_book(book_id)


@pytest.mark.integration
def test_remove_calibredb_failure_no_false_removed_trash_safe(
    facade, scratch_library, backup_root, tmp_path, monkeypatch
):
    # REM-04: a calibredb remove failure never claims removal; trash leftovers stay.
    book_id = _seed_book(scratch_library, tmp_path)
    review = facade.remove_book(book_id)

    def _boom(*_a, **_k):
        raise CalibredbError(["remove"], 1, "calibredb boom: locked")

    monkeypatch.setattr(facade._runner, "remove", _boom)

    with pytest.raises(CalibredbError):
        facade.remove_book(book_id, token=review["confirmation_token"])

    facade.get_book(book_id)  # NOT removed
    trash = backup_root / "trash"
    assert trash.is_dir() and any(trash.iterdir())  # copied files remain as leftovers


# ------------------------------------------------------------------- SAFE-04


@pytest.mark.integration
def test_update_backup_failure_aborts_before_write(
    facade, scratch_library, tmp_path, monkeypatch
):
    # SAFE-04: backup failure aborts the edit before any calibredb write.
    book_id = _seed_book(scratch_library, tmp_path)
    plan = facade.update_metadata(book_id, {"tags": ["x"]})
    token = plan["confirmation_token"]
    _forbid_write(facade, monkeypatch, "set_metadata")
    _make_backup_fail(monkeypatch)

    with pytest.raises(OSError):
        facade.update_metadata(book_id, {"tags": ["x"]}, token=token)

    assert facade.get_book(book_id).tags == []  # unchanged


@pytest.mark.integration
def test_add_backup_failure_aborts_before_write(facade, monkeypatch, tmp_path):
    # SAFE-04: backup failure aborts the add before any calibredb write.
    epub = _sample_epub(tmp_path)
    _forbid_write(facade, monkeypatch, "add")
    _make_backup_fail(monkeypatch)

    with pytest.raises(OSError):
        facade.add_book(epub)

    assert facade.list_books() == []  # nothing imported


@pytest.mark.integration
def test_remove_backup_failure_aborts_before_write(
    facade, scratch_library, tmp_path, monkeypatch
):
    # SAFE-04: backup failure (after trash) aborts the remove before calibredb.
    book_id = _seed_book(scratch_library, tmp_path)
    review = facade.remove_book(book_id)
    _forbid_write(facade, monkeypatch, "remove")
    _make_backup_fail(monkeypatch)

    with pytest.raises(OSError):
        facade.remove_book(book_id, token=review["confirmation_token"])

    facade.get_book(book_id)  # still present, no calibredb write happened


def _make_backup_fail(monkeypatch):
    """Simulate an unwritable backup dir (backup_metadata_db's SAFE-04 contract)."""

    def _fail(*_a, **_k):
        raise OSError("cannot back up metadata.db; write aborted")

    monkeypatch.setattr(library_module, "backup_metadata_db", _fail)


def _forbid_write(facade, monkeypatch, method: str):
    """Fail loudly if the calibredb write runs — proves the abort came first."""

    def _must_not_run(*_a, **_k):
        raise AssertionError(f"calibredb {method} ran despite backup failure")

    monkeypatch.setattr(facade._runner, method, _must_not_run)
