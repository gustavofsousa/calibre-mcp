"""Integration tests for ``CalibreLibrary.merge_duplicate_group`` (ORGN-03,
MERGE-01..08).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` (add + set_metadata / add_format) so the backup dir starts
empty and the batch's own backup is observable.

MERGE-01: plan (no token) returns per-loser format split + one token, no write.
MERGE-02: an unknown survivor or loser id is rejected before any backup.
MERGE-03: empty/self/duplicate loser_ids are rejected before any backup.
MERGE-04: apply (token) backs up once, attaches formats, recoverably removes.
MERGE-05: a mismatched token is refused, nothing written.
MERGE-06: an attach failure keeps that loser (not removed); others still merge.
MERGE-07: a format already on the survivor is not duplicated (reported only).
MERGE-08: survivor formats are re-read; each merged loser reports a trash location.
Edge case: a single-loser batch still runs the full plan->confirm path.
Design Risk L-001: the backup runs before the first mutation (attach/remove).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp import library as library_module
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import BookNotFoundError, ConfirmationError, InvalidInputError
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
    index: int = 0,
) -> int:
    """Add a book directly via the runner (no facade backup)."""
    runner = CalibredbRunner(scratch_library)
    result = runner.add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# --------------------------------------------------------------------- plan


@pytest.mark.integration
def test_plan_lists_per_loser_format_split_without_writing(
    facade, scratch_library, tmp_path
):
    # MERGE-01/07 (Independent Test 1): overlap reported, unique format to-add.
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_id = _seed_book(scratch_library, tmp_path, "loser.epub", 1)
    # loser's own EPUB overlaps the survivor's; give the loser a second format.
    loser_epub = next(iter(facade._reader.format_files(loser_id).values()))
    fake_pdf = tmp_path / "extra.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    facade._runner.add_format(loser_id, fake_pdf)

    plan = facade.merge_duplicate_group(survivor_id, [loser_id])

    assert plan["status"] == "plan"
    assert plan["survivor_id"] == survivor_id
    assert plan["recoverable"] is True
    entry = plan["losers"][0]
    assert entry["book_id"] == loser_id
    assert entry["formats_to_add"] == ["PDF"]
    assert entry["formats_already_present"] == ["EPUB"]
    assert plan["confirmation_token"]
    # nothing written: loser still present, survivor formats unchanged
    facade.get_book(loser_id)
    assert facade.get_book(survivor_id).formats == ["EPUB"]
    assert loser_epub.exists()


@pytest.mark.integration
def test_plan_rejects_unknown_survivor_or_loser_before_backup(
    facade, scratch_library, tmp_path, backup_root
):
    # MERGE-02: an id matching no book is rejected before any backup.
    real_id = _seed_book(scratch_library, tmp_path, "b1.epub")

    with pytest.raises(BookNotFoundError):
        facade.merge_duplicate_group(999999, [real_id])
    with pytest.raises(BookNotFoundError):
        facade.merge_duplicate_group(real_id, [999999])
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_plan_rejects_invalid_loser_ids_before_backup(
    facade, scratch_library, tmp_path, backup_root
):
    # MERGE-03: empty, self-referential, or duplicate loser_ids all rejected.
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_id = _seed_book(scratch_library, tmp_path, "loser.epub", 1)

    with pytest.raises(InvalidInputError):
        facade.merge_duplicate_group(survivor_id, [])
    with pytest.raises(InvalidInputError):
        facade.merge_duplicate_group(survivor_id, [survivor_id])
    with pytest.raises(InvalidInputError):
        facade.merge_duplicate_group(survivor_id, [loser_id, loser_id])
    assert _snapshots(backup_root) == []


# -------------------------------------------------------------------- apply


@pytest.mark.integration
def test_apply_unions_formats_backs_up_once_and_removes_losers(
    facade, scratch_library, backup_root, tmp_path
):
    # MERGE-04/08: apply backs up once, attaches unique formats, removes losers.
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_id = _seed_book(scratch_library, tmp_path, "loser.epub", 1)
    fake_pdf = tmp_path / "extra.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    facade._runner.add_format(loser_id, fake_pdf)
    plan = facade.merge_duplicate_group(survivor_id, [loser_id])

    result = facade.merge_duplicate_group(
        survivor_id, [loser_id], token=plan["confirmation_token"]
    )

    assert result["status"] == "merged"
    assert set(result["survivor_formats"]) == {"EPUB", "PDF"}
    assert result["merged"] == [
        {
            "loser_id": loser_id,
            "formats_added": ["PDF"],
            "trash_location": result["merged"][0]["trash_location"],
        }
    ]
    assert result["failed"] == []
    trash_dir = Path(result["merged"][0]["trash_location"])
    assert trash_dir.is_dir() and any(trash_dir.iterdir())
    assert len(_snapshots(backup_root)) == 1
    with pytest.raises(BookNotFoundError):
        facade.get_book(loser_id)  # gone
    assert set(facade.get_book(survivor_id).formats) == {"EPUB", "PDF"}


@pytest.mark.integration
def test_apply_token_mismatch_refuses_and_writes_nothing(
    facade, scratch_library, backup_root, tmp_path
):
    # MERGE-05: a wrong token is refused; nothing written or backed up.
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_id = _seed_book(scratch_library, tmp_path, "loser.epub", 1)

    with pytest.raises(ConfirmationError):
        facade.merge_duplicate_group(
            survivor_id, [loser_id], token="deadbeefdeadbeef"
        )

    facade.get_book(loser_id)  # still present
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_apply_attach_failure_keeps_loser_others_still_merge(
    facade, scratch_library, tmp_path
):
    # MERGE-06: one loser's format is missing on disk (attach-time failure) ->
    # that loser is NOT removed and lands in failed; the other loser still
    # merges. Mirrors the design's documented risk (missing on-disk format).
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_ok = _seed_book(scratch_library, tmp_path, "loser_ok.epub", 1)
    loser_bad = _seed_book(scratch_library, tmp_path, "loser_bad.epub", 2)
    plan = facade.merge_duplicate_group(survivor_id, [loser_ok, loser_bad])
    # Delete loser_bad's on-disk format file while metadata.db still
    # references it -- format_files() raises InvalidInputError for it.
    bad_file = next(iter(facade._reader.format_files(loser_bad).values()))
    bad_file.unlink()

    result = facade.merge_duplicate_group(
        survivor_id, [loser_ok, loser_bad], token=plan["confirmation_token"]
    )

    merged_ids = {m["loser_id"] for m in result["merged"]}
    failed_ids = {f["loser_id"] for f in result["failed"]}
    assert merged_ids == {loser_ok}
    assert failed_ids == {loser_bad}
    assert len(result["merged"]) + len(result["failed"]) == 2
    with pytest.raises(BookNotFoundError):
        facade.get_book(loser_ok)  # merged, removed
    facade.get_book(loser_bad)  # NOT removed after failed attach


@pytest.mark.integration
def test_single_loser_batch_runs_full_plan_confirm_path(
    facade, scratch_library, backup_root, tmp_path
):
    # Edge case: a degenerate one-loser batch is not an error.
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_id = _seed_book(scratch_library, tmp_path, "loser.epub", 1)
    plan = facade.merge_duplicate_group(survivor_id, [loser_id])

    result = facade.merge_duplicate_group(
        survivor_id, [loser_id], token=plan["confirmation_token"]
    )

    assert result["merged"][0]["loser_id"] == loser_id
    assert result["failed"] == []
    with pytest.raises(BookNotFoundError):
        facade.get_book(loser_id)
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_backup_failure_aborts_before_any_mutation(
    facade, scratch_library, tmp_path, monkeypatch
):
    # Design Risk L-001: the backup must run before the first attach/remove.
    survivor_id = _seed_book(scratch_library, tmp_path, "survivor.epub")
    loser_id = _seed_book(scratch_library, tmp_path, "loser.epub", 1)
    plan = facade.merge_duplicate_group(survivor_id, [loser_id])
    token = plan["confirmation_token"]

    def _must_not_run(*_a, **_k):
        raise AssertionError("mutation ran despite backup failure")

    monkeypatch.setattr(facade._runner, "add_format", _must_not_run)
    monkeypatch.setattr(facade._runner, "remove", _must_not_run)

    def _fail_backup(*_a, **_k):
        raise OSError("cannot back up metadata.db; write aborted")

    monkeypatch.setattr(library_module, "backup_metadata_db", _fail_backup)

    with pytest.raises(OSError):
        facade.merge_duplicate_group(survivor_id, [loser_id], token=token)

    facade.get_book(loser_id)  # unchanged, still present
