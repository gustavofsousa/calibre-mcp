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

import shutil
import sqlite3
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.errors import BookNotFoundError, InvalidInputError
from calibre_mcp.sqlite_reader import Book, SqliteReader

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
