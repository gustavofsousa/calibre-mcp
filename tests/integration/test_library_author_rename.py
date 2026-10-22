"""Integration tests for ``CalibreLibrary.rename_author`` (ORGN-01, ARENAME-01..08).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` (add + set_metadata authors) so the backup dir starts
empty and the batch's own backup is observable.

ARENAME-01: plan (no token) returns a per-book resolved diff + one token, no write.
ARENAME-02: old_name matching no author is rejected before any backup.
ARENAME-03: blank new_name or new_name == old_name is rejected before any backup.
ARENAME-04: apply (token) backs up once, applies via set_metadata, returns backup path.
ARENAME-05: a mismatched token is refused, nothing written.
ARENAME-06: one book's failure lands in failed; the rest still apply.
ARENAME-07: co-author-safe replace + in-book dedupe/merge onto an existing name.
ARENAME-08: applied entries re-read the resulting authors.
Edge case: a single-book batch still runs the full plan->confirm path.
Design Risk L-001: the backup runs before the first set_metadata write.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp import library as library_module
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import CalibredbError, ConfirmationError, InvalidInputError
from calibre_mcp.library import CalibreLibrary
from sample_books import sample_epub_sources


def _sample_epub(tmp_path: Path, name: str, index: int = 0) -> Path:
    # ``index`` picks a distinct source file so two seeded books in the same
    # test are never byte-identical (calibredb would flag a duplicate).
    sources = sample_epub_sources()
    dest = tmp_path / name
    shutil.copy2(sources[index], dest)
    return dest


@pytest.fixture
def backup_root(tmp_path: Path) -> Path:
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


def _seed_book(
    scratch_library: Path,
    tmp_path: Path,
    name: str,
    authors: list[str],
    index: int = 0,
) -> int:
    """Add a book directly via the runner and set its authors (no facade backup)."""
    runner = CalibredbRunner(scratch_library)
    result = runner.add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    runner.set_metadata(result.book_id, {"authors": authors})
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# --------------------------------------------------------------------- plan


@pytest.mark.integration
def test_plan_lists_affected_books_with_resolved_diffs_without_writing(
    facade, scratch_library, tmp_path
):
    # ARENAME-01 (Independent Test 1): co-author preserved, third book untouched.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Old Name"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["Old Name", "Co Author"], 1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", ["Someone Else"], 2)

    plan = facade.rename_author("Old Name", "New Name")

    assert plan["status"] == "plan"
    by_id = {d["book_id"]: d for d in plan["diffs"]}
    assert set(by_id) == {b1, b2}  # b3 not affected
    assert by_id[b1]["diff"]["authors"]["proposed"] == ["New Name"]
    assert by_id[b2]["diff"]["authors"]["proposed"] == ["New Name", "Co Author"]
    assert plan["confirmation_token"]
    # nothing was written
    assert facade.get_book(b1).authors == ["Old Name"]
    assert facade.get_book(b2).authors == ["Old Name", "Co Author"]
    assert facade.get_book(b3).authors == ["Someone Else"]


@pytest.mark.integration
def test_plan_rejects_author_not_found_before_backup(facade, backup_root):
    # ARENAME-02: no book credited to old_name -> rejected before any backup.
    with pytest.raises(InvalidInputError) as excinfo:
        facade.rename_author("Nobody At All", "New Name")

    assert "not found" in str(excinfo.value).lower()
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_new_name_blank_or_equal_to_old_rejected_before_backup(
    facade, scratch_library, tmp_path, backup_root
):
    # ARENAME-03: blank new_name, or new_name == old_name, rejected before backup.
    _seed_book(scratch_library, tmp_path, "b1.epub", ["Old Name"])

    with pytest.raises(InvalidInputError):
        facade.rename_author("Old Name", "")
    with pytest.raises(InvalidInputError):
        facade.rename_author("Old Name", "   ")
    with pytest.raises(InvalidInputError):
        facade.rename_author("Old Name", "Old Name")
    assert _snapshots(backup_root) == []


# -------------------------------------------------------------------- apply


@pytest.mark.integration
def test_apply_writes_resolved_authors_backs_up_once_and_rereads(
    facade, scratch_library, backup_root, tmp_path
):
    # ARENAME-04/08: apply backs up once, writes each resolved list, re-reads.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Old Name"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["Old Name", "Co Author"], 1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", ["Someone Else"], 2)
    plan = facade.rename_author("Old Name", "New Name")

    applied = facade.rename_author(
        "Old Name", "New Name", token=plan["confirmation_token"]
    )

    assert applied["status"] == "renamed"
    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert by_id[b1]["authors"] == ["New Name"]
    assert by_id[b2]["authors"] == ["New Name", "Co Author"]
    assert applied["failed"] == []
    assert facade.get_book(b1).authors == ["New Name"]
    assert facade.get_book(b2).authors == ["New Name", "Co Author"]
    assert facade.get_book(b3).authors == ["Someone Else"]  # untouched
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_apply_token_mismatch_refuses_and_writes_nothing(
    facade, scratch_library, backup_root, tmp_path
):
    # ARENAME-05: a wrong token is refused; nothing is written or backed up.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Old Name"])

    with pytest.raises(ConfirmationError):
        facade.rename_author("Old Name", "New Name", token="deadbeefdeadbeef")

    assert facade.get_book(b1).authors == ["Old Name"]
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_apply_one_book_failure_reports_failed_others_still_renamed(
    facade, scratch_library, tmp_path, monkeypatch
):
    # ARENAME-06: one book's calibredb failure lands in failed; rest still apply.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Old Name"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["Old Name"], 1)
    plan = facade.rename_author("Old Name", "New Name")
    real_set_metadata = facade._runner.set_metadata

    def _flaky(book_id, fields):
        if book_id == b2:
            raise CalibredbError(["set_metadata"], 1, "boom")
        return real_set_metadata(book_id, fields)

    monkeypatch.setattr(facade._runner, "set_metadata", _flaky)

    applied = facade.rename_author(
        "Old Name", "New Name", token=plan["confirmation_token"]
    )

    applied_ids = {a["book_id"] for a in applied["applied"]}
    failed_ids = {f["book_id"] for f in applied["failed"]}
    assert applied_ids == {b1}
    assert failed_ids == {b2}
    assert len(applied["applied"]) + len(applied["failed"]) == 2
    assert facade.get_book(b1).authors == ["New Name"]
    assert facade.get_book(b2).authors == ["Old Name"]  # unchanged after failure


@pytest.mark.integration
def test_single_book_batch_runs_full_plan_confirm_path(
    facade, scratch_library, backup_root, tmp_path
):
    # Edge case: a degenerate one-book batch is not an error.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Solo Author"])
    plan = facade.rename_author("Solo Author", "Renamed Author")

    applied = facade.rename_author(
        "Solo Author", "Renamed Author", token=plan["confirmation_token"]
    )

    assert applied["applied"] == [{"book_id": b1, "authors": ["Renamed Author"]}]
    assert facade.get_book(b1).authors == ["Renamed Author"]
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_backup_failure_aborts_before_any_set_metadata_write(
    facade, scratch_library, tmp_path, monkeypatch
):
    # Design Risk L-001: the backup must run before the first set_metadata call.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Old Name"])
    plan = facade.rename_author("Old Name", "New Name")
    token = plan["confirmation_token"]

    def _must_not_run(*_a, **_k):
        raise AssertionError("set_metadata ran despite backup failure")

    monkeypatch.setattr(facade._runner, "set_metadata", _must_not_run)

    def _fail_backup(*_a, **_k):
        raise OSError("cannot back up metadata.db; write aborted")

    monkeypatch.setattr(library_module, "backup_metadata_db", _fail_backup)

    with pytest.raises(OSError):
        facade.rename_author("Old Name", "New Name", token=token)

    assert facade.get_book(b1).authors == ["Old Name"]  # unchanged


# ---------------------------------------------------------- merge / co-author


@pytest.mark.integration
def test_merge_onto_existing_name_dedupes_and_consumes_old_name(
    facade, scratch_library, tmp_path
):
    # ARENAME-07 (Independent Test 2): merge onto an existing name dedupes
    # in-book; re-running the same rename afterward is rejected as
    # "author not found" because old_name is fully consumed.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["Old", "New"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["X", "Old"], 1)
    plan = facade.rename_author("Old", "New")

    applied = facade.rename_author("Old", "New", token=plan["confirmation_token"])

    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert by_id[b1]["authors"] == ["New"]
    assert by_id[b2]["authors"] == ["X", "New"]
    assert facade.get_book(b1).authors == ["New"]
    assert facade.get_book(b2).authors == ["X", "New"]

    with pytest.raises(InvalidInputError):
        facade.rename_author("Old", "New")
