"""Read-only access to Calibre's ``metadata.db`` (VIEW-01/02/03, SEARCH-01/02).

All reads go through here; this layer NEVER writes. The connection is opened
with the ``file:{path}?mode=ro`` URI (``uri=True``) so SQLite itself refuses any
write. JOIN queries were verified against the real test library schema
(authors/tags/series/ratings/comments/identifiers/data/languages link tables).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .errors import BookNotFoundError, InvalidInputError


@dataclass
class Book:
    """Full metadata record for one book (design §Data Models)."""

    id: int
    title: str
    authors: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    series: str | None = None
    series_index: float | None = None
    rating: int | None = None
    publisher: str | None = None
    pubdate: str | None = None
    languages: list[str] = field(default_factory=list)
    comments: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)
    formats: list[str] = field(default_factory=list)
    path: str = ""


# Whitelist of sortable columns: maps the caller-facing sort key to the actual
# ``books`` column. Interpolating the mapped value (never the raw input) into the
# ORDER BY keeps ``list_books`` injection-safe.
_SORT_COLUMNS = {
    "id": "id",
    "title": "sort",
    "authors": "author_sort",
    "pubdate": "pubdate",
    "timestamp": "timestamp",
}


class SqliteReader:
    """Read-only reader over a Calibre ``metadata.db``."""

    def __init__(self, db_path: Path, library_path: Path) -> None:
        self._db_path = Path(db_path)
        self._library_path = Path(library_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def get_book(self, book_id: int) -> Book:
        """Return the full record for ``book_id`` (VIEW-01).

        Rejects non-integer ids before any DB access (VIEW-03) and raises
        ``BookNotFoundError`` when the id does not exist (VIEW-02).
        """
        self._require_int(book_id)
        conn = self._connect()
        try:
            book = self._fetch_book(conn, book_id)
        finally:
            conn.close()
        if book is None:
            raise BookNotFoundError(book_id)
        return book

    def hydrate(self, ids: list[int]) -> list[Book]:
        """Batch-fetch full metadata for ``ids``, preserving order (SEARCH-01).

        Ids that no longer exist are skipped (search results may reference a
        just-removed book); order of the surviving ids is preserved.
        """
        conn = self._connect()
        try:
            books = [self._fetch_book(conn, book_id) for book_id in ids]
        finally:
            conn.close()
        return [book for book in books if book is not None]

    def count_books(self) -> int:
        """Return the total number of books in the library, independent of paging."""
        conn = self._connect()
        try:
            row = conn.execute("SELECT COUNT(*) AS n FROM books").fetchone()
        finally:
            conn.close()
        return row["n"]

    def list_books(self, limit: int, offset: int, sort: str) -> list[Book]:
        """Return a page of books ordered by ``sort`` (SEARCH-02).

        ``sort`` must be one of the whitelisted keys; anything else is rejected
        as invalid input (also blocks ORDER BY injection).
        """
        column = _SORT_COLUMNS.get(sort)
        if column is None:
            allowed = ", ".join(sorted(_SORT_COLUMNS))
            raise InvalidInputError(f"invalid sort '{sort}'; allowed: {allowed}")

        conn = self._connect()
        try:
            rows = conn.execute(
                f"SELECT id FROM books ORDER BY {column} LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            books = [self._fetch_book(conn, row["id"]) for row in rows]
        finally:
            conn.close()
        return [book for book in books if book is not None]

    @staticmethod
    def _require_int(book_id: int) -> None:
        if not isinstance(book_id, int) or isinstance(book_id, bool):
            raise InvalidInputError(f"book id must be an integer, got {book_id!r}")

    def _fetch_book(self, conn: sqlite3.Connection, book_id: int) -> Book | None:
        row = conn.execute(
            "SELECT id, title, series_index, pubdate, path FROM books WHERE id = ?",
            (book_id,),
        ).fetchone()
        if row is None:
            return None

        return Book(
            id=row["id"],
            title=row["title"],
            authors=self._authors(conn, book_id),
            tags=self._tags(conn, book_id),
            series=self._series(conn, book_id),
            series_index=row["series_index"],
            rating=self._rating(conn, book_id),
            publisher=self._publisher(conn, book_id),
            pubdate=row["pubdate"],
            languages=self._languages(conn, book_id),
            comments=self._comments(conn, book_id),
            identifiers=self._identifiers(conn, book_id),
            formats=self._formats(conn, book_id),
            path=row["path"],
        )

    def _authors(self, conn: sqlite3.Connection, book_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT a.name FROM books_authors_link l "
            "JOIN authors a ON a.id = l.author "
            "WHERE l.book = ? ORDER BY l.id",
            (book_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    def _tags(self, conn: sqlite3.Connection, book_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT t.name FROM books_tags_link l "
            "JOIN tags t ON t.id = l.tag "
            "WHERE l.book = ? ORDER BY t.name",
            (book_id,),
        ).fetchall()
        return [r["name"] for r in rows]

    def _series(self, conn: sqlite3.Connection, book_id: int) -> str | None:
        row = conn.execute(
            "SELECT s.name FROM books_series_link l "
            "JOIN series s ON s.id = l.series "
            "WHERE l.book = ? LIMIT 1",
            (book_id,),
        ).fetchone()
        return row["name"] if row else None

    def _rating(self, conn: sqlite3.Connection, book_id: int) -> int | None:
        row = conn.execute(
            "SELECT r.rating FROM books_ratings_link l "
            "JOIN ratings r ON r.id = l.rating "
            "WHERE l.book = ? LIMIT 1",
            (book_id,),
        ).fetchone()
        return row["rating"] if row else None

    def _publisher(self, conn: sqlite3.Connection, book_id: int) -> str | None:
        row = conn.execute(
            "SELECT p.name FROM books_publishers_link l "
            "JOIN publishers p ON p.id = l.publisher "
            "WHERE l.book = ? LIMIT 1",
            (book_id,),
        ).fetchone()
        return row["name"] if row else None

    def _languages(self, conn: sqlite3.Connection, book_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT lg.lang_code FROM books_languages_link l "
            "JOIN languages lg ON lg.id = l.lang_code "
            "WHERE l.book = ? ORDER BY l.item_order",
            (book_id,),
        ).fetchall()
        return [r["lang_code"] for r in rows]

    def _comments(self, conn: sqlite3.Connection, book_id: int) -> str | None:
        row = conn.execute(
            "SELECT text FROM comments WHERE book = ? LIMIT 1",
            (book_id,),
        ).fetchone()
        return row["text"] if row else None

    def _identifiers(self, conn: sqlite3.Connection, book_id: int) -> dict[str, str]:
        rows = conn.execute(
            "SELECT type, val FROM identifiers WHERE book = ?",
            (book_id,),
        ).fetchall()
        return {r["type"]: r["val"] for r in rows}

    def _formats(self, conn: sqlite3.Connection, book_id: int) -> list[str]:
        rows = conn.execute(
            "SELECT format FROM data WHERE book = ? ORDER BY format",
            (book_id,),
        ).fetchall()
        return [r["format"] for r in rows]

    def format_files(self, book_id: int) -> dict[str, Path]:
        """Map each format (e.g. ``"EPUB"``) to its absolute on-disk path
        (ORG-01/CONV-01/EMAIL-01 path resolution, AD-017).

        Raises ``BookNotFoundError`` for an unknown id; raises a clear
        ``InvalidInputError`` when the metadata references a file that is not
        actually on disk, rather than passing a bad path to a CLI.
        """
        conn = self._connect()
        try:
            book_row = conn.execute(
                "SELECT path FROM books WHERE id = ?", (book_id,)
            ).fetchone()
            if book_row is None:
                raise BookNotFoundError(book_id)

            data_rows = conn.execute(
                "SELECT format, name FROM data WHERE book = ?", (book_id,)
            ).fetchall()
        finally:
            conn.close()

        files: dict[str, Path] = {}
        for row in data_rows:
            # NOTE: build the filename by concatenation, not Path.with_suffix —
            # data.name routinely contains literal periods (e.g. "Robert C.
            # Martin") that with_suffix would misread as an existing extension
            # and corrupt when replacing it.
            file_path = (
                self._library_path
                / book_row["path"]
                / f"{row['name']}.{row['format'].lower()}"
            )
            if not file_path.is_file():
                raise InvalidInputError(
                    f"format file for book {book_id} ({row['format']}) not "
                    f"found on disk: {file_path}"
                )
            files[row["format"]] = file_path
        return files

    def find_duplicate_groups(self) -> list[list[Book]]:
        """Group likely-duplicate books by normalized (title, primary author)
        (ORG-01). Groups have size >= 2; no duplicates -> empty list.
        """
        conn = self._connect()
        try:
            rows = conn.execute("SELECT id FROM books").fetchall()
            books = [self._fetch_book(conn, row["id"]) for row in rows]
        finally:
            conn.close()

        groups: dict[tuple[str, str], list[Book]] = {}
        for book in books:
            if book is None:
                continue
            primary_author = book.authors[0] if book.authors else ""
            key = (
                book.title.strip().casefold(),
                primary_author.strip().casefold(),
            )
            groups.setdefault(key, []).append(book)

        return [group for group in groups.values() if len(group) >= 2]
