"""Integration tests for the CalibreLibrary facade — enrich_from_identifier (ENRICH-01).

Derived from spec.md P1 ACs (LOOKUP-01..09), asserting spec-defined outcomes. A
per-test ``scratch_library`` (temp dir) is seeded and an injected fake enricher
stands in for Open Library, so ZERO real network traffic occurs (spec test-safety
rule) — the facade orchestration is what's under test, not the HTTP client.

LOOKUP-01: has ISBN + record -> advisory proposal, library byte-for-byte unchanged.
LOOKUP-02: no ISBN -> found:false, no network (enricher never called).
LOOKUP-03: unknown id -> BookNotFoundError; non-int -> InvalidInputError (pre-network).
LOOKUP-04: comments proposal sourced from the record's (work) description.
LOOKUP-05: an already-present target field is skipped, never proposed.
LOOKUP-06: no cover + record cover -> downloaded local_path; has cover -> cover:null.
LOOKUP-07: known ISBN, no record -> found:false, not an error.
LOOKUP-08: a fetch_record source error propagates (facade does not swallow it).
LOOKUP-09: a cover download failure is non-fatal (metadata proposal still returned).
"""

from __future__ import annotations

import hashlib
import os
import re
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import (
    BookNotFoundError,
    EnrichmentSourceError,
    InvalidInputError,
)
from calibre_mcp.library import CalibreLibrary
from calibre_mcp.openlibrary_client import OpenLibraryRecord

_RAW_ISBN = "978-0-553-29335-7"
_NORMALIZED_ISBN = "9780553293357"
_COVER_URL = "https://covers.openlibrary.org/b/id/12345-L.jpg"
_CANNED_COVER = b"\x89PNG\r\n\x1a\n-canned-open-library-cover-"


def _valid_cover_png(path: Path, width: int = 100, height: int = 150) -> Path:
    """Write a real multi-pixel PNG (stdlib only) — Calibre rejects a 1x1 image."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress((b"\x00" + b"\xff\xff\xff" * width) * height)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    return path


def _seed_empty_book(scratch_library: Path, title: str = "Book") -> int:
    result = subprocess.run(
        ["calibredb", "add", "--empty", "--title", title,
         "--with-library", str(scratch_library)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    output = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"Added book ids:\s*([\d,]+)", output)
    assert match is not None
    return int(match.group(1).split(",")[0])


def _set_isbn(scratch_library: Path, book_id: int) -> None:
    runner = CalibredbRunner(scratch_library)
    runner.set_metadata(book_id, {"identifiers": f"isbn:{_RAW_ISBN}"})


class _FakeEnricher:
    """A duck-typed stand-in for OpenLibraryClient — no network, records calls."""

    def __init__(
        self,
        record: OpenLibraryRecord | None,
        *,
        cover_bytes: bytes | None = None,
        cover_error: Exception | None = None,
        cover_dir: Path | None = None,
        fetch_error: Exception | None = None,
    ) -> None:
        self._record = record
        self._cover_bytes = cover_bytes
        self._cover_error = cover_error
        self._cover_dir = cover_dir
        self._fetch_error = fetch_error
        self.fetch_calls = 0
        self.download_calls = 0
        self.received_isbn: str | None = None

    def fetch_record(self, isbn: str) -> OpenLibraryRecord | None:
        self.fetch_calls += 1
        self.received_isbn = isbn
        if self._fetch_error is not None:
            raise self._fetch_error
        return self._record

    def download_cover(self, cover_url: str, dest_dir: Path | None = None) -> Path:
        self.download_calls += 1
        if self._cover_error is not None:
            raise self._cover_error
        fd, path = tempfile.mkstemp(prefix="fake-enrich-", dir=self._cover_dir)
        with os.fdopen(fd, "wb") as handle:
            handle.write(self._cover_bytes or b"")
        return Path(path)


@pytest.fixture
def config(scratch_library: Path, tmp_path: Path) -> Config:
    return Config(
        library_path=scratch_library,
        db_path=scratch_library / "metadata.db",
        backup_root=tmp_path / "backups",
    )


@pytest.fixture
def facade(config: Config) -> CalibreLibrary:
    return CalibreLibrary(config)


def _db_digest(scratch_library: Path) -> str:
    return hashlib.sha256((scratch_library / "metadata.db").read_bytes()).hexdigest()


@pytest.mark.integration
def test_happy_path_proposes_gaps_and_leaves_library_unchanged(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-01/04 + normalization edge: gaps proposed, comments from description,
    # ISBN echoed normalized, and metadata.db is byte-for-byte unchanged.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(
        OpenLibraryRecord("Bantam", "April 2009", "A sprawling space opera.", None)
    )
    before = _db_digest(scratch_library)

    result = facade.enrich_from_identifier(book_id)

    assert result == {
        "book_id": book_id,
        "found": True,
        "source": "openlibrary",
        "identifier_used": {"type": "isbn", "value": _NORMALIZED_ISBN},
        "proposed": {
            "comments": "A sprawling space opera.",
            "publisher": "Bantam",
            "pubdate": "April 2009",
        },
        "skipped_present": [],
        "cover": None,
    }
    assert _db_digest(scratch_library) == before  # LOOKUP-01: nothing written


@pytest.mark.integration
def test_no_isbn_returns_found_false_and_never_calls_enricher(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-02 + spec test (a): only a google id -> no-network found:false.
    book_id = _seed_empty_book(scratch_library)
    runner = CalibredbRunner(scratch_library)
    runner.set_metadata(book_id, {"identifiers": "google:abc123"})
    enricher = _FakeEnricher(OpenLibraryRecord("X", "Y", "Z", None))
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert result == {
        "book_id": book_id,
        "found": False,
        "reason": "no usable identifier (ISBN)",
    }
    assert enricher.fetch_calls == 0  # no network call


@pytest.mark.integration
def test_unknown_id_raises_book_not_found_before_enricher(
    facade: CalibreLibrary
) -> None:
    # LOOKUP-03 + spec test (b): unknown id fails before any network call.
    enricher = _FakeEnricher(OpenLibraryRecord("X", "Y", "Z", None))
    facade._enricher = enricher

    with pytest.raises(BookNotFoundError):
        facade.enrich_from_identifier(999999)
    assert enricher.fetch_calls == 0


@pytest.mark.integration
def test_non_int_id_raises_invalid_input(facade: CalibreLibrary) -> None:
    # LOOKUP-03: a non-integer id is rejected at the boundary, pre-network.
    with pytest.raises(InvalidInputError):
        facade.enrich_from_identifier("not-an-int")  # type: ignore[arg-type]


@pytest.mark.integration
def test_present_fields_go_to_skipped_not_proposed(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-05 + spec test (c): populated target fields are skipped, not proposed.
    book_id = _seed_empty_book(scratch_library)
    runner = CalibredbRunner(scratch_library)
    _set_isbn(scratch_library, book_id)
    runner.set_metadata(book_id, {"publisher": "Existing Pub", "comments": "Notes"})
    runner.set_metadata(book_id, {"pubdate": "2015-06-15"})
    facade._enricher = _FakeEnricher(
        OpenLibraryRecord("Bantam", "April 2009", "New desc", None)
    )

    result = facade.enrich_from_identifier(book_id)

    assert result["proposed"] == {}
    assert result["skipped_present"] == ["comments", "publisher", "pubdate"]


@pytest.mark.integration
def test_no_cover_downloads_and_returns_local_path_with_canned_bytes(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # LOOKUP-06: no cover + record cover -> a downloaded local file with the bytes.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(
        OpenLibraryRecord("Bantam", "2009", "Desc", _COVER_URL),
        cover_bytes=_CANNED_COVER,
        cover_dir=tmp_path,
    )

    cover = facade.enrich_from_identifier(book_id)["cover"]

    assert cover is not None
    assert cover["url"] == _COVER_URL
    assert Path(cover["local_path"]).read_bytes() == _CANNED_COVER


@pytest.mark.integration
def test_book_with_cover_yields_cover_null_and_no_download(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # LOOKUP-06 + spec test (d): a book that already has a cover -> cover:null.
    book_id = _seed_empty_book(scratch_library, "Covered")
    runner = CalibredbRunner(scratch_library)
    runner.set_metadata(book_id, {"cover": str(_valid_cover_png(tmp_path / "c.png"))})
    _set_isbn(scratch_library, book_id)
    enricher = _FakeEnricher(
        OpenLibraryRecord("Bantam", "2009", "Desc", _COVER_URL), cover_dir=tmp_path
    )
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert result["cover"] is None
    assert enricher.download_calls == 0  # don't propose replacing an existing cover


@pytest.mark.integration
def test_no_record_at_source_returns_found_false(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-07 + spec test (e): known ISBN but no record -> a clean negative.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(None)

    result = facade.enrich_from_identifier(book_id)

    assert result == {
        "book_id": book_id,
        "found": False,
        "identifier_used": {"type": "isbn", "value": _NORMALIZED_ISBN},
        "reason": "no record at source",
    }


@pytest.mark.integration
def test_fetch_record_source_error_propagates(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-08: a metadata-fetch source failure is NOT swallowed by the facade.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(None, fetch_error=EnrichmentSourceError("offline"))

    with pytest.raises(EnrichmentSourceError):
        facade.enrich_from_identifier(book_id)


@pytest.mark.integration
def test_cover_download_failure_is_non_fatal(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-09: a failed cover download keeps the metadata proposal; cover reports it.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(
        OpenLibraryRecord("Bantam", "2009", "Desc", _COVER_URL),
        cover_error=EnrichmentSourceError("cover 403"),
    )

    result = facade.enrich_from_identifier(book_id)

    assert result["proposed"] == {
        "comments": "Desc",
        "publisher": "Bantam",
        "pubdate": "2009",
    }
    assert result["cover"]["url"] == _COVER_URL
    assert result["cover"]["local_path"] is None
    assert "error" in result["cover"]


@pytest.mark.integration
def test_all_present_with_cover_is_nothing_to_fill(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # Edge: all target fields present + a cover -> found:true, proposed:{}, all
    # three skipped, cover:null.
    book_id = _seed_empty_book(scratch_library, "Full")
    runner = CalibredbRunner(scratch_library)
    runner.set_metadata(book_id, {"cover": str(_valid_cover_png(tmp_path / "c.png"))})
    _set_isbn(scratch_library, book_id)
    runner.set_metadata(book_id, {"publisher": "Pub", "comments": "Notes"})
    runner.set_metadata(book_id, {"pubdate": "2015-06-15"})
    facade._enricher = _FakeEnricher(
        OpenLibraryRecord("Bantam", "2009", "Desc", _COVER_URL), cover_dir=tmp_path
    )

    result = facade.enrich_from_identifier(book_id)

    assert result["found"] is True
    assert result["proposed"] == {}
    assert result["skipped_present"] == ["comments", "publisher", "pubdate"]
    assert result["cover"] is None
