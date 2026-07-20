"""Integration tests for the CalibreLibrary facade — reads (T8).

Derived from spec ACs, asserting spec-defined outcomes (not implementation
shape). Run read-only against the REAL test library (``real_library`` fixture);
they never write.

SEARCH-01: search resolves ids via calibredb then hydrates full metadata.
SEARCH-02: list_books returns an ordered page with a sane default/max cap (50).
SEARCH-03: a blank query returns an empty list, not an error, and not "all".
VIEW-01:   get_book returns the full record for a valid id.
VIEW-02:   an unknown id raises BookNotFoundError naming the id.
Invariant: the facade never imports sqlite3/subprocess directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from calibre_mcp import library as library_module
from calibre_mcp.config import Config
from calibre_mcp.errors import BookNotFoundError
from calibre_mcp.library import CalibreLibrary
from calibre_mcp.sqlite_reader import Book


def _config_for(library_path: Path) -> Config:
    return Config(
        library_path=library_path,
        db_path=library_path / "metadata.db",
        backup_root=library_path / ".calibre-mcp-backups",
    )


@pytest.fixture
def facade(real_library: Path) -> CalibreLibrary:
    return CalibreLibrary(_config_for(real_library))


@pytest.mark.integration
def test_search_books_hydrates_matches(facade: CalibreLibrary):
    # SEARCH-01: "Llaudato" resolves to book 1 and comes back fully hydrated.
    results = facade.search_books("Llaudato")

    assert results, "expected at least one match for a real term"
    assert all(isinstance(b, Book) for b in results)
    by_id = {b.id: b for b in results}
    assert 1 in by_id
    assert by_id[1].title == "E2 Llaudato Si"
    assert by_id[1].authors == ["Papa Francisco"]


@pytest.mark.integration
def test_search_books_nonsense_returns_empty(facade: CalibreLibrary):
    # SEARCH-03: a query that matches nothing is an empty list, not an error.
    assert facade.search_books("title:zzz_no_such_title_zzz") == []


@pytest.mark.integration
def test_search_books_blank_query_returns_empty_not_all(facade: CalibreLibrary):
    # SEARCH-03: a blank/whitespace query returns [] WITHOUT matching everything.
    # (calibredb search "" returns all 170 books; the facade must guard that.)
    assert facade.search_books("") == []
    assert facade.search_books("   ") == []


@pytest.mark.integration
def test_list_books_default_caps_at_fifty(facade: CalibreLibrary):
    # SEARCH-02 edge case: absent limit -> sane default cap of 50 (library has 170).
    page = facade.list_books()

    assert len(page) == 50


@pytest.mark.integration
def test_list_books_huge_limit_capped(facade: CalibreLibrary):
    # SEARCH-02 edge case: a huge limit is capped to 50, not the whole library.
    page = facade.list_books(limit=100000)

    assert len(page) == 50


@pytest.mark.integration
def test_list_books_paginates_disjoint_windows(facade: CalibreLibrary):
    # SEARCH-02: offset advances to a different, ordered window.
    page1 = facade.list_books(limit=5, offset=0, sort="id")
    page2 = facade.list_books(limit=5, offset=5, sort="id")

    ids1 = [b.id for b in page1]
    ids2 = [b.id for b in page2]
    assert ids1 == sorted(ids1)
    assert set(ids1).isdisjoint(ids2)


@pytest.mark.integration
def test_count_books_reports_full_size_not_page_size(facade: CalibreLibrary):
    # SEARCH-02: total count is independent of the 50-item page cap (lib has 170).
    total = facade.count_books()
    page = facade.list_books()

    assert total > len(page)
    assert total == 170


@pytest.mark.integration
def test_get_book_returns_full_record(facade: CalibreLibrary):
    # VIEW-01: valid id -> full record read from metadata.db.
    book = facade.get_book(1)

    assert book.id == 1
    assert book.title == "E2 Llaudato Si"
    assert book.authors == ["Papa Francisco"]


@pytest.mark.integration
def test_get_book_unknown_id_raises_not_found(facade: CalibreLibrary):
    # VIEW-02: missing id -> BookNotFoundError naming the id, propagated by facade.
    with pytest.raises(BookNotFoundError) as excinfo:
        facade.get_book(999999)

    assert excinfo.value.book_id == 999999


@pytest.mark.integration
def test_library_stats_includes_known_duplicate_and_ordered_top_lists(
    facade: CalibreLibrary,
):
    # STATS-01-01/06: full AC-1 shape composed; duplicate_title_groups reuses
    # find_duplicate_groups() (the "A fé explicada" duplicate, ids 68 & 132);
    # top-10 lists are length-capped and ordered by count descending.
    stats = facade.library_stats()

    groups = stats["data_quality_flags"]["duplicate_title_groups"]
    matching = [g for g in groups if g["key"]["title"] == "A fé explicada"]
    assert matching, "expected the known 'A fé explicada' duplicate group"
    assert {b["id"] for b in matching[0]["books"]} == {68, 132}

    assert len(stats["authors"]["top"]) <= 10
    assert len(stats["tags"]["top"]) <= 10
    author_counts = [entry["count"] for entry in stats["authors"]["top"]]
    assert author_counts == sorted(author_counts, reverse=True)


@pytest.mark.integration
def test_library_stats_empty_library_returns_same_shape(scratch_library: Path):
    # STATS-01-02 (AC-2): empty library -> same shape, zeroed/empty, no error.
    facade = CalibreLibrary(_config_for(scratch_library))

    stats = facade.library_stats()

    assert stats["totals"]["books"] == 0
    assert stats["authors"] == {"distinct": 0, "top": []}
    assert stats["tags"] == {"distinct": 0, "top": []}
    assert stats["data_quality_flags"] == {
        "unknown_author_books": 0,
        "placeholder_pubdate_0101": 0,
        "series_unused": True,
        "rating_unused": True,
        "duplicate_title_groups": [],
    }


@pytest.mark.integration
def test_library_stats_touches_no_sqlite3_or_subprocess(facade: CalibreLibrary):
    # AD-001: composing library_stats() must not reach for sqlite3/subprocess
    # directly (mirrors the existing facade-wide invariant test).
    facade.library_stats()

    assert not hasattr(library_module, "sqlite3")
    assert not hasattr(library_module, "subprocess")


@pytest.mark.integration
def test_facade_never_imports_sqlite3_or_subprocess():
    # Invariant (design §Layer rule): the facade composes reader+runner; it must
    # not reach for sqlite3/subprocess itself. Imports become module attributes,
    # so their absence proves the facade never imported them directly.
    assert not hasattr(library_module, "sqlite3")
    assert not hasattr(library_module, "subprocess")
