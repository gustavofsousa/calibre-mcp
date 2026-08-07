"""Integration tests for ENRICH-02 — routing enrich_from_identifier's proposal
through the existing update_metadata/set_cover plan->confirm gates (AD-012,
AD-025). No new mutation path: this proves the CHAIN (enrich -> update_metadata
-> set_cover) round-trips unchanged, per spec.md.

A per-test ``scratch_library`` (temp dir) is seeded and an injected fake
enricher stands in for Open Library — ZERO real network traffic occurs (spec
test-safety rule).

ENRICH2-01/02: proposed text fields plan+apply through update_metadata unchanged.
ENRICH2-03:    an empty proposed dict plans fine (empty diff) but FAILS at
               apply -- calibredb rejects a zero-field set_metadata call
               (CalibredbError), verified empirically. The host's job is to
               skip the call entirely, not rely on a graceful no-op.
ENRICH2-04:    update_metadata's own diff/skip behavior is reused unchanged --
               proven by re-running enrichment after apply and seeing the
               now-populated fields land in skipped_present, not proposed.
ENRICH2-05/06: the downloaded cover plans+applies through set_cover unchanged.
ENRICH2-07:    a null cover.local_path is never passed to set_cover -- the
               host-side guard is the only thing preventing set_cover's own
               Path(None) TypeError (documented, not newly guarded).
"""

from __future__ import annotations

import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import CalibredbError
from calibre_mcp.library import CalibreLibrary
from calibre_mcp.openlibrary_client import OpenLibraryRecord

_RAW_ISBN = "978-0-553-29335-7"
_COVER_URL = "https://covers.openlibrary.org/b/id/12345-L.jpg"


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
    """Duck-typed OpenLibraryClient stand-in — no network, records calls."""

    def __init__(
        self,
        record: OpenLibraryRecord | None,
        *,
        cover_png_source: Path | None = None,
    ) -> None:
        self._record = record
        self._cover_png_source = cover_png_source
        self.download_calls = 0

    def fetch_record(self, isbn: str) -> OpenLibraryRecord | None:
        return self._record

    def download_cover(self, cover_url: str, dest_dir: Path | None = None) -> Path:
        self.download_calls += 1
        assert self._cover_png_source is not None
        dest = (dest_dir or self._cover_png_source.parent) / "downloaded-cover.png"
        dest.write_bytes(self._cover_png_source.read_bytes())
        return dest


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


@pytest.mark.integration
def test_proposed_text_fields_apply_through_update_metadata_plan_then_confirm(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # ENRICH2-01/02: enrich_from_identifier's `proposed` dict fed verbatim into
    # update_metadata's plan step reflects those exact values in the diff, and
    # applying it writes exactly those values (re-read matches).
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(  # type: ignore[assignment]
        OpenLibraryRecord("Bantam", "April 2009", "A sprawling space opera.", None)
    )

    lookup = facade.enrich_from_identifier(book_id)
    proposed = lookup["proposed"]
    assert proposed == {
        "comments": "A sprawling space opera.",
        "publisher": "Bantam",
        "pubdate": "April 2009",
    }

    plan = facade.update_metadata(book_id, fields=proposed)
    assert plan["status"] == "plan"
    for field, value in proposed.items():
        assert plan["diff"][field]["proposed"] == value

    applied = facade.update_metadata(
        book_id, fields=proposed, token=plan["confirmation_token"]
    )
    assert applied["status"] == "applied"
    book = applied["book"]
    assert book.comments == proposed["comments"]
    assert book.publisher == proposed["publisher"]
    # calibredb normalizes a partial date string into a full ISO datetime --
    # verified empirically (pre-existing calibredb behavior, not ENRICH-02's).
    assert book.pubdate == "2009-04-15 00:00:00+00:00"


@pytest.mark.integration
def test_update_metadata_empty_fields_fails_at_apply_not_a_silent_noop(
    facade: CalibreLibrary
) -> None:
    # ENRICH2-03: an empty `proposed` (nothing missing, or found:false) is
    # accepted by update_metadata's plan step (empty diff) but its apply step
    # raises CalibredbError -- verified empirically, calibredb rejects a
    # zero-field set_metadata call. This is why the host must skip the call
    # entirely rather than relying on the server to no-op gracefully.
    book_id = _seed_empty_book_local(facade)
    plan = facade.update_metadata(book_id, fields={})
    assert plan["diff"] == {}
    with pytest.raises(CalibredbError):
        facade.update_metadata(book_id, fields={}, token=plan["confirmation_token"])


def _seed_empty_book_local(facade: CalibreLibrary) -> int:
    return _seed_empty_book(facade._config.library_path)


@pytest.mark.integration
def test_reenrichment_after_apply_reuses_update_metadata_skip_behavior_unchanged(
    facade: CalibreLibrary, scratch_library: Path
) -> None:
    # ENRICH2-04: after applying a proposal, re-running enrichment sees those
    # fields as already-present -- update_metadata's own diff/skip semantics
    # (LOOKUP-05) are reused as-is, no ENRICH-02-specific handling.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    facade._enricher = _FakeEnricher(  # type: ignore[assignment]
        OpenLibraryRecord("Bantam", "April 2009", "A sprawling space opera.", None)
    )

    first = facade.enrich_from_identifier(book_id)
    plan = facade.update_metadata(book_id, fields=first["proposed"])
    facade.update_metadata(
        book_id, fields=first["proposed"], token=plan["confirmation_token"]
    )

    second = facade.enrich_from_identifier(book_id)
    assert second["proposed"] == {}
    assert sorted(second["skipped_present"]) == ["comments", "pubdate", "publisher"]


@pytest.mark.integration
def test_downloaded_cover_applies_through_set_cover_plan_then_confirm(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
) -> None:
    # ENRICH2-05/06: enrich_from_identifier's cover.local_path fed verbatim
    # into set_cover's plan step reports current_has_cover:false (ENRICH-01
    # only ever proposes a cover for a book that lacks one), and applying it
    # results in has_cover:true, re-read from cover_file.
    book_id = _seed_empty_book(scratch_library)
    _set_isbn(scratch_library, book_id)
    source_png = _valid_cover_png(tmp_path / "source.png")
    facade._enricher = _FakeEnricher(  # type: ignore[assignment]
        OpenLibraryRecord("Bantam", "April 2009", "Desc", _COVER_URL),
        cover_png_source=source_png,
    )

    lookup = facade.enrich_from_identifier(book_id)
    assert lookup["cover"] is not None
    local_path = lookup["cover"]["local_path"]
    assert local_path is not None

    plan = facade.set_cover(book_id, image_path=local_path)
    assert plan["status"] == "plan"
    assert plan["current_has_cover"] is False

    applied = facade.set_cover(
        book_id, image_path=local_path, token=plan["confirmation_token"]
    )
    assert applied["status"] == "applied"
    assert applied["has_cover"] is True
    assert applied["cover_path"] is not None


@pytest.mark.integration
def test_null_cover_local_path_is_never_passed_to_set_cover(
    facade: CalibreLibrary
) -> None:
    # ENRICH2-07: a null cover.local_path (no cover at source, or a failed
    # download) has no valid interpretation for set_cover -- Path(None) raises
    # TypeError before any backup/write, which is why the host-side rule is
    # "never call set_cover with a null path" rather than a server guard.
    book_id = _seed_empty_book_local(facade)
    with pytest.raises(TypeError):
        facade.set_cover(book_id, image_path=None)  # type: ignore[arg-type]
