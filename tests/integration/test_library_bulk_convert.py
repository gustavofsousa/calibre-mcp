"""Integration tests for ``CalibreLibrary.convert_book_bulk`` (BULK-02, T2).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` so the backup dir starts empty and the batch's own single
backup is observable.

BCONV-01: additive convert; exactly one metadata.db backup before the batch,
          returned as ``backup``; no confirmation token.
BCONV-02: a per-book failure (vanished id, bogus source) lands in ``failed``
          and never aborts the batch or fakes an "all succeeded".
BCONV-03: a benign no-op (already has target / no source) lands in ``skipped``,
          not ``failed``.
BCONV-04: a converted book re-reads its resulting format list into ``converted``.
BCONV-05: invariant converted + skipped + failed == len(book_ids).
BCONV-06: invalid input (bad target, empty/duplicate/non-int/bool ids, over the
          50-book cap) is rejected before any backup or conversion.
Edge cases: single-id batch, all-skipped batch, exactly-50 accepted / 51 rejected.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import InvalidInputError
from calibre_mcp.library import CalibreLibrary
from sample_books import sample_epub_sources


def _sample_epub(tmp_path: Path, name: str, index: int = 0) -> Path:
    # ``index`` picks a distinct source file so seeded books are never
    # byte-identical (calibredb would flag a byte-identical add as a duplicate
    # and refuse to import it).
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
    scratch_library: Path, tmp_path: Path, name: str, index: int = 0
) -> int:
    """Add a book directly via the runner (no facade backup) and return its id."""
    result = CalibredbRunner(scratch_library).add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# ------------------------------------------------------------- happy path (T1)


@pytest.mark.integration
def test_all_succeed_adds_target_keeps_existing_and_takes_one_backup(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # Independent Test 1 (BCONV-01/04): 3 convertible books -> each reads back an
    # added PDF with EPUB preserved; exactly one backup; 3 converted entries.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", index=0)
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", index=1)
    b3 = _seed_book(scratch_library, tmp_path, "b3.epub", index=2)

    result = facade.convert_book_bulk([b3, b1, b2], "pdf")

    assert result["status"] == "converted"
    assert result["target_format"] == "pdf"
    assert result["skipped"] == []
    assert result["failed"] == []
    by_id = {c["book_id"]: c for c in result["converted"]}
    assert set(by_id) == {b1, b2, b3}
    # Spec edge case: reporting order is ascending book_id (deterministic),
    # regardless of the input order ([b3, b1, b2] above).
    assert [c["book_id"] for c in result["converted"]] == sorted([b1, b2, b3])
    for book_id in (b1, b2, b3):
        assert set(by_id[book_id]["formats"]) == {"EPUB", "PDF"}  # additive, re-read
        assert set(facade.get_book(book_id).formats) == {"EPUB", "PDF"}  # persisted
    assert len(_snapshots(backup_root)) == 1  # BCONV-01: exactly one backup
    assert result["backup"] == str(_snapshots(backup_root)[0])


# --------------------------------------------------- mixed batch + invariant


@pytest.mark.integration
def test_mixed_batch_routes_skipped_failed_converted_and_holds_invariant(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # Independent Test 2 (BCONV-02/03/04/05): a book already having the target
    # PDF -> skipped (reason names the format), a missing id -> failed, and a
    # third EPUB-only book -> actually converted to PDF. The three-bucket
    # invariant holds and exactly one backup covers the batch.
    already_pdf = _seed_book(scratch_library, tmp_path, "haspdf.epub", index=0)
    facade.convert_book(already_pdf, "pdf")  # now has EPUB + PDF (own backup)
    to_convert = _seed_book(scratch_library, tmp_path, "conv.epub", index=1)
    missing = 999999
    book_ids = [already_pdf, to_convert, missing]
    backups_before = len(_snapshots(backup_root))  # setup convert already made one

    result = facade.convert_book_bulk(book_ids, "pdf")

    assert {c["book_id"] for c in result["converted"]} == {to_convert}
    assert set(result["converted"][0]["formats"]) == {"EPUB", "PDF"}  # re-read
    assert {s["book_id"] for s in result["skipped"]} == {already_pdf}
    assert "PDF" in result["skipped"][0]["reason"]  # reason names the format
    assert {f["book_id"] for f in result["failed"]} == {missing}
    assert (
        len(result["converted"]) + len(result["skipped"]) + len(result["failed"])
        == len(book_ids)  # BCONV-05 invariant
    )
    assert len(_snapshots(backup_root)) == backups_before + 1  # bulk: one backup


# ----------------------------------------------------------------- edge cases


@pytest.mark.integration
def test_single_id_batch_runs_the_full_convert_path(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # Edge case: a degenerate one-book batch is not an error.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", index=0)

    result = facade.convert_book_bulk([b1], "pdf")

    assert result["converted"] == [
        {"book_id": b1, "formats": facade.get_book(b1).formats}
    ]
    assert set(facade.get_book(b1).formats) == {"EPUB", "PDF"}
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_all_skipped_batch_still_takes_one_backup_no_conversions(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # Edge case: every book already has the target -> all skipped, empty
    # converted/failed, and the one backup is still present (BCONV-01/03).
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", index=0)
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", index=1)

    result = facade.convert_book_bulk([b1, b2], "epub")

    assert result["converted"] == []
    assert result["failed"] == []
    assert {s["book_id"] for s in result["skipped"]} == {b1, b2}
    assert len(_snapshots(backup_root)) == 1  # unconditional pre-loop backup


@pytest.mark.integration
def test_no_source_book_is_skipped_not_failed(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path, monkeypatch
):
    # BCONV-03: a book with zero source files is a benign skip, not a failure.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", index=0)
    monkeypatch.setattr(facade._reader, "format_files", lambda _id: {})

    result = facade.convert_book_bulk([b1], "pdf")

    assert result["converted"] == []
    assert result["failed"] == []
    assert result["skipped"][0]["book_id"] == b1
    assert "no file to convert from" in result["skipped"][0]["reason"]


@pytest.mark.integration
def test_bogus_source_book_lands_in_failed_batch_continues(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # BCONV-02: a corrupt source raises inside the loop -> that book is failed,
    # the other book still converts; never a fake "all succeeded".
    bogus = _seed_book(scratch_library, tmp_path, "bogus.epub", index=0)
    facade._reader.format_files(bogus)["EPUB"].write_bytes(b"not a real epub")
    good = _seed_book(scratch_library, tmp_path, "good.epub", index=1)

    result = facade.convert_book_bulk([bogus, good], "pdf")

    assert {f["book_id"] for f in result["failed"]} == {bogus}
    assert {c["book_id"] for c in result["converted"]} == {good}
    assert set(facade.get_book(good).formats) == {"EPUB", "PDF"}
    assert facade.get_book(bogus).formats == ["EPUB"]  # nothing added to the failed one


# ------------------------------------------------------------- BCONV-06 gate


@pytest.mark.integration
def test_rejects_unsupported_target_before_any_backup(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", index=0)

    with pytest.raises(InvalidInputError) as excinfo:
        facade.convert_book_bulk([b1], "bogus")

    assert "bogus" in str(excinfo.value)
    assert _snapshots(backup_root) == []  # rejected before any backup


@pytest.mark.integration
def test_rejects_empty_book_ids_before_any_backup(
    facade: CalibreLibrary, backup_root: Path
):
    with pytest.raises(InvalidInputError):
        facade.convert_book_bulk([], "epub")

    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_rejects_duplicate_book_ids(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", index=0)
    with pytest.raises(InvalidInputError):
        facade.convert_book_bulk([b1, b1], "pdf")


@pytest.mark.integration
def test_rejects_non_integer_book_id(facade: CalibreLibrary):
    with pytest.raises(InvalidInputError):
        facade.convert_book_bulk([1, "2"], "pdf")  # type: ignore[list-item]


@pytest.mark.integration
def test_rejects_bool_as_book_id(facade: CalibreLibrary):
    # bool is an int subclass in Python; must be explicitly rejected.
    with pytest.raises(InvalidInputError):
        facade.convert_book_bulk([1, True], "pdf")


@pytest.mark.integration
def test_rejects_over_cap_51_before_any_backup(
    facade: CalibreLibrary, backup_root: Path
):
    # BCONV-06 edge: 51 ids exceeds the 50-book cap -> rejected before backup.
    with pytest.raises(InvalidInputError) as excinfo:
        facade.convert_book_bulk(list(range(1, 52)), "epub")

    assert "50" in str(excinfo.value)
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_validator_accepts_exactly_50_and_normalizes_target():
    # BCONV-06 edge: exactly 50 ids is accepted; the target is lowercased. Tested
    # through the pure validator so 50 real conversions are not run.
    assert (
        CalibreLibrary._validate_bulk_convert_input(list(range(1, 51)), "EPUB")
        == "epub"
    )
