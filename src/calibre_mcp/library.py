"""``CalibreLibrary`` facade — the single entrypoint the tool layer uses.

Composes the read layer (``SqliteReader``), the write/search layer
(``CalibredbRunner``), the safety net (``backup``) and the intent gate
(``confirmation``), and enforces the cross-cutting rules. It NEVER touches
``sqlite3`` or ``subprocess`` directly — reads go through ``SqliteReader``,
writes through ``CalibredbRunner`` (the one invariant a reviewer checks).
"""

from __future__ import annotations

from .calibredb_runner import CalibredbRunner
from .config import Config
from .sqlite_reader import Book, SqliteReader

# SEARCH-02 edge case: when ``limit`` is absent or huge, apply a sane cap so a
# single call never tries to page the whole library. This value is both the
# default and the ceiling; ``offset`` is exposed for paging past it.
DEFAULT_LIMIT = 50


class CalibreLibrary:
    """Facade over one Calibre library: reads via SQLite, writes via calibredb."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._reader = SqliteReader(config.db_path)
        self._runner = CalibredbRunner(config.library_path)

    def search_books(self, query: str) -> list[Book]:
        """Resolve ids via ``calibredb search`` then hydrate them (SEARCH-01).

        An empty/blank query returns an empty list rather than an error and
        without hitting ``calibredb`` (SEARCH-03) — a blank query is "no
        criteria", not "match everything".
        """
        if not query or not query.strip():
            return []
        ids = self._runner.search(query)
        return self._reader.hydrate(ids)

    def list_books(
        self,
        limit: int | None = None,
        offset: int = 0,
        sort: str = "id",
    ) -> list[Book]:
        """Return a page of books ordered by ``sort`` (SEARCH-02).

        ``limit`` defaults to and is capped at ``DEFAULT_LIMIT`` so an absent or
        huge value can never request the whole library in one call.
        """
        capped = DEFAULT_LIMIT if limit is None else min(limit, DEFAULT_LIMIT)
        return self._reader.list_books(capped, offset, sort)

    def get_book(self, book_id: int) -> Book:
        """Return one book's full record; propagates ``BookNotFoundError``
        (VIEW-01/02) and ``InvalidInputError`` for a non-int id (VIEW-03)."""
        return self._reader.get_book(book_id)
