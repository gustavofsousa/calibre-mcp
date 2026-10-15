"""Integration tests for ``CalibreLibrary.rename_tag`` (ORGN-02, TRENAME-01..08).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` (add + set_metadata tags) so the backup dir starts empty
and the batch's own backup is observable.

Tags are a SET: Calibre re-reads them alphabetically (``ORDER BY t.name``), so
apply/re-read assertions compare tag *sets*, not positional order (spec
TRENAME-08 note).

TRENAME-01: plan (no token) returns a per-book resolved diff + one token, no write.
TRENAME-02: old_tag matching no tag is rejected before any backup.
TRENAME-03: blank new_tag or new_tag == old_tag is rejected before any backup.
TRENAME-04: apply (token) backs up once, applies via set_metadata, returns backup path.
TRENAME-05: a mismatched token is refused, nothing written.
TRENAME-06: one book's failure lands in failed; the rest still apply.
TRENAME-07: other-tag-safe replace + in-book dedupe/merge onto an existing tag.
TRENAME-08: applied entries re-read the resulting tags.
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
    tags: list[str],
    index: int = 0,
) -> int:
    """Add a book directly via the runner and set its tags (no facade backup)."""
    runner = CalibredbRunner(scratch_library)
    result = runner.add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    runner.set_metadata(result.book_id, {"tags": tags})
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# --------------------------------------------------------------------- plan


@pytest.mark.integration
def test_plan_lists_affected_books_with_resolved_diffs_without_writing(
    facade, scratch_library, tmp_path
):
    # TRENAME-01 (Independent Test 1): other tag preserved, third book untouched.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["old-tag"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["old-tag", "keep"], 1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", ["unrelated"], 2)

    plan = facade.rename_tag("old-tag", "new-tag")

    assert plan["status"] == "plan"
    by_id = {d["book_id"]: d for d in plan["diffs"]}
    assert set(by_id) == {b1, b2}  # b3 not affected
    assert set(by_id[b1]["diff"]["tags"]["proposed"]) == {"new-tag"}
    assert set(by_id[b2]["diff"]["tags"]["proposed"]) == {"new-tag", "keep"}
    assert plan["confirmation_token"]
    # nothing was written
    assert facade.get_book(b1).tags == ["old-tag"]
    assert set(facade.get_book(b2).tags) == {"old-tag", "keep"}
    assert facade.get_book(b3).tags == ["unrelated"]


@pytest.mark.integration
def test_plan_rejects_tag_not_found_before_backup(facade, backup_root):
    # TRENAME-02: no book carries old_tag -> rejected before any backup.
    with pytest.raises(InvalidInputError) as excinfo:
        facade.rename_tag("no-such-tag", "new-tag")

    assert "not found" in str(excinfo.value).lower()
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_new_tag_blank_or_equal_to_old_rejected_before_backup(
    facade, scratch_library, tmp_path, backup_root
):
    # TRENAME-03: blank new_tag, or new_tag == old_tag, rejected before backup.
    _seed_book(scratch_library, tmp_path, "b1.epub", ["old-tag"])

    with pytest.raises(InvalidInputError):
        facade.rename_tag("old-tag", "")
    with pytest.raises(InvalidInputError):
        facade.rename_tag("old-tag", "   ")
    with pytest.raises(InvalidInputError):
        facade.rename_tag("old-tag", "old-tag")
    assert _snapshots(backup_root) == []


# -------------------------------------------------------------------- apply


@pytest.mark.integration
def test_apply_writes_resolved_tags_backs_up_once_and_rereads(
    facade, scratch_library, backup_root, tmp_path
):
    # TRENAME-04/08: apply backs up once, writes each resolved set, re-reads.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["old-tag"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["old-tag", "keep"], 1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", ["unrelated"], 2)
    plan = facade.rename_tag("old-tag", "new-tag")

    applied = facade.rename_tag(
        "old-tag", "new-tag", token=plan["confirmation_token"]
    )

    assert applied["status"] == "renamed"
    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert set(by_id[b1]["tags"]) == {"new-tag"}
    assert set(by_id[b2]["tags"]) == {"new-tag", "keep"}
    assert applied["failed"] == []
    assert set(facade.get_book(b1).tags) == {"new-tag"}
    assert set(facade.get_book(b2).tags) == {"new-tag", "keep"}
    assert facade.get_book(b3).tags == ["unrelated"]  # untouched
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_apply_token_mismatch_refuses_and_writes_nothing(
    facade, scratch_library, backup_root, tmp_path
):
    # TRENAME-05: a wrong token is refused; nothing is written or backed up.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["old-tag"])

    with pytest.raises(ConfirmationError):
        facade.rename_tag("old-tag", "new-tag", token="deadbeefdeadbeef")

    assert facade.get_book(b1).tags == ["old-tag"]
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_apply_one_book_failure_reports_failed_others_still_renamed(
    facade, scratch_library, tmp_path, monkeypatch
):
    # TRENAME-06: one book's calibredb failure lands in failed; rest still apply.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["old-tag"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["old-tag"], 1)
    plan = facade.rename_tag("old-tag", "new-tag")
    real_set_metadata = facade._runner.set_metadata

    def _flaky(book_id, fields):
        if book_id == b2:
            raise CalibredbError(["set_metadata"], 1, "boom")
        return real_set_metadata(book_id, fields)

    monkeypatch.setattr(facade._runner, "set_metadata", _flaky)

    applied = facade.rename_tag(
        "old-tag", "new-tag", token=plan["confirmation_token"]
    )

    applied_ids = {a["book_id"] for a in applied["applied"]}
    failed_ids = {f["book_id"] for f in applied["failed"]}
    assert applied_ids == {b1}
    assert failed_ids == {b2}
    assert len(applied["applied"]) + len(applied["failed"]) == 2
    assert set(facade.get_book(b1).tags) == {"new-tag"}
    assert facade.get_book(b2).tags == ["old-tag"]  # unchanged after failure


@pytest.mark.integration
def test_single_book_batch_runs_full_plan_confirm_path(
    facade, scratch_library, backup_root, tmp_path
):
    # Edge case: a degenerate one-book batch is not an error.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["solo"])
    plan = facade.rename_tag("solo", "renamed")

    applied = facade.rename_tag("solo", "renamed", token=plan["confirmation_token"])

    assert applied["applied"] == [{"book_id": b1, "tags": ["renamed"]}]
    assert facade.get_book(b1).tags == ["renamed"]
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_backup_failure_aborts_before_any_set_metadata_write(
    facade, scratch_library, tmp_path, monkeypatch
):
    # Design Risk L-001: the backup must run before the first set_metadata call.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["old-tag"])
    plan = facade.rename_tag("old-tag", "new-tag")
    token = plan["confirmation_token"]

    def _must_not_run(*_a, **_k):
        raise AssertionError("set_metadata ran despite backup failure")

    monkeypatch.setattr(facade._runner, "set_metadata", _must_not_run)

    def _fail_backup(*_a, **_k):
        raise OSError("cannot back up metadata.db; write aborted")

    monkeypatch.setattr(library_module, "backup_metadata_db", _fail_backup)

    with pytest.raises(OSError):
        facade.rename_tag("old-tag", "new-tag", token=token)

    assert facade.get_book(b1).tags == ["old-tag"]  # unchanged


# ------------------------------------------------------------ merge / other-tag


@pytest.mark.integration
def test_merge_onto_existing_tag_dedupes_and_consumes_old_tag(
    facade, scratch_library, tmp_path
):
    # TRENAME-07 (Independent Test 2): merge onto an existing tag dedupes
    # in-book; re-running the same rename afterward is rejected as "tag not
    # found" because old_tag is fully consumed.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", ["old", "new"])
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", ["x", "old"], 1)
    plan = facade.rename_tag("old", "new")

    applied = facade.rename_tag("old", "new", token=plan["confirmation_token"])

    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert set(by_id[b1]["tags"]) == {"new"}
    assert set(by_id[b2]["tags"]) == {"x", "new"}
    assert set(facade.get_book(b1).tags) == {"new"}
    assert set(facade.get_book(b2).tags) == {"x", "new"}

    with pytest.raises(InvalidInputError):
        facade.rename_tag("old", "new")
