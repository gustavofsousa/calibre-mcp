"""Integration tests for SqliteReader — derived from spec VIEW-* and SEARCH-*.

Run read-only against the REAL test library (``real_library`` fixture). Never
writes. Assertions target spec-defined outcomes, not implementation shape.

VIEW-01: get_book returns the full metadata record for a valid id.
VIEW-02: unknown id -> clear "book not found" error naming the id.
VIEW-03: non-integer id -> rejected before touching the database.
SEARCH-01: hydrate batch-fetches full metadata preserving order.
SEARCH-02: list_books returns a page ordered by the requested field.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.errors import BookNotFoundError, InvalidInputError
from calibre_mcp.sqlite_reader import Book, LibraryStats, SqliteReader

REAL_LIBRARY = Path("/home/gustavo/Documents/BibliotecaCalibre")


def _sample_epub(tmp_path: Path, name: str = "sample.epub", index: int = 0) -> Path:
    sources = list(REAL_LIBRARY.glob("**/*.epub"))
    if len(sources) <= index:
        pytest.skip("not enough distinct sample .epub files in the real library")
    dest = tmp_path / name
    shutil.copy2(sources[index], dest)
    return dest


def _seed_book(
    scratch_library: Path, tmp_path: Path, name: str = "seed.epub", index: int = 0
) -> int:
    result = CalibredbRunner(scratch_library).add(
        _sample_epub(tmp_path, name, index)
    )
    assert result.book_id is not None
    return result.book_id


def _valid_cover_png(path: Path, width: int = 100, height: int = 150) -> Path:
    """Write a real, multi-pixel PNG using only stdlib zlib/struct.

    Calibre re-encodes any valid input image to ``cover.jpg`` on
    ``set_metadata --field cover:``. A degenerate 1x1 PNG is rejected by Qt
    ("Image is empty"), so this emits a real WxH white image.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + b"\xff\xff\xff" * width  # filter byte + white pixels
    idat = zlib.compress(row * height)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def _seed_empty_book(scratch_library: Path, title: str = "Empty") -> int:
    # calibredb add --empty has no CalibredbRunner wrapper (adds no format /
    # embedded cover) -- needed so an "uncovered" book is deterministic,
    # since a real sample .epub's own embedded cover gets auto-extracted.
    result = subprocess.run(
        [
            "calibredb",
            "add",
            "--empty",
            "--title",
            title,
            "--with-library",
            str(scratch_library),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(
        r"Added book ids:\s*([\d,]+)", f"{result.stdout}\n{result.stderr}"
    )
    assert match is not None
    return int(match.group(1).split(",")[0])


def _seed_covered_book(scratch_library: Path, tmp_path: Path) -> int:
    book_id = _seed_empty_book(scratch_library, "Covered")
    cover_png = _valid_cover_png(tmp_path / "cover-source.png")
    CalibredbRunner(scratch_library).set_metadata(book_id, {"cover": str(cover_png)})
    return book_id


@pytest.fixture
def reader(real_library: Path) -> SqliteReader:
    return SqliteReader(real_library / "metadata.db", real_library)


@pytest.mark.integration
def test_get_book_returns_full_record(reader: SqliteReader):
    # VIEW-01: known book 1 in the real library (verified during design).
    book = reader.get_book(1)

    assert isinstance(book, Book)
    assert book.id == 1
    assert book.title == "E2 Llaudato Si"
    assert book.authors == ["Papa Francisco"]
    assert "EPUB" in book.formats
    assert book.path.startswith("Papa Francisco")
    assert book.rating is None  # no ratings exist in the test library


@pytest.mark.integration
def test_get_book_hydrates_tags_and_languages(reader: SqliteReader):
    # VIEW-01: a record with multiple tags + a language (book 15, verified).
    book = reader.get_book(15)

    assert book.title == "Nineteen Ways of Looking at Wang Wei"
    assert len(book.tags) == 6
    assert "Poetry" in book.tags
    assert book.languages == ["eng"]


@pytest.mark.integration
def test_get_book_preserves_multi_author_order(reader: SqliteReader):
    # VIEW-01: multi-author book 27 keeps Calibre's author order.
    book = reader.get_book(27)

    assert book.authors == [
        "Francisco Adolfo de Varnhagen",
        "João Capistrano de Abreu",
    ]


@pytest.mark.integration
def test_books_by_author_finds_every_book_ascending_sorted(reader: SqliteReader):
    # ARENAME-01: "Papa Francisco" credits books 1,2,4,5 (verified in the real
    # library) -- returned ascending regardless of underlying link-table order.
    ids = reader.books_by_author("Papa Francisco")

    assert ids == [1, 2, 4, 5]


@pytest.mark.integration
def test_books_by_author_finds_coauthored_book_by_either_credited_name(
    reader: SqliteReader,
):
    # ARENAME-01: book 27 credits two authors; matching by either name finds it.
    assert 27 in reader.books_by_author("Francisco Adolfo de Varnhagen")
    assert 27 in reader.books_by_author("João Capistrano de Abreu")


@pytest.mark.integration
def test_books_by_author_no_match_returns_empty_list(reader: SqliteReader):
    # ARENAME-02: an author name credited to no book returns [] (not an error).
    assert reader.books_by_author("Nonexistent Author XYZ") == []


@pytest.mark.integration
def test_books_by_tag_finds_every_book_ascending_sorted(reader: SqliteReader):
    # TRENAME-01: "Poetry" tags books 9,15,17,19 (verified in the real
    # library) -- returned ascending regardless of underlying link-table order.
    assert reader.books_by_tag("Poetry") == [9, 15, 17, 19]


@pytest.mark.integration
def test_books_by_tag_finds_a_multi_tag_book(reader: SqliteReader):
    # TRENAME-01: book 15 carries several tags incl. "Poetry"; it is found.
    assert 15 in reader.books_by_tag("Poetry")


@pytest.mark.integration
def test_books_by_tag_no_match_returns_empty_list(reader: SqliteReader):
    # TRENAME-02: a tag on no book returns [] (not an error).
    assert reader.books_by_tag("Nonexistent Tag XYZ") == []


# --------------------------------------------------------- books_by_series
# The real library has 0 books in any series (series_unused) -- these tests
# seed a scratch_library instead of using the real-library `reader` fixture.


@pytest.mark.integration
def test_books_by_series_finds_every_book_ascending_sorted(
    scratch_library: Path, tmp_path: Path
):
    # SRENAME-01: two books in "Old", one in "Other" -- only the "Old" pair
    # is returned, ascending regardless of underlying link-table order.
    runner = CalibredbRunner(scratch_library)
    id2 = _seed_book(scratch_library, tmp_path, "two.epub", index=1)
    id1 = _seed_book(scratch_library, tmp_path, "one.epub", index=0)
    id3 = _seed_book(scratch_library, tmp_path, "three.epub", index=2)
    runner.set_metadata(id2, {"series": "Old", "series_index": "2.0"})
    runner.set_metadata(id1, {"series": "Old", "series_index": "1.0"})
    runner.set_metadata(id3, {"series": "Other", "series_index": "1.0"})
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    assert reader.books_by_series("Old") == sorted([id1, id2])


@pytest.mark.integration
def test_books_by_series_no_match_returns_empty_list(
    scratch_library: Path, tmp_path: Path
):
    # SRENAME-02: a series on no book returns [] (not an error).
    _seed_book(scratch_library, tmp_path)
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    assert reader.books_by_series("Nonexistent Series XYZ") == []


@pytest.mark.integration
def test_get_book_unknown_id_raises_not_found(reader: SqliteReader):
    # VIEW-02: missing id -> BookNotFoundError naming the id.
    with pytest.raises(BookNotFoundError) as excinfo:
        reader.get_book(999999)

    assert excinfo.value.book_id == 999999


@pytest.mark.integration
def test_get_book_non_int_raises_invalid_input(reader: SqliteReader):
    # VIEW-03: non-integer id rejected before DB access.
    with pytest.raises(InvalidInputError):
        reader.get_book("1")  # type: ignore[arg-type]


@pytest.mark.integration
def test_list_books_paginates_disjoint_windows(reader: SqliteReader):
    # SEARCH-02: offset yields a different, ordered page.
    page1 = reader.list_books(limit=5, offset=0, sort="id")
    page2 = reader.list_books(limit=5, offset=5, sort="id")

    assert len(page1) == 5
    assert len(page2) == 5
    ids1 = [b.id for b in page1]
    ids2 = [b.id for b in page2]
    assert ids1 == sorted(ids1)  # ordered by id
    assert set(ids1).isdisjoint(ids2)  # paging advanced the window
    assert min(ids2) > max(ids1)


@pytest.mark.integration
def test_list_books_orders_by_requested_field(reader: SqliteReader):
    # SEARCH-02: sorting by pubdate yields ascending pubdates (string-comparable
    # ISO). Property-based, not coupled to the implementation's query text.
    books = reader.list_books(limit=20, offset=0, sort="pubdate")

    pubdates = [b.pubdate for b in books]
    assert pubdates == sorted(pubdates)


@pytest.mark.integration
def test_list_books_rejects_unknown_sort(reader: SqliteReader):
    # SEARCH-02 / injection-safety: only whitelisted sort keys are honored.
    with pytest.raises(InvalidInputError):
        reader.list_books(limit=5, offset=0, sort="id; DROP TABLE books")


@pytest.mark.integration
def test_hydrate_preserves_order(reader: SqliteReader):
    # SEARCH-01: hydrate returns full records in the requested id order.
    books = reader.hydrate([3, 1, 2])

    assert [b.id for b in books] == [3, 1, 2]
    assert all(b.title for b in books)


@pytest.mark.integration
def test_hydrate_skips_missing_ids(reader: SqliteReader):
    # SEARCH-01: a stale/removed id is skipped, order otherwise preserved.
    books = reader.hydrate([1, 999999, 2])

    assert [b.id for b in books] == [1, 2]


@pytest.mark.integration
def test_count_books_matches_independent_query(
    reader: SqliteReader, real_library: Path
):
    # SEARCH-02: count_books reports the full library size, not a page size.
    conn = sqlite3.connect(
        f"file:{real_library / 'metadata.db'}?mode=ro", uri=True
    )
    try:
        expected = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    finally:
        conn.close()

    assert reader.count_books() == expected


# ---------------------------------------------------------------- format_files


@pytest.mark.integration
def test_format_files_returns_absolute_path_per_format(reader: SqliteReader):
    # AD-017: book 1 has EPUB; the resolved path exists and matches the layout.
    files = reader.format_files(1)

    assert "EPUB" in files
    assert files["EPUB"].is_file()
    assert files["EPUB"].suffix == ".epub"


@pytest.mark.integration
def test_format_files_unknown_book_raises_not_found(reader: SqliteReader):
    with pytest.raises(BookNotFoundError) as excinfo:
        reader.format_files(999999)

    assert excinfo.value.book_id == 999999


@pytest.mark.integration
def test_format_files_missing_file_on_disk_raises_invalid_input(
    scratch_library: Path, tmp_path: Path
):
    # Design Risks: metadata references a file that isn't there -> clear error,
    # never a bad path passed to a CLI.
    book_id = _seed_book(scratch_library, tmp_path)
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)
    book = reader.get_book(book_id)
    shutil.rmtree(scratch_library / book.path)  # wipe the book's files on disk

    with pytest.raises(InvalidInputError) as excinfo:
        reader.format_files(book_id)

    assert str(book_id) in str(excinfo.value)


# ------------------------------------------------------------------- cover_file


@pytest.mark.integration
def test_cover_file_covered_book_returns_resolved_path(
    scratch_library: Path, tmp_path: Path
):
    # RCOVER-01: has_cover=1 and cover.jpg present -> resolved Path, is_file() true.
    book_id = _seed_covered_book(scratch_library, tmp_path)
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    cover = reader.cover_file(book_id)

    assert cover is not None
    assert cover.is_file()
    assert cover.name == "cover.jpg"


@pytest.mark.integration
def test_cover_file_uncovered_book_returns_none(scratch_library: Path):
    # RCOVER-02: has_cover=0 -> None (a normal state, not an error). An empty
    # book (no formats) guarantees no embedded cover was auto-extracted.
    book_id = _seed_empty_book(scratch_library)
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    assert reader.cover_file(book_id) is None


@pytest.mark.integration
def test_cover_file_unknown_book_raises_not_found(scratch_library: Path):
    # RCOVER-03: unknown id -> BookNotFoundError naming the id.
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    with pytest.raises(BookNotFoundError) as excinfo:
        reader.cover_file(999999)

    assert excinfo.value.book_id == 999999


@pytest.mark.integration
def test_cover_file_missing_on_disk_raises_invalid_input(
    scratch_library: Path, tmp_path: Path
):
    # RCOVER-04: has_cover=1 but cover.jpg missing on disk -> InvalidInputError
    # (metadata<->disk inconsistency), mirroring format_files -- never a
    # silent "no cover" degrade.
    book_id = _seed_covered_book(scratch_library, tmp_path)
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)
    book = reader.get_book(book_id)
    (scratch_library / book.path / "cover.jpg").unlink()

    with pytest.raises(InvalidInputError) as excinfo:
        reader.cover_file(book_id)

    assert str(book_id) in str(excinfo.value)


# ---------------------------------------------------------- find_duplicate_groups


@pytest.mark.integration
def test_find_duplicate_groups_groups_same_title_and_author(
    scratch_library: Path, tmp_path: Path
):
    # ORG-01: two books with the same (title, primary author) -> one group of 2.
    runner = CalibredbRunner(scratch_library)
    id1 = _seed_book(scratch_library, tmp_path, "one.epub", index=0)
    id2 = _seed_book(scratch_library, tmp_path, "two.epub", index=1)
    runner.set_metadata(id1, {"title": "Same Title", "authors": ["Same Author"]})
    runner.set_metadata(id2, {"title": "Same Title", "authors": ["Same Author"]})
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    groups = reader.find_duplicate_groups()

    assert len(groups) == 1
    assert {b.id for b in groups[0]} == {id1, id2}


@pytest.mark.integration
def test_find_duplicate_groups_no_duplicates_returns_empty_list(
    scratch_library: Path, tmp_path: Path
):
    # ORG-01 AC-3: distinct (title, author) pairs -> no groups.
    runner = CalibredbRunner(scratch_library)
    id1 = _seed_book(scratch_library, tmp_path, "one.epub", index=0)
    id2 = _seed_book(scratch_library, tmp_path, "two.epub", index=1)
    runner.set_metadata(id1, {"title": "Title One", "authors": ["Author One"]})
    runner.set_metadata(id2, {"title": "Title Two", "authors": ["Author Two"]})
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    assert reader.find_duplicate_groups() == []


# --------------------------------------------------------------- library_stats


@pytest.mark.integration
def test_library_stats_returns_every_ac1_sub_object(reader: SqliteReader):
    # STATS-01-01: every AC-1 sub-object present, computed in one connection.
    stats = reader.library_stats()

    assert isinstance(stats, LibraryStats)
    assert set(stats.totals) == {
        "books",
        "min_id",
        "max_id",
        "gapped_ids",
        "next_id_hint",
    }
    assert isinstance(stats.formats, dict)
    assert "unset" in stats.languages
    assert set(stats.metadata_completeness) == {
        "comments",
        "publisher",
        "tags",
        "identifiers",
        "languages",
        "real_pubdate",
        "series",
        "rating",
    }
    for field in stats.metadata_completeness.values():
        assert set(field) == {"filled", "pct"}
    assert set(stats.authors) == {"distinct", "top"}
    assert set(stats.tags) == {"distinct", "top"}
    assert set(stats.data_quality) == {
        "unknown_author_books",
        "placeholder_pubdate_0101",
        "series_unused",
        "rating_unused",
    }


@pytest.mark.integration
def test_library_stats_grounded_facts_against_real_library(reader: SqliteReader):
    # STATS-01-01/02: grounded facts confirmed directly against metadata.db
    # (170 books, ids 1-185, 64 placeholder pubdates, 14 Unknown-author books).
    stats = reader.library_stats()

    assert stats.totals["books"] == reader.count_books()
    assert stats.totals["max_id"] + 1 == stats.totals["next_id_hint"]
    assert stats.data_quality["placeholder_pubdate_0101"] == 64
    assert stats.data_quality["unknown_author_books"] == 14
    assert stats.metadata_completeness["comments"]["filled"] == 49
    # Edge case: real (non-placeholder) pubdates are mutually exclusive with
    # placeholder_pubdate_0101 and counted separately (170 - 64 = 106).
    assert stats.metadata_completeness["real_pubdate"]["filled"] == 106
    # Edge case: books with no language recorded land in an explicit "unset"
    # bucket rather than being silently dropped from the total.
    assert stats.languages["unset"] == 91
    assert sum(stats.languages.values()) == stats.totals["books"]


@pytest.mark.integration
def test_library_stats_pct_guarded_and_tie_breakers_deterministic(
    reader: SqliteReader,
):
    # STATS-01-05: pct is a real percentage (no ZeroDivision on a non-empty
    # library); top lists carry an explicit tie-breaker so order is stable.
    stats = reader.library_stats()

    comments = stats.metadata_completeness["comments"]
    assert comments["pct"] == round(100 * comments["filled"] / stats.totals["books"], 1)
    assert len(stats.authors["top"]) <= 10
    assert len(stats.tags["top"]) <= 10
    author_counts = [entry["count"] for entry in stats.authors["top"]]
    assert author_counts == sorted(author_counts, reverse=True)
    # STATS-01-01 grounded: "Eiichirô Oda" (20 books) is the top author.
    assert stats.authors["top"][0] == {"name": "Eiichirô Oda", "count": 20}


@pytest.mark.integration
def test_library_stats_two_reads_are_identical(reader: SqliteReader):
    # STATS-01-05 (AC-5): deterministic — two reads with no DB change match.
    first = reader.library_stats()
    second = reader.library_stats()

    assert first == second


@pytest.mark.integration
def test_library_stats_empty_library_returns_zeroed_snapshot(scratch_library: Path):
    # STATS-01-02 (AC-2): empty library -> zeroed/empty snapshot, no error.
    reader = SqliteReader(scratch_library / "metadata.db", scratch_library)

    stats = reader.library_stats()

    assert stats.totals == {
        "books": 0,
        "min_id": None,
        "max_id": None,
        "gapped_ids": 0,
        "next_id_hint": 1,
    }
    assert stats.formats == {}
    assert stats.languages == {"unset": 0}
    assert all(
        field["filled"] == 0 and field["pct"] == 0.0
        for field in stats.metadata_completeness.values()
    )
    assert stats.identifier_types == {}
    assert stats.authors == {"distinct": 0, "top": []}
    assert stats.tags == {"distinct": 0, "top": []}
    assert stats.data_quality == {
        "unknown_author_books": 0,
        "placeholder_pubdate_0101": 0,
        "series_unused": True,
        "rating_unused": True,
    }
