"""Integration tests for the CalibreLibrary facade — enrich_from_identifier (ENRICH-01).

Derived from spec.md P1 ACs (LOOKUP-01..09), asserting spec-defined outcomes. A
per-test ``scratch_library`` (temp dir) is seeded and an injected fake enricher
stands in for Open Library, so ZERO real network traffic occurs (spec test-safety
rule) — the facade orchestration is what's under test, not the HTTP client.

LOOKUP-01: has ISBN + record -> advisory proposal, library byte-for-byte unchanged.
LOOKUP-02 (revised by ENRICH-04 TSEARCH-06): no ISBN and no usable title ->
           found:false, no network (enricher never called).
LOOKUP-03: unknown id -> BookNotFoundError; non-int -> InvalidInputError (pre-network).
LOOKUP-04: comments proposal sourced from the record's (work) description.
LOOKUP-05: an already-present target field is skipped, never proposed.
LOOKUP-06: no cover + record cover -> downloaded local_path; has cover -> cover:null.
LOOKUP-07: known ISBN, no record -> found:false, not an error.
LOOKUP-08: a fetch_record source error propagates (facade does not swallow it).
LOOKUP-09: a cover download failure is non-fatal (metadata proposal still returned).

ENRICH-04 (title/author search fallback when there is no usable ISBN):
TSEARCH-01: search by title + primary author ("Unknown" author omitted); never
            for a book with an ISBN.
TSEARCH-03: a high match proposes the work description (comments) + cover only.
TSEARCH-04: a non-high best match is reported, never proposed or downloaded.
TSEARCH-05: no candidates -> found:false, "no record at source", match:null.
TSEARCH-07: a search failure propagates; a failed description is non-fatal.
TSEARCH-08: read-only (metadata.db unchanged).
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
from calibre_mcp.openlibrary_client import OpenLibraryRecord, SearchCandidate

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
        candidates: list[SearchCandidate] | None = None,
        search_error: Exception | None = None,
        description: str | None = None,
    ) -> None:
        self._record = record
        self._cover_bytes = cover_bytes
        self._cover_error = cover_error
        self._cover_dir = cover_dir
        self._fetch_error = fetch_error
        self.fetch_calls = 0
        self.download_calls = 0
        self.received_isbn: str | None = None
        self._candidates = candidates or []
        self._search_error = search_error
        self._description = description
        self.search_calls: list[tuple[str, str | None]] = []
        self.description_calls: list[str] = []

    def search_works(self, title: str, author: str | None) -> list[SearchCandidate]:
        self.search_calls.append((title, author))
        if self._search_error is not None:
            raise self._search_error
        return self._candidates

    def fetch_work_description(self, work_key: str) -> str | None:
        self.description_calls.append(work_key)
        return self._description

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
def test_isbn_with_hyphens_and_lowercase_x_is_normalized_end_to_end(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # spec Edge Case + LOOKUP-01: a hyphenated, lower-case-`x` ISBN is normalized
    # (strip non-alphanumerics, upper-case) both when queried and when echoed back.
    book_id = _seed_empty_book(scratch_library)
    runner = CalibredbRunner(scratch_library)
    runner.set_metadata(book_id, {"identifiers": "isbn:0-8044-2957-x"})
    enricher = _FakeEnricher(OpenLibraryRecord("Bantam", "2009", "Desc", None))
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert enricher.received_isbn == "080442957X"  # normalized before the lookup
    assert result["identifier_used"] == {"type": "isbn", "value": "080442957X"}


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
def test_no_isbn_and_no_usable_title_returns_found_false_without_network(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # LOOKUP-02 revised by TSEARCH-06: only a google id AND Calibre's "Unknown"
    # title placeholder -> nothing to look up or search -> no network at all.
    book_id = _seed_empty_book(scratch_library, title="Unknown")
    runner = CalibredbRunner(scratch_library)
    runner.set_metadata(book_id, {"identifiers": "google:abc123"})
    enricher = _FakeEnricher(OpenLibraryRecord("X", "Y", "Z", None))
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert result == {
        "book_id": book_id,
        "found": False,
        "reason": "no usable identifier (ISBN) or title",
    }
    assert enricher.fetch_calls == 0  # no ISBN lookup
    assert enricher.search_calls == []  # and no search


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


# ------------------------------------------- ENRICH-04: title/author search


_HOBBIT_KEY = "/works/OL262758W"
_HOBBIT_COVER = "https://covers.openlibrary.org/b/id/14627509-L.jpg"


def _hobbit() -> SearchCandidate:
    return SearchCandidate(
        work_key=_HOBBIT_KEY,
        title="The Hobbit",
        authors=["J.R.R. Tolkien"],
        cover_url=_HOBBIT_COVER,
    )


def _seed_titled_book(scratch_library: Path, title: str, author: str) -> int:
    book_id = _seed_empty_book(scratch_library, title=title)
    CalibredbRunner(scratch_library).set_metadata(book_id, {"authors": [author]})
    return book_id


@pytest.mark.integration
def test_search_is_never_used_for_a_book_with_an_isbn(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # TSEARCH-01 Must-not: the ISBN path runs unchanged.
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "J. R. R. Tolkien")
    _set_isbn(scratch_library, book_id)
    enricher = _FakeEnricher(None, candidates=[_hobbit()])
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert enricher.search_calls == []
    assert result["reason"] == "no record at source"


@pytest.mark.integration
def test_search_sends_title_and_primary_author(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # TSEARCH-01: no ISBN -> search by title + primary author.
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "J. R. R. Tolkien")
    enricher = _FakeEnricher(None)
    facade._enricher = enricher

    facade.enrich_from_identifier(book_id)

    assert enricher.search_calls == [("The Hobbit", "J. R. R. Tolkien")]


@pytest.mark.integration
def test_search_omits_unknown_author(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # TSEARCH-01: Calibre's "Unknown" author placeholder is not sent.
    book_id = _seed_empty_book(scratch_library, title="The Hobbit")
    enricher = _FakeEnricher(None)
    facade._enricher = enricher

    facade.enrich_from_identifier(book_id)

    assert enricher.search_calls == [("The Hobbit", None)]


@pytest.mark.integration
def test_high_match_proposes_description_and_cover_only(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # TSEARCH-03 + TSEARCH-08: exact payload; publisher/pubdate never proposed
    # even though the book lacks both; nothing written to the library.
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "J. R. R. Tolkien")
    enricher = _FakeEnricher(
        None,
        candidates=[_hobbit()],
        description="A hobbit goes on an adventure.",
        cover_bytes=_CANNED_COVER,
        cover_dir=tmp_path,
    )
    facade._enricher = enricher
    before = _db_digest(scratch_library)

    result = facade.enrich_from_identifier(book_id)

    cover = result.pop("cover")
    assert result == {
        "book_id": book_id,
        "found": True,
        "source": "openlibrary",
        "identifier_used": None,
        "match": {
            "method": "search",
            "confidence": "high",
            "title": "The Hobbit",
            "authors": ["J.R.R. Tolkien"],
            "work_key": _HOBBIT_KEY,
            "title_similarity": 1.0,
            "author_similarity": 1.0,
        },
        "proposed": {"comments": "A hobbit goes on an adventure."},
        "skipped_present": [],
    }
    assert cover["url"] == _HOBBIT_COVER
    assert Path(cover["local_path"]).read_bytes() == _CANNED_COVER
    assert enricher.description_calls == [_HOBBIT_KEY]
    assert _db_digest(scratch_library) == before


@pytest.mark.integration
def test_high_match_never_overwrites_present_comments(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # TSEARCH-03: comments proposed only when missing (gap-only, LOOKUP-05).
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "J. R. R. Tolkien")
    CalibredbRunner(scratch_library).set_metadata(
        book_id,
        {"comments": "Mine.", "cover": str(_valid_cover_png(tmp_path / "c.png"))},
    )
    enricher = _FakeEnricher(None, candidates=[_hobbit()], description="Theirs.")
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert result["found"] is True
    assert result["proposed"] == {}
    assert "comments" in result["skipped_present"]
    assert result["cover"] is None  # the book already has one


@pytest.mark.integration
def test_non_high_match_is_reported_but_never_proposed(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # TSEARCH-04: same title, another author -> medium: shown, not proposed;
    # no description fetched, no cover downloaded.
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "Someone Else")
    enricher = _FakeEnricher(None, candidates=[_hobbit()], description="Theirs.")
    facade._enricher = enricher

    result = facade.enrich_from_identifier(book_id)

    assert result["found"] is False
    assert result["reason"] == "no confident match"
    assert result["match"]["confidence"] == "medium"
    assert result["match"]["work_key"] == _HOBBIT_KEY
    assert "proposed" not in result
    assert enricher.description_calls == []
    assert enricher.download_calls == 0


@pytest.mark.integration
def test_no_candidates_is_no_record_with_null_match(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # TSEARCH-05.
    book_id = _seed_titled_book(scratch_library, "Obscure Book", "Nobody")
    facade._enricher = _FakeEnricher(None, candidates=[])

    result = facade.enrich_from_identifier(book_id)

    assert result == {
        "book_id": book_id,
        "found": False,
        "reason": "no record at source",
        "match": None,
    }


@pytest.mark.integration
def test_search_failure_propagates_as_source_error(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # TSEARCH-07: a search transport/parse failure is a tool error.
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "J. R. R. Tolkien")
    facade._enricher = _FakeEnricher(
        None, search_error=EnrichmentSourceError("down", "url")
    )

    with pytest.raises(EnrichmentSourceError):
        facade.enrich_from_identifier(book_id)


@pytest.mark.integration
def test_failed_description_still_returns_the_cover_proposal(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # TSEARCH-07: a missing/failed description is non-fatal.
    book_id = _seed_titled_book(scratch_library, "The Hobbit", "J. R. R. Tolkien")
    facade._enricher = _FakeEnricher(
        None,
        candidates=[_hobbit()],
        description=None,
        cover_bytes=_CANNED_COVER,
        cover_dir=tmp_path,
    )

    result = facade.enrich_from_identifier(book_id)

    assert result["found"] is True
    assert result["proposed"] == {}
    assert result["cover"]["url"] == _HOBBIT_COVER
