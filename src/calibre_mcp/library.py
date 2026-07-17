"""``CalibreLibrary`` facade — the single entrypoint the tool layer uses.

Composes the read layer (``SqliteReader``), the write/search layer
(``CalibredbRunner``), the safety net (``backup``) and the intent gate
(``confirmation``), and enforces the cross-cutting rules. It NEVER touches
``sqlite3`` or ``subprocess`` directly — reads go through ``SqliteReader``,
writes through ``CalibredbRunner`` (the one invariant a reviewer checks).
"""

from __future__ import annotations

from pathlib import Path

from .backup import backup_metadata_db, trash_book_files
from .calibredb_runner import CalibredbRunner
from .config import Config
from .confirmation import plan_token, verify
from .errors import InvalidInputError
from .sqlite_reader import Book, SqliteReader

# SEARCH-02 edge case: when ``limit`` is absent or huge, apply a sane cap so a
# single call never tries to page the whole library. This value is both the
# default and the ceiling; ``offset`` is exposed for paging past it.
DEFAULT_LIMIT = 50

# The curation fields ``calibredb set_metadata`` supports (design §Data Models).
# The facade validates every edit against this set before planning a change.
ALLOWED_EDIT_FIELDS = {
    "title",
    "authors",
    "tags",
    "series",
    "series_index",
    "rating",
    "comments",
    "publisher",
    "pubdate",
    "languages",
}

_RATING_MIN = 0
_RATING_MAX = 10

# Operation names bound into the plan token so the applied op is provably the
# reviewed op (AD-012). Must stay stable between the plan and apply calls.
_OP_UPDATE = "update_metadata"
_OP_REMOVE = "remove_book"


class CalibreLibrary:
    """Facade over one Calibre library: reads via SQLite, writes via calibredb."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._reader = SqliteReader(config.db_path, config.library_path)
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

    def count_books(self) -> int:
        """Return the total number of books in the library (unaffected by paging)."""
        return self._reader.count_books()

    def get_book(self, book_id: int) -> Book:
        """Return one book's full record; propagates ``BookNotFoundError``
        (VIEW-01/02) and ``InvalidInputError`` for a non-int id (VIEW-03)."""
        return self._reader.get_book(book_id)

    # -- mutations (plan -> confirm, backup-before-write) ------------------

    def update_metadata(
        self,
        book_id: int,
        fields: dict,
        token: str | None = None,
    ) -> dict:
        """Edit a book's metadata via the plan->confirm handshake (EDIT-01..07).

        Plan step (no token): validate the fields, confirm the book exists, and
        return a current->proposed diff plus a deterministic
        ``confirmation_token`` — nothing is written. Apply step (token): verify
        the token, back up ``metadata.db``, apply via ``calibredb set_metadata``,
        then re-read and return the updated record.
        """
        self._validate_edit_fields(fields)  # EDIT-04 / EDIT-07 (at plan step)
        book = self._reader.get_book(book_id)  # EDIT-06: exists-precheck, no write

        if token is None:
            return {
                "status": "plan",
                "book_id": book_id,
                "diff": self._build_diff(book, fields),
                "confirmation_token": plan_token(_OP_UPDATE, book_id, fields),
            }

        verify(_OP_UPDATE, book_id, fields, token)  # EDIT-03 mismatch -> raise
        backup = backup_metadata_db(  # SAFE-04: raises before any write
            self._config.db_path, self._config.backup_root
        )
        self._runner.set_metadata(book_id, fields)  # EDIT-05 failure propagates
        return {
            "status": "applied",
            "book_id": book_id,
            "book": self._reader.get_book(book_id),  # re-read (EDIT-02)
            "backup": str(backup),
        }

    def add_book(self, path: str | Path) -> dict:
        """Import an ebook file by path (ADD-01..04).

        Validates the path is an existing file BEFORE any subprocess (ADD-02),
        backs up ``metadata.db`` (AD-011), then imports via ``calibredb add``.
        Surfaces a duplicate outcome honestly rather than a fake id (ADD-03);
        a ``calibredb`` failure propagates with its stderr (ADD-04).
        """
        file_path = Path(path)
        if not file_path.is_file():  # ADD-02: reject before subprocess/backup
            raise InvalidInputError(f"add_book: not an existing file: {file_path}")

        backup = backup_metadata_db(self._config.db_path, self._config.backup_root)
        result = self._runner.add(file_path)  # ADD-04 failure propagates

        if result.duplicate:  # ADD-03: surface, never hide
            return {
                "status": "duplicate",
                "book_id": None,
                "duplicate": True,
                "backup": str(backup),
            }
        return {
            "status": "added",
            "book_id": result.book_id,
            "duplicate": False,
            "book": self._reader.get_book(result.book_id),
            "backup": str(backup),
        }

    def remove_book(self, book_id: int, token: str | None = None) -> dict:
        """Remove a book via the review->confirm handshake (REM-01..05).

        Review step (no token): confirm the book exists and return its details
        plus a note that removal is recoverable (trash copy + recycle bin) and a
        ``confirmation_token`` — nothing is deleted. Apply step (token): verify
        the token, then in order (REM-02) copy the book's files to trash, back up
        ``metadata.db``, and ``calibredb remove`` (recycle bin, no
        ``--permanent``). A missing id raises ``BookNotFoundError`` (REM-03, no
        false success); a ``calibredb`` failure propagates and never claims the
        book was removed (REM-04).
        """
        book = self._reader.get_book(book_id)  # REM-03: exists-precheck, no-op

        if token is None:
            return {
                "status": "review",
                "book_id": book_id,
                "title": book.title,
                "authors": book.authors,
                "formats": book.formats,
                "recoverable": True,
                "note": (
                    "files will be copied to backups/trash/ and the book sent to "
                    "the recycle bin (recoverable)"
                ),
                "confirmation_token": plan_token(_OP_REMOVE, book_id, {}),
            }

        verify(_OP_REMOVE, book_id, {}, token)  # REM-05 mismatch -> raise
        trash = trash_book_files(  # REM-02(a)
            book, self._config.library_path, self._config.backup_root
        )
        backup = backup_metadata_db(  # REM-02(b) / SAFE-04: raises before remove
            self._config.db_path, self._config.backup_root
        )
        self._runner.remove(book_id)  # REM-02(c) recycle bin; REM-04 propagates
        return {
            "status": "removed",
            "book_id": book_id,
            "trash_location": str(trash.dest),
            "files_copied": trash.any_copied,  # SAFE-03: honest no-copy reporting
            "copied_files": trash.copied,
            "backup": str(backup),
        }

    @staticmethod
    def _validate_edit_fields(fields: dict) -> None:
        """Reject fields outside the whitelist (EDIT-04) and bad values (EDIT-07)."""
        unknown = set(fields) - ALLOWED_EDIT_FIELDS
        if unknown:
            allowed = ", ".join(sorted(ALLOWED_EDIT_FIELDS))
            raise InvalidInputError(
                f"field(s) {sorted(unknown)} not allowed; allowed: {allowed}"
            )

        if "series_index" in fields and "series" not in fields:
            raise InvalidInputError(
                "series_index requires series; provide series alongside it"
            )

        if "rating" in fields:
            rating = fields["rating"]
            if (
                isinstance(rating, bool)
                or not isinstance(rating, int)
                or not _RATING_MIN <= rating <= _RATING_MAX
            ):
                raise InvalidInputError(
                    f"rating must be an integer in {_RATING_MIN}-{_RATING_MAX} "
                    f"(0-5 stars x2), got {rating!r}"
                )

    @staticmethod
    def _build_diff(book: Book, fields: dict) -> dict:
        """Build a per-field current->proposed diff for the plan (EDIT-01)."""
        return {
            name: {"current": getattr(book, name), "proposed": value}
            for name, value in fields.items()
        }
