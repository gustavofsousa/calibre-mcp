"""Integration tests for ``CalibreLibrary.rename_series`` (ORGN-04, SRENAME-01..08).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` (add + set_metadata series/series_index) so the backup
dir starts empty and the batch's own backup is observable. The real library
has 0 books in any series (series_unused) — scratch seeding is required here.

Series is a SINGLE-valued field: unlike tags/authors there is no per-book
list to resolve or dedupe. The one field-specific requirement the siblings
never faced is ``series_index`` preservation — the apply writes the
``series`` field ONLY, so each book's position survives the rename.

SRENAME-01: plan (no token) returns a per-book diff (series current->proposed,
    with series_index shown unchanged) + one token, no write.
SRENAME-02: old_series matching no book is rejected before any backup.
SRENAME-03: blank new_series or new_series == old_series is rejected before
    any backup.
SRENAME-04: apply (token) backs up once, applies via set_metadata (series
    field only), returns backup path.
SRENAME-05: a mismatched token is refused, nothing written.
SRENAME-06: one book's failure lands in failed; the rest still apply.
SRENAME-07: series_index is preserved across the rename; merge-onto-existing
    is allowed with each book keeping its own index.
SRENAME-08: applied entries re-read the resulting series + series_index.
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
    series: str,
    series_index: float,
    index: int = 0,
) -> int:
    """Add a book directly via the runner and set its series (no facade backup)."""
    runner = CalibredbRunner(scratch_library)
    result = runner.add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    runner.set_metadata(
        result.book_id, {"series": series, "series_index": series_index}
    )
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# --------------------------------------------------------------------- plan


@pytest.mark.integration
def test_plan_lists_affected_books_with_series_diffs_without_writing(
    facade, scratch_library, tmp_path
):
    # SRENAME-01 (Independent Test 1): both "Old" books listed with unchanged
    # indices, "Other" book untouched, nothing written.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 2.0)
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", "Old", 7.5, 1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", "Other", 1.0, 2)

    plan = facade.rename_series("Old", "New")

    assert plan["status"] == "plan"
    by_id = {d["book_id"]: d for d in plan["diffs"]}
    assert set(by_id) == {b1, b2}  # b3 not affected
    assert by_id[b1]["diff"]["series"]["proposed"] == "New"
    assert by_id[b1]["series_index"] == 2.0
    assert by_id[b2]["diff"]["series"]["proposed"] == "New"
    assert by_id[b2]["series_index"] == 7.5
    assert plan["confirmation_token"]
    # nothing was written
    assert facade.get_book(b1).series == "Old"
    assert facade.get_book(b2).series == "Old"
    assert facade.get_book(b3).series == "Other"


@pytest.mark.integration
def test_plan_rejects_series_not_found_before_backup(facade, backup_root):
    # SRENAME-02: no book carries old_series -> rejected before any backup.
    with pytest.raises(InvalidInputError) as excinfo:
        facade.rename_series("no-such-series", "New")

    assert "not found" in str(excinfo.value).lower()
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_new_series_blank_or_equal_to_old_rejected_before_backup(
    facade, scratch_library, tmp_path, backup_root
):
    # SRENAME-03: blank new_series, or new_series == old_series, rejected
    # before backup.
    _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 1.0)

    with pytest.raises(InvalidInputError):
        facade.rename_series("Old", "")
    with pytest.raises(InvalidInputError):
        facade.rename_series("Old", "   ")
    with pytest.raises(InvalidInputError):
        facade.rename_series("Old", "Old")
    assert _snapshots(backup_root) == []


# -------------------------------------------------------------------- apply


@pytest.mark.integration
def test_apply_writes_new_series_backs_up_once_and_preserves_index(
    facade, scratch_library, backup_root, tmp_path
):
    # SRENAME-04/07/08 (star assertion): apply backs up once, writes the new
    # series name, and each book's series_index survives unchanged
    # (fractional 7.5 included) -- the one footgun this feature exists to
    # avoid.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 2.0)
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", "Old", 7.5, 1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", "Other", 1.0, 2)
    plan = facade.rename_series("Old", "New")

    applied = facade.rename_series(
        "Old", "New", token=plan["confirmation_token"]
    )

    assert applied["status"] == "renamed"
    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert by_id[b1] == {"book_id": b1, "series": "New", "series_index": 2.0}
    assert by_id[b2] == {"book_id": b2, "series": "New", "series_index": 7.5}
    assert applied["failed"] == []
    assert facade.get_book(b1).series == "New"
    assert facade.get_book(b1).series_index == 2.0
    assert facade.get_book(b2).series == "New"
    assert facade.get_book(b2).series_index == 7.5  # preserved, not reset
    assert facade.get_book(b3).series == "Other"  # untouched
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_apply_token_mismatch_refuses_and_writes_nothing(
    facade, scratch_library, backup_root, tmp_path
):
    # SRENAME-05: a wrong token is refused; nothing is written or backed up.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 1.0)

    with pytest.raises(ConfirmationError):
        facade.rename_series("Old", "New", token="deadbeefdeadbeef")

    assert facade.get_book(b1).series == "Old"
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_apply_one_book_failure_reports_failed_others_still_renamed(
    facade, scratch_library, tmp_path, monkeypatch
):
    # SRENAME-06: one book's calibredb failure lands in failed; rest still apply.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 1.0)
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", "Old", 2.0, 1)
    plan = facade.rename_series("Old", "New")
    real_set_metadata = facade._runner.set_metadata

    def _flaky(book_id, fields):
        if book_id == b2:
            raise CalibredbError(["set_metadata"], 1, "boom")
        return real_set_metadata(book_id, fields)

    monkeypatch.setattr(facade._runner, "set_metadata", _flaky)

    applied = facade.rename_series(
        "Old", "New", token=plan["confirmation_token"]
    )

    applied_ids = {a["book_id"] for a in applied["applied"]}
    failed_ids = {f["book_id"] for f in applied["failed"]}
    assert applied_ids == {b1}
    assert failed_ids == {b2}
    assert len(applied["applied"]) + len(applied["failed"]) == 2
    assert facade.get_book(b1).series == "New"
    assert facade.get_book(b2).series == "Old"  # unchanged after failure


@pytest.mark.integration
def test_single_book_batch_runs_full_plan_confirm_path(
    facade, scratch_library, backup_root, tmp_path
):
    # Edge case: a degenerate one-book batch is not an error.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Solo", 3.0)
    plan = facade.rename_series("Solo", "Renamed")

    applied = facade.rename_series(
        "Solo", "Renamed", token=plan["confirmation_token"]
    )

    assert applied["applied"] == [
        {"book_id": b1, "series": "Renamed", "series_index": 3.0}
    ]
    assert facade.get_book(b1).series == "Renamed"
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_backup_failure_aborts_before_any_set_metadata_write(
    facade, scratch_library, tmp_path, monkeypatch
):
    # Design Risk L-001: the backup must run before the first set_metadata call.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 1.0)
    plan = facade.rename_series("Old", "New")
    token = plan["confirmation_token"]

    def _must_not_run(*_a, **_k):
        raise AssertionError("set_metadata ran despite backup failure")

    monkeypatch.setattr(facade._runner, "set_metadata", _must_not_run)

    def _fail_backup(*_a, **_k):
        raise OSError("cannot back up metadata.db; write aborted")

    monkeypatch.setattr(library_module, "backup_metadata_db", _fail_backup)

    with pytest.raises(OSError):
        facade.rename_series("Old", "New", token=token)

    assert facade.get_book(b1).series == "Old"  # unchanged


# --------------------------------------------------------------- merge / index


@pytest.mark.integration
def test_merge_onto_existing_series_preserves_each_books_own_index(
    facade, scratch_library, tmp_path
):
    # SRENAME-07 (Independent Test 2): merging onto an existing series keeps
    # each book's own index (no renumbering); re-running afterward is
    # rejected as "series not found" because old_series is fully consumed.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", "Old", 3.0)
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", "New", 1.0, 1)
    plan = facade.rename_series("Old", "New")

    applied = facade.rename_series("Old", "New", token=plan["confirmation_token"])

    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert by_id[b1] == {"book_id": b1, "series": "New", "series_index": 3.0}
    assert facade.get_book(b1).series == "New"
    assert facade.get_book(b1).series_index == 3.0
    assert facade.get_book(b2).series == "New"
    assert facade.get_book(b2).series_index == 1.0  # untouched, no collision fix

    with pytest.raises(InvalidInputError):
        facade.rename_series("Old", "New")
