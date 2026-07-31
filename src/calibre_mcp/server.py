"""FastMCP tool surface — the 6 P1 tools (T10).

FastMCP owns the stdio transport. Each ``@mcp.tool()`` narrows its inputs at the
boundary, delegates to the ``CalibreLibrary`` facade (never ``sqlite3`` /
``subprocess`` directly — the enforced invariant), shapes an LLM-friendly dict,
and surfaces every failure as an explicit tool error — never a silent wrong or
empty result (spec §Error Handling; design error-handling table).

stdout hygiene (critical, design Risks): stdout is the stdio MCP framing channel.
All logging goes to STDERR only and this module never prints to stdout.
"""

from __future__ import annotations

import functools
import logging
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from .config import load_config
from .errors import CalibreMcpError
from .library import CalibreLibrary
from .sqlite_reader import Book

# Logging to STDERR only — stdout is the stdio MCP channel and must stay clean.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("calibre_mcp")

mcp = FastMCP("calibre")

# Built lazily so config is read/validated at startup or on first tool call, and
# so tests can point the server at a scratch library via the environment.
_library: CalibreLibrary | None = None


def _get_library() -> CalibreLibrary:
    """Return the facade, building it from validated startup config (CFG-01).

    A missing/invalid ``CALIBRE_LIBRARY_PATH`` raises ``ConfigError`` here, which
    ``_map_errors`` turns into a clear tool error naming the offending path.
    """
    global _library
    if _library is None:
        _library = CalibreLibrary(load_config())
    return _library


def _map_errors[T](fn: Callable[..., T]) -> Callable[..., T]:
    """Map every known failure to an explicit ``ToolError`` (design error table).

    Guarantees a failure is never returned as a silent wrong/empty result: each
    ``CalibreMcpError`` (config, not-found, invalid input, locked, calibredb,
    confirmation) surfaces as a clear tool error the host/LLM can act on.
    Generic over the wrapped tool's return type (``dict`` for every existing
    tool, ``Image | dict`` for ``read_cover``, AD-024) — a pure typing change,
    behavior is unchanged: it only ever re-raises what ``fn`` returns/raises.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return fn(*args, **kwargs)
        except CalibreMcpError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def _map_resource_errors(fn: Callable[[], dict]) -> Callable[[], dict]:
    """Map every known read failure to an explicit ``ResourceError`` (AC-4).

    Mirrors ``_map_errors`` for the resource surface: a ``CalibreMcpError``
    (e.g. bad config) or a raw ``sqlite3.Error``/``OSError`` (e.g. missing or
    corrupt ``metadata.db``) surfaces as a named ``ResourceError`` instead of a
    silent empty/wrong profile. Catching these does not violate the "no SQL
    outside the read layer" invariant (AD-001) — no SQL is issued here.
    """

    @functools.wraps(fn)
    def wrapper() -> dict:
        try:
            return fn()
        except CalibreMcpError as exc:
            raise ResourceError(str(exc)) from exc
        except (sqlite3.Error, OSError) as exc:
            raise ResourceError(str(exc)) from exc

    return wrapper


def _book_to_dict(book: Book) -> dict:
    """Shape a ``Book`` dataclass as a JSON-friendly dict for tool output."""
    return asdict(book)


def _jsonify(result: dict) -> dict:
    """Convert any ``Book`` embedded in a facade mutation result to a dict."""
    book = result.get("book")
    if isinstance(book, Book):
        return {**result, "book": _book_to_dict(book)}
    return result


@mcp.tool()
@_map_errors
def search_books(query: str) -> dict:
    """Search the library with Calibre's own query grammar (SEARCH-01/03).

    Resolves matching book ids via ``calibredb search "query"``, then hydrates
    their full metadata from ``metadata.db``. An empty/blank query returns an
    empty result set (not an error). Examples: ``author:asimov``, ``tag:scifi``,
    ``series:Dune``, ``title:"Foundation"``.
    """
    books = _get_library().search_books(query)
    return {"count": len(books), "books": [_book_to_dict(b) for b in books]}


@mcp.tool()
@_map_errors
def list_books(limit: int | None = None, offset: int = 0, sort: str = "id") -> dict:
    """List a page of books ordered by ``sort`` (SEARCH-02).

    ``sort`` is one of: id, title, authors, pubdate, timestamp. ``limit``
    defaults to and is capped at 50; use ``offset`` to page. ``total`` in the
    response is the library's full book count, independent of paging — use it
    to know how many ``offset`` pages to request. Pure SQLite and
    lock-independent, so this is the fallback when the Calibre GUI holds the
    library lock.
    """
    library = _get_library()
    books = library.list_books(limit=limit, offset=offset, sort=sort)
    return {
        "count": len(books),
        "offset": offset,
        "total": library.count_books(),
        "books": [_book_to_dict(b) for b in books],
    }


@mcp.tool()
@_map_errors
def get_book(book_id: int) -> dict:
    """Return one book's full metadata record (VIEW-01/02/03).

    A non-integer id is rejected as invalid input before any DB access (VIEW-03);
    an id that does not exist returns a clear "book not found" error naming the id
    (VIEW-02) — never an empty or misleading record.
    """
    return _book_to_dict(_get_library().get_book(book_id))


@mcp.tool()
@_map_errors
def read_cover(book_id: int) -> Any:
    """Return a book's cover as viewable image content (RCOVER-01..05).

    A book with a cover returns the cover itself as viewable image content
    (``image/jpeg``) so the host can actually see it -- not just a path. A book
    with no cover returns ``{book_id, has_cover: false, cover_path: null}`` --
    not an error. An unknown id raises a "book not found" error; a book whose
    metadata claims a cover but whose ``cover.jpg`` is missing on disk raises
    invalid input (a real metadata<->disk inconsistency), mirroring
    ``format_files`` rather than a silent "no cover" degrade. Pure read: no
    write, no ``calibredb`` call, no network.
    """
    # SPEC_DEVIATION: design.md specifies `-> Image | dict` as the return
    # annotation. With the installed mcp SDK (1.28.1) that crashes tool
    # *registration*: building the union's structured-output schema calls
    # pydantic's create_model() unconditionally (even for
    # structured_output=False) and pydantic has no schema for Image.
    # Reason: `-> Any` produces the identical runtime wire behavior --
    # FastMCP's content conversion dispatches on the actual returned value's
    # type, not the static annotation, and output_schema is None either way
    # (verified) -- while avoiding the crash.
    result = _get_library().read_cover(book_id)
    return Image(path=result["cover_path"]) if result["has_cover"] else result


@mcp.tool()
@_map_errors
def update_metadata(
    book_id: int,
    fields: dict[str, Any],
    confirmation_token: str | None = None,
) -> dict:
    """Edit a book's metadata via a two-step plan->confirm handshake (EDIT-01..07).

    HOST: surface the returned plan (the per-field current->proposed diff) to the
    USER and only re-call with ``confirmation_token`` after they approve.

    Without a token: nothing is written; returns the diff plus a deterministic
    ``confirmation_token`` for that exact change. With a matching token: backs up
    ``metadata.db`` first, applies the fields via ``calibredb set_metadata``, then
    returns the re-read record. A mismatched token is refused. Editable fields:
    title, authors, tags, series, series_index, rating (0-10, i.e. 0-5 stars x2),
    comments, publisher, pubdate, languages. A ``calibredb`` failure surfaces its
    stderr and never reports success.
    """
    result = _get_library().update_metadata(
        book_id, fields, token=confirmation_token
    )
    return _jsonify(result)


@mcp.tool()
@_map_errors
def update_metadata_bulk(
    book_ids: list[int],
    fields: dict[str, Any],
    list_mode: str = "replace",
    confirmation_token: str | None = None,
) -> dict:
    """Broadcast one set of field changes to many books, two-step plan->confirm
    (BEDIT-01..09).

    HOST: surface the returned per-book plan (each book's current->proposed
    diff) to the USER and only re-call with ``confirmation_token`` after they
    approve.

    Without a token: nothing is written; returns a diff per book (or
    ``found: false`` for a vanished id) plus one deterministic
    ``confirmation_token`` covering the whole batch. With a matching token:
    backs up ``metadata.db`` ONCE, then applies every book best-effort — a
    single book's failure (vanished id, calibredb error) never voids the
    batch; the result reports ``applied`` (with each book's re-read affected
    fields) and ``failed`` (with the error) separately, so a partial failure
    is never reported as a fake "all succeeded". A mismatched token is
    refused before any write.

    ``list_mode`` applies to the list-valued fields (authors, tags,
    languages): ``replace`` (default) OVERWRITES each book's field with
    exactly the supplied values — a footgun for broadcast tagging; ``add``
    unions the supplied values into each book's existing ones (nothing
    lost); ``remove`` subtracts the supplied values from each book's existing
    ones (missing values ignored). Note Calibre may re-normalize written list
    values (case-folding/dedup), so a re-read may not byte-match the plan.
    """
    return _get_library().update_metadata_bulk(
        book_ids, fields, list_mode=list_mode, token=confirmation_token
    )


@mcp.tool()
@_map_errors
def rename_author(
    old_name: str,
    new_name: str,
    confirmation_token: str | None = None,
) -> dict:
    """Rename an author across every book they're credited on, two-step
    plan->confirm (ORGN-01, ARENAME-01..08).

    HOST: surface the returned per-book plan (each book's ``authors``
    current->proposed) to the USER and only re-call with
    ``confirmation_token`` after they approve.

    ``old_name`` is matched EXACTLY (case-sensitive) against every book
    credited to that author. Without a token: nothing is written; discovers
    every affected book and returns its resolved ``authors`` diff plus one
    deterministic ``confirmation_token`` covering the whole batch. If
    ``old_name`` matches no author, or ``new_name`` is blank/equal to
    ``old_name``, the call is rejected before any backup.

    With a matching token: backs up ``metadata.db`` ONCE, then applies every
    affected book best-effort in ``book_id`` order. The rename is
    CO-AUTHOR-SAFE: only ``old_name`` is replaced on each book — every other
    credited author and their order is preserved (never an overwrite of the
    whole author list). Renaming onto a name already used by another author
    MERGES the two (a book crediting both collapses to a single entry,
    deduped). A single book's failure never voids the batch; the result
    reports ``applied`` (with each book's re-read resulting ``authors``) and
    ``failed`` (with the error) separately — never a false "all renamed". A
    mismatched token is refused before any write.
    """
    return _jsonify(
        _get_library().rename_author(old_name, new_name, token=confirmation_token)
    )


@mcp.tool()
@_map_errors
def rename_tag(
    old_tag: str,
    new_tag: str,
    confirmation_token: str | None = None,
) -> dict:
    """Rename a tag across every book carrying it, two-step plan->confirm
    (ORGN-02, TRENAME-01..08).

    HOST: surface the returned per-book plan (each book's ``tags``
    current->proposed) to the USER and only re-call with
    ``confirmation_token`` after they approve.

    ``old_tag`` is matched EXACTLY (case-sensitive) against every book carrying
    that tag. Without a token: nothing is written; discovers every affected book
    and returns its resolved ``tags`` diff plus one deterministic
    ``confirmation_token`` covering the whole batch. If ``old_tag`` matches no
    tag, or ``new_tag`` is blank/equal to ``old_tag``, the call is rejected
    before any backup.

    With a matching token: backs up ``metadata.db`` ONCE, then applies every
    affected book best-effort in ``book_id`` order. The rename is
    OTHER-TAG-SAFE: only ``old_tag`` is replaced on each book — every other tag
    is preserved (never an overwrite of the whole tag set). Renaming onto a tag
    already in use MERGES the two (a book carrying both collapses to a single
    entry, deduped). Tags are a set, so re-read ordering is Calibre's, not the
    plan's. A single book's failure never voids the batch; the result reports
    ``applied`` (with each book's re-read resulting ``tags``) and ``failed``
    (with the error) separately — never a false "all renamed". A mismatched
    token is refused before any write.
    """
    return _jsonify(
        _get_library().rename_tag(old_tag, new_tag, token=confirmation_token)
    )


@mcp.tool()
@_map_errors
def rename_series(
    old_series: str,
    new_series: str,
    confirmation_token: str | None = None,
) -> dict:
    """Rename a series across every book in it, two-step plan->confirm
    (ORGN-04, SRENAME-01..08).

    HOST: surface the returned per-book plan (each book's ``series``
    current->proposed, with its unchanged ``series_index``) to the USER and
    only re-call with ``confirmation_token`` after they approve.

    ``old_series`` is matched EXACTLY (case-sensitive) against every book
    whose series is that name. Without a token: nothing is written; discovers
    every affected book and returns its ``series`` diff plus one deterministic
    ``confirmation_token`` covering the whole batch. If ``old_series`` matches
    no book, or ``new_series`` is blank/equal to ``old_series``, the call is
    rejected before any backup.

    With a matching token: backs up ``metadata.db`` ONCE, then applies every
    affected book best-effort in ``book_id`` order. The rename writes the
    ``series`` field ONLY — each book's ``series_index`` (its position in the
    series) is PRESERVED, never reset or renumbered. Renaming onto a series
    name already in use MERGES the two (each book keeps its own index; index
    collisions are left as-is, not renumbered). A single book's failure never
    voids the batch; the result reports ``applied`` (with each book's re-read
    resulting ``series``/``series_index``) and ``failed`` (with the error)
    separately — never a false "all renamed". A mismatched token is refused
    before any write.
    """
    return _jsonify(
        _get_library().rename_series(old_series, new_series, token=confirmation_token)
    )


@mcp.tool()
@_map_errors
def add_book(path: str) -> dict:
    """Import an ebook file into the library by local filesystem path (ADD-01..04).

    Validates the path is an existing file before any subprocess (ADD-02), backs
    up ``metadata.db``, then imports via ``calibredb add`` and returns the new
    book id plus its parsed metadata. A duplicate is surfaced honestly (never a
    fake id); a ``calibredb`` failure surfaces its stderr.
    """
    return _jsonify(_get_library().add_book(path))


@mcp.tool()
@_map_errors
def import_folder(path: str) -> dict:
    """Import every ebook file under a directory, recursively (BULK-03).

    ADDITIVE, NO confirmation token (like ``add_book``). Discovers every
    ebook-candidate file under ``path`` — recursive (includes subfolders),
    case-insensitive whitelist of unambiguous ebook formats — silently
    ignoring non-ebook and hidden/dotfiles (they are never reported). Max 500
    ebook candidates per call; a larger tree is rejected as invalid input
    before any backup or import. Backs up ``metadata.db`` ONCE before the
    batch.

    Best-effort, honest THREE-bucket result — every candidate lands in
    exactly one: ``added`` (with its new ``book_id`` and parsed metadata);
    ``duplicate`` (already in the library — surfaced, never re-added, never a
    fake id); or ``failed`` (a real per-file ``calibredb`` error). A single
    file failing never aborts the batch and is never reported as a fake "all
    imported".
    """
    result = _get_library().import_folder(path)
    return {
        **result,
        "added": [
            {**entry, "book": _book_to_dict(entry["book"])} for entry in result["added"]
        ],
    }


@mcp.tool()
@_map_errors
def remove_book(book_id: int, confirmation_token: str | None = None) -> dict:
    """Remove a book — RECOVERABLE — via a two-step review->confirm (REM-01..06).

    Removal is RECOVERABLE: the book's files are copied to ``backups/trash/`` and
    the book is sent to Calibre's recycle bin (never permanently deleted). It
    still requires the two-step review->confirm.

    HOST: surface the returned review (title/authors/formats + the recoverable
    note) to the USER and only re-call with ``confirmation_token`` after they
    approve.

    Without a token: nothing is deleted; returns the book's details plus a
    deterministic ``confirmation_token``. With a matching token: copies files to
    trash, backs up ``metadata.db``, sends the book to the recycle bin, then
    reports the trash location. A mismatched token or an unknown id is refused
    with a clear error — never a false "removed".
    """
    return _jsonify(_get_library().remove_book(book_id, token=confirmation_token))


@mcp.tool()
@_map_errors
def merge_duplicate_group(
    survivor_id: int,
    loser_ids: list[int],
    confirmation_token: str | None = None,
) -> dict:
    """Merge a duplicate group onto a caller-chosen survivor, two-step
    plan->confirm (ORGN-03, MERGE-01..08).

    HOST: surface the returned plan (per-loser formats to add vs. already
    present, and that every loser will be recoverably deleted) to the USER and
    only re-call with ``confirmation_token`` after they approve.

    You choose ``survivor_id`` (the record to keep) and ``loser_ids`` (the
    records to fold into it) — typically from a ``find_duplicates`` group. The
    merge is FORMATS-ONLY: the survivor's metadata (title, authors, tags, …)
    is never touched, only its file formats change. Without a token: nothing
    is written; returns, per loser, ``formats_to_add`` vs.
    ``formats_already_present`` on the survivor, plus one deterministic
    ``confirmation_token`` covering the whole batch. ``survivor_id``/loser ids
    must all exist; ``loser_ids`` must be non-empty, without duplicates, and
    must not include ``survivor_id`` — any violation is rejected before any
    backup.

    With a matching token: backs up ``metadata.db`` ONCE, then processes each
    loser best-effort in ascending id order. DATA-SAFE ORDERING: a loser's
    formats are attached onto the survivor first (``add_format
    --dont-replace`` — the survivor's existing copy always wins on conflict,
    never duplicated); the loser is deleted — RECOVERABLY (trash copy +
    recycle bin, never permanent) — only after every one of its formats is
    confirmed on the survivor. If attaching a loser's format fails, that loser
    is left untouched and reported in ``failed``; the batch continues with the
    remaining losers — never a false "all merged". The result reports
    ``merged`` (each loser's formats added + trash location) and ``failed``
    separately, plus the survivor's re-read resulting ``formats`` (the proven
    union). A mismatched token is refused before any write.
    """
    return _jsonify(
        _get_library().merge_duplicate_group(
            survivor_id, loser_ids, token=confirmation_token
        )
    )


@mcp.tool()
@_map_errors
def convert_book(book_id: int, target_format: str) -> dict:
    """Convert a book to ``target_format`` via ``ebook-convert`` (CONV-01).

    ADDITIVE: the book's existing format(s) are kept — after a successful
    convert the book has both the old and the new format. Refuses (no
    overwrite) when the book already has ``target_format``. Supported target
    formats: epub, azw3, mobi, pdf. Backs up ``metadata.db`` before attaching
    the new format. A conversion failure (bad/corrupt source) surfaces its
    stderr and adds nothing.
    """
    return _jsonify(_get_library().convert_book(book_id, target_format))


@mcp.tool()
@_map_errors
def convert_book_bulk(book_ids: list[int], target_format: str) -> dict:
    """Convert many books to one ``target_format`` via ``ebook-convert`` (BULK-02).

    ADDITIVE: each book keeps its existing format(s) and gains ``target_format``;
    NO confirmation token (like ``convert_book``). Broadcasts one target to every
    id in ``book_ids`` — max 50 per call (a larger batch is rejected as invalid
    input). Supported targets: epub, azw3, mobi, pdf.

    Best-effort, honest THREE-bucket result — every book lands in exactly one:
    ``converted`` (with its re-read resulting ``formats``); ``skipped`` (a BENIGN
    no-op — the book already has the target, or has no source file — this is NOT
    a failure); or ``failed`` (a real per-book error: corrupt/unsupported source,
    or an id that does not exist). A single book failing never aborts the batch
    and is never reported as a fake "all succeeded"; every id is accounted for
    (converted + skipped + failed == book_ids). Backs up ``metadata.db`` once
    before the batch. Conversions run sequentially and can be slow for a large
    batch.
    """
    return _get_library().convert_book_bulk(book_ids, target_format)


@mcp.tool()
@_map_errors
def find_duplicates() -> dict:
    """Find likely-duplicate books by normalized (title, primary author) (ORG-01).

    READ-ONLY advisory report: groups (size >= 2) of books that look like
    duplicates. Never mutates the library and never auto-merges — the host/user
    decides what, if anything, to do with each group. No duplicates found
    returns an empty group set, not an error.
    """
    return _get_library().find_duplicates()


@mcp.tool()
@_map_errors
def email_book(
    book_id: int,
    recipient: str,
    format: str | None = None,  # noqa: A002 - matches design/spec param name
    confirmation_token: str | None = None,
) -> dict:
    """Email a book's file to ``recipient`` via ``calibre-smtp`` (EMAIL-01).

    OUTWARD-FACING: uses a two-step plan->confirm handshake. HOST: surface the
    returned plan (recipient, chosen format, subject, and file) to the USER and
    only re-call with ``confirmation_token`` after they approve — nothing is
    sent until then.

    ``format`` picks the attachment explicitly; otherwise it is chosen by
    device-preference order (epub, azw3, mobi, pdf). Requires
    ``CALIBRE_MCP_SMTP_*`` environment variables to be set (relay, username,
    password, sender); if unset, the apply step fails naming the missing
    variable and sends nothing. A book with no attachable format is refused
    before sending.
    """
    return _get_library().email_book(
        book_id, recipient, format=format, token=confirmation_token
    )


@mcp.resource(
    "calibre://library/stats",
    name="library_stats",
    mime_type="application/json",
)
@_map_resource_errors
def library_stats_resource() -> dict:
    """Aggregate baseline profile of the library (STATS-01): totals, format/
    language mix, metadata completeness, identifier types, top authors/tags,
    and data-quality flags (including duplicate-title groups). Read-only,
    parameter-free, and lock-independent — known on connect without a tool
    call.
    """
    return _get_library().library_stats()


def main() -> None:
    """Entry point: validate config at startup (CFG-01), then serve over stdio."""
    _get_library()  # fail fast with a clear ConfigError if the library path is bad
    logger.info("calibre-mcp starting on stdio")
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
