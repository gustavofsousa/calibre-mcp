"""Integration tests for CalibreLibrary.enrich_missing (ENRICH-03 batch review).

A per-test ``scratch_library`` is seeded and a routing fake enricher (keyed by
normalized ISBN) stands in for Open Library — ZERO real network traffic and ZERO
real-library writes (both spec test-safety rules). Derived from spec ENRICH3-01..09,
asserting spec-defined outcomes.

ENRICH3-01/02: sweep selects isbn+gap books, returns verbatim ENRICH-01 payload
               + status, writes nothing (metadata.db byte-for-byte unchanged).
ENRICH3-03:    found+nothing-to-fill -> no_new_data; no record -> no_record.
ENRICH3-04:    one book's EnrichmentSourceError -> that item status:error,
               and the sweep continues.
ENRICH3-05/06: candidate_count/processed reported; empty / offset-past-end
               -> not an error.
ENRICH3-07:    default cap (25) applied when no limit given (effective + reader arg).
ENRICH3-08:    bad bound rejected BEFORE any selection/network call.
ENRICH3-09:    sequential, exactly one lookup per processed candidate, in id order.

ENRICH-04 TSEARCH-09 (revises ENRICH3-01): ISBN-less titled books missing comments
or a cover are swept via title/author search; only a high match is `proposed`, a
lower one lands in the new `no_confident_match` bucket.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import EnrichmentSourceError, InvalidInputError
from calibre_mcp.library import ENRICH_BATCH_DEFAULT, CalibreLibrary
from calibre_mcp.openlibrary_client import OpenLibraryRecord, SearchCandidate
from sample_books import write_cover_png

_COVER_URL = "https://covers.openlibrary.org/b/id/12345-L.jpg"


def _seed_empty_book(scratch_library: Path, title: str) -> int:
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


class _RoutingEnricher:
    """Per-ISBN stand-in for OpenLibraryClient — no network, records call order."""

    def __init__(
        self,
        records: dict[str, OpenLibraryRecord | Exception | None],
        cover_dir: Path,
        candidates_by_title: dict[str, list[SearchCandidate]] | None = None,
    ) -> None:
        self._records = records
        self._cover_dir = cover_dir
        self._candidates_by_title = candidates_by_title or {}
        self.searched_titles: list[str] = []
        self.fetch_calls = 0
        self.received_isbns: list[str] = []

    def fetch_record(self, isbn: str) -> OpenLibraryRecord | None:
        self.fetch_calls += 1
        self.received_isbns.append(isbn)
        value = self._records.get(isbn)
        if isinstance(value, Exception):
            raise value
        return value

    def search_works(self, title: str, author: str | None) -> list[SearchCandidate]:
        self.searched_titles.append(title)
        return self._candidates_by_title.get(title, [])

    def fetch_work_description(self, work_key: str) -> str | None:
        return f"Description of {work_key}"

    def download_cover(self, cover_url: str, dest_dir: Path | None = None) -> Path:
        fd, path = tempfile.mkstemp(prefix="fake-batch-", dir=self._cover_dir)
        with os.fdopen(fd, "wb") as handle:
            handle.write(b"\x89PNG\r\n-canned-cover-")
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
def test_sweep_returns_proposals_isolates_errors_and_writes_nothing(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-01/02/04: A,B propose (verbatim ENRICH-01 payload), E errors and the
    # sweep still returns A,B; C (complete) and D (no isbn, and nothing a search
    # could fill — TSEARCH-09) are not candidates.
    runner = CalibredbRunner(scratch_library)

    a = _seed_empty_book(scratch_library, "A all gaps")
    runner.set_metadata(a, {"identifiers": "isbn:9780000000001"})
    b = _seed_empty_book(scratch_library, "B missing publisher")
    runner.set_metadata(b, {"identifiers": "isbn:9780000000002",
                            "comments": "Notes", "pubdate": "2015-06-15"})
    c = _seed_empty_book(scratch_library, "C complete")  # excluded
    runner.set_metadata(c, {"identifiers": "isbn:9780000000003",
                            "comments": "Notes", "publisher": "Pub",
                            "pubdate": "2015-06-15"})
    d = _seed_empty_book(scratch_library, "D no isbn")  # excluded
    runner.set_metadata(d, {
        "identifiers": "google:xyz", "comments": "Notes",
        "cover": str(write_cover_png(tmp_path / "d.png")),
    })
    e = _seed_empty_book(scratch_library, "E raises")
    runner.set_metadata(e, {"identifiers": "isbn:9780000000005"})

    facade._enricher = _RoutingEnricher(
        {
            "9780000000001": OpenLibraryRecord(
                "Bantam", "2009", "A space opera.", _COVER_URL
            ),
            "9780000000002": OpenLibraryRecord("OnlyPub", None, None, None),
            "9780000000005": EnrichmentSourceError("offline"),
        },
        cover_dir=tmp_path,
    )
    before = _db_digest(scratch_library)

    result = facade.enrich_missing()

    assert result["candidate_count"] == 3
    assert result["processed"] == 3
    assert result["summary"] == {
        "proposed": 2, "no_new_data": 0, "no_record": 0,
        "no_confident_match": 0, "error": 1
    }
    by_id = {r["book_id"]: r for r in result["results"]}
    assert by_id[a]["status"] == "proposed"
    assert by_id[a]["proposed"] == {
        "comments": "A space opera.", "publisher": "Bantam", "pubdate": "2009"
    }
    assert by_id[a]["cover"]["local_path"] is not None  # verbatim ENRICH-01 payload
    assert by_id[b]["status"] == "proposed"
    assert by_id[b]["proposed"] == {"publisher": "OnlyPub"}
    assert by_id[b]["skipped_present"] == ["comments", "pubdate"]
    assert by_id[e] == {
        "book_id": e, "status": "error",
        "reason": "enrichment source failed: offline",
    }
    assert _db_digest(scratch_library) == before  # ENRICH3-01: nothing written


@pytest.mark.integration
def test_limit_processes_only_the_first_window(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-05/07: limit:1 -> only the first candidate looked up, count still full.
    runner = CalibredbRunner(scratch_library)
    first = _seed_empty_book(scratch_library, "first")
    runner.set_metadata(first, {"identifiers": "isbn:9780000000011"})
    second = _seed_empty_book(scratch_library, "second")
    runner.set_metadata(second, {"identifiers": "isbn:9780000000012"})
    enricher = _RoutingEnricher(
        {
            "9780000000011": OpenLibraryRecord("P1", None, None, None),
            "9780000000012": OpenLibraryRecord("P2", None, None, None),
        },
        cover_dir=tmp_path,
    )
    facade._enricher = enricher

    result = facade.enrich_missing(limit=1)

    assert result["candidate_count"] == 2
    assert result["processed"] == 1
    assert result["limit"] == 1
    assert [r["book_id"] for r in result["results"]] == [first]
    assert enricher.received_isbns == ["9780000000011"]  # only the first, once


@pytest.mark.integration
def test_offset_past_end_is_empty_not_error(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-06: paging past the candidates -> empty results, zeroed summary.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "only one")
    runner.set_metadata(book, {"identifiers": "isbn:9780000000021"})
    enricher = _RoutingEnricher({}, cover_dir=tmp_path)
    facade._enricher = enricher

    result = facade.enrich_missing(offset=5)

    assert result["candidate_count"] == 1
    assert result["processed"] == 0
    assert result["results"] == []
    assert result["summary"] == {
        "proposed": 0, "no_new_data": 0, "no_record": 0,
        "no_confident_match": 0, "error": 0
    }
    assert enricher.fetch_calls == 0


@pytest.mark.integration
def test_no_new_data_and_no_record_statuses(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-03: found-but-empty -> no_new_data; no record at source -> no_record.
    runner = CalibredbRunner(scratch_library)
    empty_hit = _seed_empty_book(scratch_library, "found nothing")
    runner.set_metadata(empty_hit, {"identifiers": "isbn:9780000000031"})
    missing = _seed_empty_book(scratch_library, "no record")
    runner.set_metadata(missing, {"identifiers": "isbn:9780000000032"})
    facade._enricher = _RoutingEnricher(
        {
            "9780000000031": OpenLibraryRecord(None, None, None, None),  # found, empty
            "9780000000032": None,  # no record at source
        },
        cover_dir=tmp_path,
    )

    result = facade.enrich_missing()

    by_id = {r["book_id"]: r for r in result["results"]}
    assert by_id[empty_hit]["status"] == "no_new_data"
    assert by_id[missing]["status"] == "no_record"
    assert result["summary"] == {
        "proposed": 0, "no_new_data": 1, "no_record": 1,
        "no_confident_match": 0, "error": 0
    }


@pytest.mark.integration
def test_no_candidates_returns_empty_result(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-06: nothing to enrich -> empty results + zeroed summary, not an error.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "complete")
    runner.set_metadata(book, {"identifiers": "isbn:9780000000041",
                               "comments": "Notes", "publisher": "Pub",
                               "pubdate": "2015-06-15"})
    facade._enricher = _RoutingEnricher({}, cover_dir=tmp_path)

    result = facade.enrich_missing()

    assert result["candidate_count"] == 0
    assert result["processed"] == 0
    assert result["results"] == []


@pytest.mark.integration
def test_default_cap_is_applied_to_selection(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-07: no limit -> default cap (25) is the effective limit for selection.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "one")
    runner.set_metadata(book, {"identifiers": "isbn:9780000000051"})
    facade._enricher = _RoutingEnricher(
        {"9780000000051": OpenLibraryRecord("P", None, None, None)}, cover_dir=tmp_path
    )
    seen_limits: list[int] = []
    real = facade._reader.enrichable_candidates

    def spy(limit: int, offset: int) -> tuple[int, list[int]]:
        seen_limits.append(limit)
        return real(limit, offset)

    facade._reader.enrichable_candidates = spy  # type: ignore[method-assign]

    result = facade.enrich_missing()

    assert result["limit"] == ENRICH_BATCH_DEFAULT == 25
    assert seen_limits == [25]  # the cap is what selection was actually asked for


@pytest.mark.integration
def test_default_cap_truncates_the_sweep_end_to_end(
    facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # ENRICH3-07 (spec P2 independent test): more candidates than the cap ->
    # exactly the cap is processed while candidate_count reports the full total.
    # Proven end-to-end with a small cap so the suite stays fast.
    import calibre_mcp.library as lib
    monkeypatch.setattr(lib, "ENRICH_BATCH_DEFAULT", 2)
    runner = CalibredbRunner(scratch_library)
    isbns = ["9780000000081", "9780000000082", "9780000000083"]
    for n, isbn in enumerate(isbns):
        book = _seed_empty_book(scratch_library, f"s{n}")
        runner.set_metadata(book, {"identifiers": f"isbn:{isbn}"})
    facade._enricher = _RoutingEnricher(
        {isbn: OpenLibraryRecord("P", None, None, None) for isbn in isbns},
        cover_dir=tmp_path,
    )

    result = facade.enrich_missing()

    assert result["limit"] == 2
    assert result["processed"] == 2
    assert result["candidate_count"] == 3


@pytest.mark.integration
@pytest.mark.parametrize(
    ("kwargs"),
    [{"limit": 0}, {"limit": -1}, {"limit": 1000}, {"offset": -1}, {"limit": True}],
)
def test_bad_bounds_rejected_before_any_selection_or_network(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path, kwargs: dict
) -> None:
    # ENRICH3-08: an invalid bound raises before selection or a single network call.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "candidate")
    runner.set_metadata(book, {"identifiers": "isbn:9780000000061"})
    enricher = _RoutingEnricher(
        {"9780000000061": OpenLibraryRecord("P", None, None, None)}, cover_dir=tmp_path
    )
    facade._enricher = enricher
    selection_calls: list[int] = []
    real = facade._reader.enrichable_candidates

    def spy(limit: int, offset: int) -> tuple[int, list[int]]:
        selection_calls.append(limit)
        return real(limit, offset)

    facade._reader.enrichable_candidates = spy  # type: ignore[method-assign]

    with pytest.raises(InvalidInputError):
        facade.enrich_missing(**kwargs)
    assert enricher.fetch_calls == 0  # no network
    assert selection_calls == []  # rejected before selection


@pytest.mark.integration
def test_sweep_is_sequential_one_lookup_per_candidate(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH3-09: exactly one lookup per processed candidate, in id order.
    runner = CalibredbRunner(scratch_library)
    isbns = ["9780000000071", "9780000000072", "9780000000073"]
    ids = []
    for n, isbn in enumerate(isbns):
        book = _seed_empty_book(scratch_library, f"c{n}")
        runner.set_metadata(book, {"identifiers": f"isbn:{isbn}"})
        ids.append(book)
    enricher = _RoutingEnricher(
        {isbn: OpenLibraryRecord("P", None, None, None) for isbn in isbns},
        cover_dir=tmp_path,
    )
    facade._enricher = enricher

    result = facade.enrich_missing()

    assert result["processed"] == 3
    assert enricher.fetch_calls == 3  # one lookup per candidate
    assert enricher.received_isbns == isbns  # id order preserved


@pytest.mark.integration
def test_isbn_less_books_are_swept_and_only_high_matches_are_proposed(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # TSEARCH-09: high -> proposed (description + cover); same title but another
    # author -> no_confident_match (reported, not proposed); nothing written.
    runner = CalibredbRunner(scratch_library)
    confident = _seed_empty_book(scratch_library, "The Hobbit")
    runner.set_metadata(confident, {"authors": ["J. R. R. Tolkien"]})
    doubtful = _seed_empty_book(scratch_library, "Dune")
    runner.set_metadata(doubtful, {"authors": ["Someone Else"]})
    facade._enricher = _RoutingEnricher(
        {},
        tmp_path,
        candidates_by_title={
            "The Hobbit": [
                SearchCandidate(
                    "/works/OL1W", "The Hobbit", ["J.R.R. Tolkien"], _COVER_URL
                )
            ],
            "Dune": [SearchCandidate("/works/OL2W", "Dune", ["Frank Herbert"], None)],
        },
    )
    before = _db_digest(scratch_library)

    result = facade.enrich_missing()

    by_id = {item["book_id"]: item for item in result["results"]}
    assert by_id[confident]["status"] == "proposed"
    assert by_id[confident]["proposed"] == {"comments": "Description of /works/OL1W"}
    assert by_id[confident]["match"]["confidence"] == "high"
    assert by_id[doubtful]["status"] == "no_confident_match"
    assert by_id[doubtful]["match"]["work_key"] == "/works/OL2W"
    assert "proposed" not in by_id[doubtful]
    assert result["summary"] == {
        "proposed": 1,
        "no_new_data": 0,
        "no_record": 0,
        "no_confident_match": 1,
        "error": 0,
    }
    assert _db_digest(scratch_library) == before


@pytest.mark.integration
def test_high_match_without_description_on_a_covered_book_is_no_new_data(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # Spec edge case: the work has no description and the book already has a
    # cover -> found:true with an empty proposal -> no_new_data in the batch.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "The Hobbit")
    runner.set_metadata(book, {
        "authors": ["J. R. R. Tolkien"],
        "cover": str(write_cover_png(tmp_path / "c.png")),
    })
    enricher = _RoutingEnricher(
        {},
        tmp_path,
        candidates_by_title={
            "The Hobbit": [
                SearchCandidate(
                    "/works/OL1W", "The Hobbit", ["J.R.R. Tolkien"], _COVER_URL
                )
            ]
        },
    )
    enricher.fetch_work_description = lambda work_key: None  # type: ignore[method-assign]
    facade._enricher = enricher

    result = facade.enrich_missing()

    assert result["results"][0]["status"] == "no_new_data"
    assert result["results"][0]["proposed"] == {}
    assert result["results"][0]["cover"] is None
    assert result["summary"]["no_new_data"] == 1
