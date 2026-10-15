"""Integration tests for CalibredbRunner — derived from SEARCH-01, EDIT-02, ADD, REM-02.

ALL writes go to a per-test ``scratch_library`` (temp dir). They NEVER touch the
real library — the non-negotiable test-safety rule.

SEARCH-01: search resolves matching ids; no matches -> empty list.
EDIT-02: set_metadata applies fields (list fields comma-joined).
ADD-01: add parses the new id from stdout.
ADD-03: add surfaces the duplicate outcome rather than a fake id.
REM-02/AD-009: remove uses the recycle bin (never --permanent).
Error mapping: missing binary -> CalibredbNotFoundError; lock text ->
LibraryLockedError; other non-zero -> CalibredbError.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.errors import (
    CalibredbError,
    CalibredbNotFoundError,
    LibraryLockedError,
)
from calibre_mcp.sqlite_reader import SqliteReader
from sample_books import sample_epub_sources


def _sample_epub(tmp_path: Path) -> Path:
    """Copy one synthetic sample .epub into a temp path."""
    sources = sample_epub_sources()
    dest = tmp_path / "sample.epub"
    shutil.copy2(sources[0], dest)
    return dest


@pytest.fixture
def runner(scratch_library: Path) -> CalibredbRunner:
    return CalibredbRunner(scratch_library)


@pytest.mark.integration
def test_add_returns_new_id(runner, scratch_library, tmp_path):
    # ADD-01: the new id is parsed from calibredb stdout, not guessed.
    result = runner.add(_sample_epub(tmp_path))

    assert result.duplicate is False
    assert isinstance(result.book_id, int)
    # the id really exists in the library
    book = SqliteReader(scratch_library / "metadata.db", scratch_library).get_book(
        result.book_id
    )
    assert book.id == result.book_id


@pytest.mark.integration
def test_add_duplicate_surfaces_outcome(runner, tmp_path):
    # ADD-03: re-adding the same file is reported as a duplicate, not a new id.
    epub = _sample_epub(tmp_path)
    runner.add(epub)

    second = runner.add(epub)

    assert second.duplicate is True
    assert second.book_id is None


@pytest.mark.integration
def test_search_returns_matching_ids(runner, tmp_path):
    # SEARCH-01: search resolves the added book's id.
    result = runner.add(_sample_epub(tmp_path))

    ids = runner.search("format:epub")

    assert result.book_id in ids


@pytest.mark.integration
def test_search_no_match_returns_empty_list(runner, tmp_path):
    # SEARCH-01: a non-matching query is an empty result, not an error.
    runner.add(_sample_epub(tmp_path))

    assert runner.search("title:zzz_no_such_title_zzz") == []


@pytest.mark.integration
def test_set_metadata_applies_list_field(runner, scratch_library, tmp_path):
    # EDIT-02: list fields are comma-joined and applied.
    result = runner.add(_sample_epub(tmp_path))

    runner.set_metadata(result.book_id, {"tags": ["scifi", "classic"]})

    book = SqliteReader(scratch_library / "metadata.db", scratch_library).get_book(
        result.book_id
    )
    assert set(book.tags) == {"scifi", "classic"}


@pytest.mark.integration
def test_set_metadata_authors_stay_distinct_not_mashed(
    runner, scratch_library, tmp_path
):
    # AD-022: authors join with " & ", not "," -- a "," join mashes two
    # co-authors into a single author entity ("A|B") instead of two.
    result = runner.add(_sample_epub(tmp_path))

    runner.set_metadata(result.book_id, {"authors": ["Author One", "Author Two"]})

    book = SqliteReader(scratch_library / "metadata.db", scratch_library).get_book(
        result.book_id
    )
    assert book.authors == ["Author One", "Author Two"]


@pytest.mark.integration
@pytest.mark.parametrize("rating", [2, 7, 8, 10])
def test_set_metadata_rating_round_trips_on_the_0_to_10_scale(
    runner, scratch_library, tmp_path, rating
):
    # EDIT-07: the tool contract and the reader both speak Calibre's stored 0-10
    # scale, but `calibredb set_metadata --field rating:N` takes STARS (0-5) and
    # stores N*2 -- passing the 0-10 value through doubled it (8 -> 10).
    result = runner.add(_sample_epub(tmp_path))

    runner.set_metadata(result.book_id, {"rating": rating})

    book = SqliteReader(scratch_library / "metadata.db", scratch_library).get_book(
        result.book_id
    )
    assert book.rating == rating


@pytest.mark.integration
def test_remove_deletes_book_from_library(runner, scratch_library, tmp_path):
    # REM-02: after remove, the book is gone from the library.
    result = runner.add(_sample_epub(tmp_path))

    runner.remove(result.book_id)

    assert result.book_id not in runner.search("format:epub")


@pytest.mark.integration
def test_add_format_keeps_existing_and_adds_new(runner, scratch_library, tmp_path):
    # CONV-01: add_format is additive — both old and new formats are present.
    result = runner.add(_sample_epub(tmp_path))
    pdf_path = tmp_path / "converted.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

    runner.add_format(result.book_id, pdf_path)

    book = SqliteReader(scratch_library / "metadata.db", scratch_library).get_book(
        result.book_id
    )
    assert set(book.formats) == {"EPUB", "PDF"}


@pytest.mark.integration
def test_add_format_bad_id_raises_calibredb_error(runner, tmp_path):
    # CONV-01: an unknown book id maps to CalibredbError, not a false success.
    pdf_path = tmp_path / "converted.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

    with pytest.raises(CalibredbError):
        runner.add_format(999999, pdf_path)


@pytest.mark.integration
def test_remove_never_uses_permanent_flag(scratch_library):
    # REM-02/AD-009: removal must go to the recycle bin, never --permanent.
    captured: list[list[str]] = []

    class _CapturingRunner(CalibredbRunner):
        def _run(self, args):  # type: ignore[override]
            captured.append(args)

            class _Proc:
                stdout = ""
                stderr = ""
                returncode = 0

            return _Proc()

    _CapturingRunner(scratch_library).remove(42)

    assert captured == [["remove", "42"]]
    assert "--permanent" not in captured[0]


@pytest.mark.integration
def test_missing_binary_raises_not_found(scratch_library):
    # Error mapping: absent calibredb -> explicit CalibredbNotFoundError.
    runner = CalibredbRunner(scratch_library, binary="calibredb-does-not-exist-xyz")
    with pytest.raises(CalibredbNotFoundError):
        runner.search("anything")


@pytest.mark.integration
def test_nonzero_exit_raises_calibredb_error(runner):
    # Error mapping: set_metadata on a nonexistent id -> CalibredbError w/ stderr.
    with pytest.raises(CalibredbError) as excinfo:
        runner.set_metadata(999999, {"tags": ["x"]})

    assert "999999" in excinfo.value.stderr


@pytest.mark.integration
def test_lock_message_classified_as_locked(scratch_library, tmp_path):
    # Error mapping: Calibre's "another calibre ... is running" -> LibraryLocked.
    fake = tmp_path / "fake_calibredb"
    fake.write_text(
        "#!/bin/sh\n"
        "echo 'Another calibre program such as calibredb or the calibre GUI "
        "is running. Close it and retry.' >&2\n"
        "exit 1\n"
    )
    fake.chmod(0o755)

    runner = CalibredbRunner(scratch_library, binary=str(fake))
    with pytest.raises(LibraryLockedError):
        runner.remove(1)


@pytest.mark.integration
def test_run_never_uses_shell(scratch_library, tmp_path, monkeypatch):
    # Injection safety: the subprocess call must use shell=False (design Risks).
    seen = {}
    real_run = subprocess.run

    def _spy(cmd, *args, **kwargs):
        seen["shell"] = kwargs.get("shell")
        seen["cmd_is_list"] = isinstance(cmd, list)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _spy)
    CalibredbRunner(scratch_library).search("format:epub")

    assert seen["shell"] is False
    assert seen["cmd_is_list"] is True
