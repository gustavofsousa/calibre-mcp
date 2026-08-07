"""Integration tests for SqliteReader.enrichable_candidates (ENRICH-03 selection).

Seed a per-test ``scratch_library`` and assert which books the candidate query
selects, the total count, and the id-ordered limit/offset paging. Derived from
spec ENRICH3-01/05/06/07 — a candidate carries a non-blank ISBN AND is missing at
least one enrichable field (comments/publisher/placeholder-or-NULL pubdate); a
complete book or one with no ISBN is excluded.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.sqlite_reader import SqliteReader


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


def _reader(scratch_library: Path) -> SqliteReader:
    return SqliteReader(scratch_library / "metadata.db", scratch_library)


@pytest.mark.integration
def test_selects_only_books_with_isbn_and_a_gap(scratch_library: Path) -> None:
    # ENRICH3-01: has-isbn ∧ a gap -> candidate; complete or no-isbn -> excluded.
    runner = CalibredbRunner(scratch_library)

    a = _seed_empty_book(scratch_library, "A gaps+isbn")  # empty => all gaps
    runner.set_metadata(a, {"identifiers": "isbn:9780553293357"})

    b = _seed_empty_book(scratch_library, "B missing publisher")
    runner.set_metadata(b, {
        "identifiers": "isbn:9780000000002",
        "comments": "Has notes", "pubdate": "2015-06-15",
    })

    c = _seed_empty_book(scratch_library, "C complete")  # not a candidate
    runner.set_metadata(c, {"identifiers": "isbn:9780000000003",
                            "comments": "Notes", "publisher": "Pub",
                            "pubdate": "2015-06-15"})

    d = _seed_empty_book(scratch_library, "D no isbn")  # not a candidate (no isbn)
    runner.set_metadata(d, {"identifiers": "google:abc123"})

    total, ids = _reader(scratch_library).enrichable_candidates(limit=25, offset=0)

    assert ids == [a, b]  # id-ordered, only the isbn+gap books
    assert total == 2


@pytest.mark.integration
def test_placeholder_pubdate_alone_makes_a_candidate(scratch_library: Path) -> None:
    # ENRICH3-01 edge: comments+publisher set but placeholder pubdate -> a gap.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "placeholder pubdate")  # 0101-01-01
    runner.set_metadata(book, {
        "identifiers": "isbn:9780000000009",
        "comments": "Notes", "publisher": "Pub",
    })

    total, ids = _reader(scratch_library).enrichable_candidates(limit=25, offset=0)

    assert ids == [book]
    assert total == 1


@pytest.mark.integration
def test_limit_and_offset_page_deterministically(scratch_library: Path) -> None:
    # ENRICH3-05/07: id-ordered window; total counts all candidates, not just the page.
    runner = CalibredbRunner(scratch_library)
    ids_seeded = []
    for n in range(4):
        book = _seed_empty_book(scratch_library, f"gap {n}")
        runner.set_metadata(book, {"identifiers": f"isbn:978000000010{n}"})
        ids_seeded.append(book)
    ids_seeded.sort()

    reader = _reader(scratch_library)
    total, page1 = reader.enrichable_candidates(limit=2, offset=0)
    _, page2 = reader.enrichable_candidates(limit=2, offset=2)

    assert total == 4
    assert page1 == ids_seeded[:2]
    assert page2 == ids_seeded[2:]


@pytest.mark.integration
def test_offset_past_end_returns_empty_not_error(scratch_library: Path) -> None:
    # ENRICH3-06: paging past the candidate count is a normal empty result.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "only one")
    runner.set_metadata(book, {"identifiers": "isbn:9780000000111"})

    total, ids = _reader(scratch_library).enrichable_candidates(limit=25, offset=5)

    assert total == 1
    assert ids == []


@pytest.mark.integration
def test_no_candidates_returns_zero(scratch_library: Path) -> None:
    # ENRICH3-06: nothing matches -> (0, []), not an error.
    runner = CalibredbRunner(scratch_library)
    book = _seed_empty_book(scratch_library, "complete")
    runner.set_metadata(book, {"identifiers": "isbn:9780000000222",
                               "comments": "Notes", "publisher": "Pub",
                               "pubdate": "2015-06-15"})

    total, ids = _reader(scratch_library).enrichable_candidates(limit=25, offset=0)

    assert total == 0
    assert ids == []
