"""``CalibreLibrary`` facade — the single entrypoint the tool layer uses.

Composes the read layer (``SqliteReader``), the write/search layer
(``CalibredbRunner``), the safety net (``backup``) and the intent gate
(``confirmation``), and enforces the cross-cutting rules. It NEVER touches
``sqlite3`` or ``subprocess`` directly — reads go through ``SqliteReader``,
writes through ``CalibredbRunner`` (the one invariant a reviewer checks).
"""

from __future__ import annotations

import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .backup import backup_metadata_db, trash_book_files
from .bulk_edit import LIST_FIELDS, LIST_MODES, resolve_fields
from .calibre_smtp_runner import CalibreSmtpRunner
from .calibredb_runner import CalibredbRunner
from .config import Config, load_smtp_config
from .confirmation import plan_token, verify
from .ebook_convert_runner import EbookConvertRunner
from .errors import BookNotFoundError, CalibreMcpError, InvalidInputError
from .folder_scan import scan_ebook_files
from .sqlite_reader import Book, SqliteReader

# CONV-01: formats convert_book accepts as a target, and the device-preference
# order email_book uses to pick an attachment when none is specified.
SUPPORTED_CONVERT_FORMATS = ("epub", "azw3", "mobi", "pdf")
EMAIL_FORMAT_PREFERENCE = ("EPUB", "AZW3", "MOBI", "PDF")

# SEARCH-02 edge case: when ``limit`` is absent or huge, apply a sane cap so a
# single call never tries to page the whole library. This value is both the
# default and the ceiling; ``offset`` is exposed for paging past it.
DEFAULT_LIMIT = 50

# BCONV-06: a bulk convert is a sequence of subprocesses (300 s per-book
# timeout); cap the batch so an accidental "convert everything" can't run for
# an hour. Rejected as invalid input before any backup/convert.
BULK_CONVERT_MAX = 50

# BIMPORT-02: a folder import is a sequence of `calibredb add` subprocesses;
# cap the ebook-candidate count (not every file under the folder) so pointing
# at a huge tree is rejected before any backup/import.
FOLDER_IMPORT_MAX = 500

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
_OP_EMAIL = "email_book"
_OP_UPDATE_BULK = "update_metadata_bulk"

# Sentinel id bound into the bulk token in place of a single book id — the
# batch identity lives entirely in the payload's ``book_ids`` (design §Data
# Models).
_BULK_TOKEN_ID = 0


class CalibreLibrary:
    """Facade over one Calibre library: reads via SQLite, writes via calibredb."""

    def __init__(self, config: Config) -> None:
        self._config = config
        self._reader = SqliteReader(config.db_path, config.library_path)
        self._runner = CalibredbRunner(config.library_path)
        self._converter = EbookConvertRunner()
        self._mailer = CalibreSmtpRunner()

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

    def find_duplicates(self) -> dict[str, Any]:
        """Return groups of likely-duplicate books, advisory only (ORG-01).

        Pure read (no subprocess, lock-independent); never mutates and never
        auto-merges — the host/user decides what, if anything, to do about a
        reported group.
        """
        groups = self._reader.find_duplicate_groups()
        return {
            "group_count": len(groups),
            "groups": [self._shape_duplicate_group(group) for group in groups],
        }

    def library_stats(self) -> dict[str, Any]:
        """Return the aggregate baseline profile of the library (STATS-01).

        Pure read (no subprocess, lock-independent). Composes the reader's
        snapshot with ``find_duplicate_groups()`` (reused as-is, ORG-01) so
        ``data_quality_flags.duplicate_title_groups`` matches ``find_duplicates``.
        """
        stats = asdict(self._reader.library_stats())
        data_quality_flags = stats.pop("data_quality")
        groups = self._reader.find_duplicate_groups()
        data_quality_flags["duplicate_title_groups"] = [
            self._shape_duplicate_group(group) for group in groups
        ]
        return {**stats, "data_quality_flags": data_quality_flags}

    def convert_book(self, book_id: int, target_format: str) -> dict[str, Any]:
        """Convert a book to ``target_format``, keeping the existing format(s)
        (CONV-01, AD-011, AD-016).

        Additive, single-step (like ``add_book``): refuses (``InvalidInputError``)
        if ``target_format`` already exists on the book or the book has no source
        file, rather than a confirm gate. Backs up ``metadata.db`` BEFORE
        ``add_format`` (AD-011), converts additively via the shared convert core,
        then re-reads and returns the book with both formats.
        """
        target = target_format.lower()
        if target not in SUPPORTED_CONVERT_FORMATS:
            allowed = ", ".join(SUPPORTED_CONVERT_FORMATS)
            raise InvalidInputError(
                f"unsupported target format {target_format!r}; allowed: {allowed}"
            )

        book = self._reader.get_book(book_id)  # exists-precheck, no write
        kind, info = self._classify_convert(book, target)
        if kind == "skip":  # AC-3/AC-4: already-has-format or no source -> refuse
            raise InvalidInputError(f"book {book_id} {info}; nothing to do")

        backup = backup_metadata_db(  # AD-011: backup BEFORE add_format
            self._config.db_path, self._config.backup_root
        )
        self._convert_and_attach(book_id, target, info)  # AC-5 failure propagates
        return {
            "status": "converted",
            "book_id": book_id,
            "book": self._reader.get_book(book_id),  # re-read: old + new formats
            "backup": str(backup),
        }

    def _classify_convert(self, book: Book, target: str) -> tuple[str, str]:
        """Classify a book for conversion to ``target`` — shared convert core.

        Returns ``("skip", reason)`` when the book already has ``target`` (the
        reason names the format) or has no source file to convert from, else
        ``("ready", source_path)``. A skip is a RETURN VALUE, never an exception:
        the bulk loop treats a benign no-op as data and a real failure as an
        exception (BCONV-02/03). Raises nothing for the skip cases.
        """
        if target.upper() in book.formats:
            return ("skip", f"already has format {target.upper()}")
        source_files = self._reader.format_files(book.id)  # AD-017
        if not source_files:
            return ("skip", "has no file to convert from")
        return ("ready", str(next(iter(source_files.values()))))

    def _convert_and_attach(self, book_id: int, target: str, source: str) -> None:
        """Convert ``source`` to ``target`` and attach it additively — shared core.

        Converts into a ``TemporaryDirectory`` (cleaned up even on failure) via
        ``EbookConvertRunner`` then ``CalibredbRunner.add_format``. Raises
        ``EbookConvertError`` / ``CalibredbError`` on real failure. Does NOT back
        up — the caller owns the one backup (single tool: before this call; bulk:
        once before the loop).
        """
        with tempfile.TemporaryDirectory() as out_dir:
            converted = self._converter.convert(Path(source), target, Path(out_dir))
            self._runner.add_format(book_id, converted)

    def convert_book_bulk(
        self, book_ids: list[int], target_format: str
    ) -> dict[str, Any]:
        """Convert N books to one ``target_format`` — additive, best-effort
        three-bucket (BCONV-01..06).

        Additive/no-token (AD-016): one ``metadata.db`` backup before the loop
        as the single rollback point (AD-011, unconditional even if every book
        is skipped), then each book in ``sorted(book_ids)`` lands in exactly one
        bucket — ``converted`` (re-read resulting formats, BCONV-04),
        ``skipped`` (benign no-op: already has the format / no source,
        BCONV-03), or ``failed`` (real per-book error, BCONV-02). A per-book
        failure never aborts the batch and never reports a fake "all succeeded";
        ``len(converted)+len(skipped)+len(failed) == len(book_ids)`` (BCONV-05).
        """
        target = self._validate_bulk_convert_input(book_ids, target_format)
        backup = backup_metadata_db(  # BCONV-01: once, before the loop
            self._config.db_path, self._config.backup_root
        )

        converted: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for book_id in sorted(book_ids):
            try:
                book = self._reader.get_book(book_id)  # vanished -> failed
                kind, info = self._classify_convert(book, target)
                if kind == "skip":  # BCONV-03: benign no-op, not a failure
                    skipped.append({"book_id": book_id, "reason": info})
                    continue
                self._convert_and_attach(book_id, target, info)
                reread = self._reader.get_book(book_id)  # BCONV-04: demonstrate
                converted.append({"book_id": book_id, "formats": reread.formats})
            except CalibreMcpError as exc:  # BCONV-02: never aborts the batch
                failed.append({"book_id": book_id, "error": str(exc)})

        return {
            "status": "converted",
            "target_format": target,
            "converted": converted,
            "skipped": skipped,
            "failed": failed,
            "backup": str(backup),
        }

    @staticmethod
    def _validate_bulk_convert_input(
        book_ids: list[int], target_format: str
    ) -> str:
        """Reject invalid bulk-convert input before any backup/convert (BCONV-06).

        Checks, in order: ``target_format`` (lowercased) is a supported convert
        target; ``book_ids`` is non-empty, every element a non-bool ``int``, no
        duplicates, and ``len <= BULK_CONVERT_MAX``. Returns the normalized
        (lowercased) target so the caller converts against the canonical value.
        """
        target = target_format.lower()
        if target not in SUPPORTED_CONVERT_FORMATS:
            allowed = ", ".join(SUPPORTED_CONVERT_FORMATS)
            raise InvalidInputError(
                f"unsupported target format {target_format!r}; allowed: {allowed}"
            )

        if not book_ids:
            raise InvalidInputError("book_ids must not be empty")
        if any(
            isinstance(book_id, bool) or not isinstance(book_id, int)
            for book_id in book_ids
        ):
            raise InvalidInputError(f"book_ids must all be integers, got {book_ids!r}")
        if len(set(book_ids)) != len(book_ids):
            raise InvalidInputError(
                f"book_ids must not contain duplicates: {book_ids!r}"
            )
        if len(book_ids) > BULK_CONVERT_MAX:
            raise InvalidInputError(
                f"too many book_ids: {len(book_ids)} exceeds the "
                f"{BULK_CONVERT_MAX}-book bulk convert cap"
            )
        return target

    # -- mutations (plan -> confirm, backup-before-write) ------------------

    def update_metadata(
        self,
        book_id: int,
        fields: dict[str, Any],
        token: str | None = None,
    ) -> dict[str, Any]:
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

    def update_metadata_bulk(
        self,
        book_ids: list[int],
        fields: dict[str, Any],
        list_mode: str = "replace",
        token: str | None = None,
    ) -> dict[str, Any]:
        """Broadcast ``fields`` to N books via the plan->confirm handshake
        (BEDIT-01..09).

        Plan step (no token): validate input, then for each ``sorted(book_ids)``
        emit a not-found row or a current->proposed diff (``proposed`` is the
        per-book *resolved* set under ``list_mode``) plus one deterministic
        ``confirmation_token`` over the whole batch — nothing is written.
        Apply step (token): verify the token, back up ``metadata.db`` ONCE, then
        best-effort apply each book in order — a per-book failure lands in
        ``failed`` and the batch continues (never a false "all succeeded").
        """
        self._validate_bulk_input(book_ids, fields, list_mode)
        ordered_ids = sorted(book_ids)
        payload = {"book_ids": ordered_ids, "fields": fields, "list_mode": list_mode}

        if token is None:
            return {
                "status": "plan",
                "list_mode": list_mode,
                "diffs": [
                    self._bulk_plan_entry(book_id, fields, list_mode)
                    for book_id in ordered_ids
                ],
                "confirmation_token": plan_token(
                    _OP_UPDATE_BULK, _BULK_TOKEN_ID, payload
                ),
            }

        verify(_OP_UPDATE_BULK, _BULK_TOKEN_ID, payload, token)  # BEDIT-03
        backup = backup_metadata_db(  # BEDIT-05: once, before the loop
            self._config.db_path, self._config.backup_root
        )

        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for book_id in ordered_ids:
            try:
                book = self._reader.get_book(book_id)
                resolved = resolve_fields(book, fields, list_mode)
                self._runner.set_metadata(book_id, resolved)
                reread = self._reader.get_book(book_id)
                applied.append(
                    {
                        "book_id": book_id,
                        "fields": {name: getattr(reread, name) for name in fields},
                    }
                )
            except CalibreMcpError as exc:  # BEDIT-04: never aborts the batch
                failed.append({"book_id": book_id, "error": str(exc)})

        return {
            "status": "applied",
            "list_mode": list_mode,
            "applied": applied,
            "failed": failed,
            "backup": str(backup),
        }

    def add_book(self, path: str | Path) -> dict[str, Any]:
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
        result = self._import_one(file_path)  # ADD-04 failure propagates

        if result["duplicate"]:  # ADD-03: surface, never hide
            return {
                "status": "duplicate",
                "book_id": None,
                "duplicate": True,
                "backup": str(backup),
            }
        return {
            "status": "added",
            "book_id": result["book_id"],
            "duplicate": False,
            "book": result["book"],
            "backup": str(backup),
        }

    def _import_one(self, file_path: Path) -> dict[str, Any]:
        """Classify one ``calibredb add`` result — shared by ``add_book`` and
        ``import_folder`` (BIMPORT-05/06).

        The single "surface duplicate, never a fake id, re-read on success"
        rule. Contains NO backup — each caller backs up before calling this, so
        no new side-effect ordering is introduced (lesson L-006).
        """
        result = self._runner.add(file_path)
        if result.duplicate:
            return {"duplicate": True, "book_id": None}
        if result.book_id is None:
            # Unreachable by construction (CalibredbRunner.add raises when it can
            # parse neither an id nor a duplicate); the guard keeps the state
            # impossible explicit instead of passing None to get_book.
            raise InvalidInputError("calibredb add returned no book id")
        return {
            "duplicate": False,
            "book_id": result.book_id,
            "book": self._reader.get_book(result.book_id),
        }

    def import_folder(self, path: str | Path) -> dict[str, Any]:
        """Import every ebook file under a directory, recursively (BIMPORT-01..07).

        Additive/no-token (AD-016), like ``add_book``. Rejects a non-directory
        or an over-cap ebook-candidate count as invalid input **before** any
        backup (BIMPORT-02), then takes exactly one ``metadata.db`` backup
        before the loop (BIMPORT-03, unconditional even with zero candidates).
        Each ``sorted`` candidate is imported best-effort via the shared
        ``_import_one`` core and lands in exactly one of ``added`` /
        ``duplicate`` / ``failed`` — a per-file failure never aborts the batch
        (BIMPORT-04); ``len(added)+len(duplicate)+len(failed) ==
        len(candidates)`` (BIMPORT-07).
        """
        folder = Path(path)
        if not folder.is_dir():  # BIMPORT-02: reject before scan/backup
            raise InvalidInputError(
                f"import_folder: not an existing directory: {folder}"
            )

        candidates = self._safe_scan(folder)
        if len(candidates) > FOLDER_IMPORT_MAX:  # BIMPORT-02: reject before backup
            raise InvalidInputError(
                f"too many ebook candidates: {len(candidates)} exceeds the "
                f"{FOLDER_IMPORT_MAX}-file folder import cap"
            )

        backup = backup_metadata_db(  # BIMPORT-03: once, before the loop
            self._config.db_path, self._config.backup_root
        )

        added: list[dict[str, Any]] = []
        duplicate: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for file_path in candidates:
            try:
                result = self._import_one(file_path)
                if result["duplicate"]:  # BIMPORT-05: surface, never hide
                    duplicate.append({"path": str(file_path)})
                else:  # BIMPORT-06: real id + metadata
                    added.append(
                        {
                            "path": str(file_path),
                            "book_id": result["book_id"],
                            "book": result["book"],
                        }
                    )
            except CalibreMcpError as exc:  # BIMPORT-04: never aborts the batch
                failed.append({"path": str(file_path), "error": str(exc)})

        return {
            "status": "imported",
            "added": added,
            "duplicate": duplicate,
            "failed": failed,
            "backup": str(backup),
        }

    @staticmethod
    def _safe_scan(folder: Path) -> list[Path]:
        """Scan ``folder`` for ebook candidates, converting an ``OSError``
        (e.g. unreadable directory) into ``InvalidInputError`` so it surfaces
        cleanly through ``_map_errors`` (AD-021) rather than escaping unmapped.
        """
        try:
            return scan_ebook_files(folder)
        except OSError as exc:
            raise InvalidInputError(f"cannot scan directory {folder}: {exc}") from exc

    def remove_book(self, book_id: int, token: str | None = None) -> dict[str, Any]:
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

    def email_book(
        self,
        book_id: int,
        recipient: str,
        format: str | None = None,  # noqa: A002 - matches design/spec param name
        token: str | None = None,
    ) -> dict[str, Any]:
        """Email a book's file via the plan->confirm handshake (EMAIL-01, AD-012).

        Outward-facing, so it is gated like ``update_metadata``/``remove_book``.
        Plan step (no token): confirm the book exists, resolve the attachment
        format/file, validate the recipient shape, and return the
        recipient/format/subject/file plus a ``confirmation_token`` — nothing is
        sent. Apply step (token): verify the token, load SMTP config from env
        (``SmtpNotConfiguredError`` if unset, AC-6), then send via
        ``calibre-smtp``. No metadata mutation, so no backup is taken. The SMTP
        password is never included in the plan or the result (AC-5).
        """
        book = self._reader.get_book(book_id)  # exists-precheck, no send
        self._validate_recipient(recipient)
        attachment_format, attachment_path = self._resolve_email_attachment(
            book_id, format
        )
        subject = f"Sending you: {book.title}"
        payload = {"recipient": recipient, "format": attachment_format}

        if token is None:
            return {
                "status": "plan",
                "book_id": book_id,
                "recipient": recipient,
                "format": attachment_format,
                "subject": subject,
                "file": str(attachment_path),
                "confirmation_token": plan_token(_OP_EMAIL, book_id, payload),
            }

        verify(_OP_EMAIL, book_id, payload, token)  # mismatch -> raise, no send
        smtp_cfg = load_smtp_config()  # AC-6: raises SmtpNotConfiguredError if unset
        self._mailer.send(
            smtp_cfg,
            smtp_cfg.sender,
            recipient,
            subject,
            f"Sent via calibre-mcp: {book.title}",
            attachment_path,
        )
        return {
            "status": "sent",
            "book_id": book_id,
            "recipient": recipient,
            "format": attachment_format,
        }

    def _resolve_email_attachment(
        self, book_id: int, format: str | None  # noqa: A002
    ) -> tuple[str, Path]:
        """Pick the attachment format: explicit ``format``, else device-preference
        order (EMAIL-01 AC-3); refuse before sending if none is attachable (AC-7).
        """
        files = self._reader.format_files(book_id)
        if format is not None:
            wanted = format.upper()
            if wanted not in files:
                raise InvalidInputError(
                    f"book {book_id} has no {wanted} file to attach"
                )
            return wanted, files[wanted]

        for candidate in EMAIL_FORMAT_PREFERENCE:
            if candidate in files:
                return candidate, files[candidate]
        raise InvalidInputError(f"book {book_id} has no file to attach")

    @staticmethod
    def _validate_recipient(recipient: str) -> None:
        """Reject an obviously-malformed recipient before any send (basic shape)."""
        if (
            not isinstance(recipient, str)
            or "@" not in recipient
            or recipient.startswith("@")
            or recipient.endswith("@")
        ):
            raise InvalidInputError(f"invalid recipient email address: {recipient!r}")

    @staticmethod
    def _validate_bulk_input(
        book_ids: list[int], fields: dict[str, Any], list_mode: str
    ) -> None:
        """Reject invalid bulk input before any token/backup/write (BEDIT-06).

        Checks, in order: ``list_mode`` is one of ``LIST_MODES``; ``book_ids``
        is non-empty with no duplicates and every element a non-bool ``int``;
        ``fields`` is non-empty and passes the single-book whitelist/value
        checks; ``list_mode`` in ``{add, remove}`` requires at least one
        ``LIST_FIELDS`` member in ``fields`` (a mode with nothing to apply to
        is a caller error, spec edge case).
        """
        if list_mode not in LIST_MODES:
            allowed = ", ".join(sorted(LIST_MODES))
            raise InvalidInputError(
                f"list_mode {list_mode!r} not allowed; allowed: {allowed}"
            )

        if not book_ids:
            raise InvalidInputError("book_ids must not be empty")
        if any(
            isinstance(book_id, bool) or not isinstance(book_id, int)
            for book_id in book_ids
        ):
            raise InvalidInputError(f"book_ids must all be integers, got {book_ids!r}")
        if len(set(book_ids)) != len(book_ids):
            raise InvalidInputError(
                f"book_ids must not contain duplicates: {book_ids!r}"
            )

        if not fields:
            raise InvalidInputError("fields must not be empty")
        CalibreLibrary._validate_edit_fields(fields)

        if list_mode in ("add", "remove") and not (set(fields) & LIST_FIELDS):
            raise InvalidInputError(
                f"list_mode {list_mode!r} requires at least one list field in "
                f"fields ({sorted(LIST_FIELDS)}); got {sorted(fields)}"
            )

    def _bulk_plan_entry(
        self, book_id: int, fields: dict[str, Any], list_mode: str
    ) -> dict[str, Any]:
        """Build one book's plan row (BEDIT-01, BEDIT-08 AC-4).

        A vanished id is reported ``found: False`` (no diff, no abort — it
        lands in ``failed`` at apply, BEDIT-04). ``proposed`` is the resolved
        set under ``list_mode``, so the review matches exactly what is written.
        """
        try:
            book = self._reader.get_book(book_id)
        except BookNotFoundError:
            return {"book_id": book_id, "found": False}

        resolved = resolve_fields(book, fields, list_mode)
        return {
            "book_id": book_id,
            "found": True,
            "diff": self._build_diff(book, resolved),
        }

    @staticmethod
    def _validate_edit_fields(fields: dict[str, Any]) -> None:
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
    def _shape_duplicate_group(group: list[Book]) -> dict[str, Any]:
        """Shape one duplicate group for output (ORG-01)."""
        primary_author = group[0].authors[0] if group[0].authors else ""
        return {
            "key": {"title": group[0].title, "author": primary_author},
            "books": [
                {
                    "id": book.id,
                    "title": book.title,
                    "authors": book.authors,
                    "formats": book.formats,
                }
                for book in group
            ],
        }

    @staticmethod
    def _build_diff(book: Book, fields: dict[str, Any]) -> dict[str, Any]:
        """Build a per-field current->proposed diff for the plan (EDIT-01)."""
        return {
            name: {"current": getattr(book, name), "proposed": value}
            for name, value in fields.items()
        }
