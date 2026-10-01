"""End-to-end tests for the FastMCP tool surface (T10).

Every tool is driven through FastMCP's in-process ``call_tool`` path — the same
registration + argument validation + error wrapping the real stdio transport
uses — so these assert the tool CONTRACT, not the facade internals. Derived from
spec ACs; asserted values are the spec-defined outcomes.

Test-safety rule (non-negotiable): write tools run only against a per-test
``scratch_library`` (temp dir). They NEVER touch the real library.

stdout hygiene (design Risks): stdout is the stdio MCP framing channel — one test
asserts a full round of tool calls writes NOTHING to stdout.

Coverage:
  SEARCH-01  search finds the seeded book (calibredb grammar -> hydrate).
  SEARCH-03  an empty query returns an empty set, not an error.
  SEARCH-02  list_books returns a page; an invalid sort is an explicit error.
  VIEW-01    get_book returns the full record.
  VIEW-02    an unknown id surfaces a clear "not found" tool error.
  VIEW-03    a non-integer id is rejected at the boundary (before DB access).
  RCOVER-01  read_cover returns viewable image content for a covered book.
  RCOVER-02  read_cover returns structured {has_cover: False} for no cover.
  RCOVER-03  read_cover unknown id surfaces a clear tool error.
  EDIT-01    update_metadata without a token returns a diff + token, no write.
  EDIT-02    update_metadata with a matching token applies and re-reads.
  EDIT-04    an out-of-whitelist field surfaces an explicit tool error.
  ADD-01     add_book imports and returns the new id + metadata.
  ADD-02     a nonexistent path is an explicit tool error.
  REM-01     remove_book without a token returns a recoverable review + token.
  REM-03     an unknown id surfaces a clear tool error (no false success).
  REM-06     the tool description states removal is recoverable + two-step.
  CFG-01     a missing library path surfaces a clear config tool error.
  CONV-01    convert_book adds a format additively; unsupported target is an error.
  ORG-01     find_duplicates returns groups; no duplicates -> empty group set.
  EMAIL-01   email_book plan->confirm two-step, sent via a stubbed calibre-smtp.
  MERGE-01   merge_duplicate_group plan->confirm, format union + recoverable delete.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import re
import shutil
import stat
import struct
import subprocess
import zlib
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ResourceError, ToolError
from mcp.types import ImageContent

from calibre_mcp import server
from calibre_mcp.calibre_smtp_runner import CalibreSmtpRunner
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import (
    SMTP_FROM_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_RELAY_ENV,
    SMTP_USERNAME_ENV,
)
from calibre_mcp.errors import EnrichmentSourceError
from calibre_mcp.openlibrary_client import OpenLibraryRecord
from sample_books import sample_epub_sources


def _valid_cover_png(path: Path, width: int = 100, height: int = 150) -> Path:
    """Write a real, multi-pixel PNG using only stdlib zlib/struct.

    Calibre re-encodes any valid input image to ``cover.jpg`` on
    ``set_metadata --field cover:``. A degenerate 1x1 PNG is rejected by Qt
    ("Image is empty"), so this emits a real WxH white image.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + b"\xff\xff\xff" * width  # filter byte + white pixels
    idat = zlib.compress(row * height)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def _seed_empty_book(library_path: Path, title: str = "Empty") -> int:
    # calibredb add --empty has no CalibredbRunner wrapper (adds no format /
    # embedded cover) -- needed so an "uncovered" book is deterministic, since
    # a real sample .epub's own embedded cover gets auto-extracted.
    result = subprocess.run(
        [
            "calibredb",
            "add",
            "--empty",
            "--title",
            title,
            "--with-library",
            str(library_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(
        r"Added book ids:\s*([\d,]+)", f"{result.stdout}\n{result.stderr}"
    )
    assert match is not None
    return int(match.group(1).split(",")[0])


def _seed_covered_book(library_path: Path, tmp_path: Path) -> int:
    book_id = _seed_empty_book(library_path, "Covered")
    cover_png = _valid_cover_png(tmp_path / "cover-source.png")
    CalibredbRunner(library_path).set_metadata(book_id, {"cover": str(cover_png)})
    return book_id


def _sample_epub(tmp_path: Path, name: str = "sample.epub") -> Path:
    """Copy one synthetic sample .epub into a temp path."""
    sources = sample_epub_sources()
    dest = tmp_path / name
    shutil.copy2(sources[0], dest)
    return dest


def _call(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke a registered tool in-process and parse its JSON result payload."""
    result = asyncio.run(server.mcp.call_tool(name, arguments))
    return json.loads(result[0].text)


def _call_raw(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke a registered tool in-process, returning the raw content blocks
    (for a tool whose result may not be JSON text, e.g. image content)."""
    return asyncio.run(server.mcp.call_tool(name, arguments))


def _read_resource(uri: str) -> Any:
    """Read a registered resource in-process and parse its JSON content."""
    result = asyncio.run(server.mcp.read_resource(uri))
    return json.loads(result[0].content)


@pytest.fixture
def env(scratch_library: Path, tmp_path: Path, monkeypatch) -> Path:
    """Point the server at a scratch library + isolated backup dir; reset cache."""
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(scratch_library))
    monkeypatch.setenv("CALIBRE_MCP_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(server, "_library", None)
    return scratch_library


@pytest.fixture
def seeded(env: Path, tmp_path: Path) -> int:
    """Seed one book directly via the runner and return its id."""
    result = CalibredbRunner(env).add(_sample_epub(tmp_path))
    assert result.book_id is not None
    return result.book_id


# ------------------------------------------------------------------- SEARCH


@pytest.mark.e2e
def test_search_books_finds_seeded_book(seeded: int):
    # SEARCH-01: calibredb grammar resolves ids, hydrated from metadata.db.
    payload = _call("search_books", {"query": "format:epub"})

    assert payload["count"] == 1
    assert payload["books"][0]["id"] == seeded
    assert "EPUB" in payload["books"][0]["formats"]


@pytest.mark.e2e
def test_search_books_empty_query_returns_empty_set(seeded: int):
    # SEARCH-03: an empty query is "no criteria" -> empty result, NOT an error.
    payload = _call("search_books", {"query": ""})

    assert payload["count"] == 0
    assert payload["books"] == []


# --------------------------------------------------------------------- LIST


@pytest.mark.e2e
def test_list_books_returns_seeded_book(seeded: int):
    # SEARCH-02: a page ordered by the requested field.
    payload = _call("list_books", {"sort": "title"})

    assert payload["count"] == 1
    assert payload["books"][0]["id"] == seeded
    assert payload["total"] == 1  # SEARCH-02: total is the library's full size


@pytest.mark.e2e
def test_list_books_invalid_sort_is_tool_error(env: Path):
    # SEARCH-02 boundary: an unsupported sort key surfaces an explicit error.
    with pytest.raises(ToolError) as excinfo:
        _call("list_books", {"sort": "bogus"})

    assert "invalid sort" in str(excinfo.value)


# --------------------------------------------------------------------- VIEW


@pytest.mark.e2e
def test_get_book_returns_full_record(seeded: int):
    # VIEW-01: full metadata record for a valid id.
    book = _call("get_book", {"book_id": seeded})

    assert book["id"] == seeded
    assert book["title"]
    assert "authors" in book and "tags" in book and "formats" in book


@pytest.mark.e2e
def test_get_book_unknown_id_is_tool_error(env: Path):
    # VIEW-02: an unknown id -> clear "not found" naming the id, not empty record.
    with pytest.raises(ToolError) as excinfo:
        _call("get_book", {"book_id": 999999})

    assert "999999" in str(excinfo.value)
    assert "not found" in str(excinfo.value)


@pytest.mark.e2e
def test_get_book_non_integer_id_rejected_at_boundary(env: Path):
    # VIEW-03: a non-integer id is rejected as invalid input at the boundary.
    with pytest.raises(ToolError) as excinfo:
        _call("get_book", {"book_id": "not-a-number"})

    assert "integer" in str(excinfo.value).lower()


# -------------------------------------------------------------------- COVER


@pytest.mark.e2e
def test_read_cover_covered_book_returns_viewable_image_content(
    env: Path, tmp_path: Path
):
    # RCOVER-01: a cover present -> image content, MIME image/jpeg, non-empty.
    book_id = _seed_covered_book(env, tmp_path)

    content = _call_raw("read_cover", {"book_id": book_id})

    assert len(content) == 1
    assert isinstance(content[0], ImageContent)
    assert content[0].mimeType == "image/jpeg"
    assert content[0].data


@pytest.mark.e2e
def test_read_cover_uncovered_book_returns_structured_no_cover(env: Path):
    # RCOVER-02: no cover -> structured {has_cover: False}, not an error/image.
    book_id = _seed_empty_book(env)

    payload = _call("read_cover", {"book_id": book_id})

    assert payload == {"book_id": book_id, "has_cover": False, "cover_path": None}


@pytest.mark.e2e
def test_read_cover_unknown_id_is_tool_error(env: Path):
    # RCOVER-03: an unknown id -> clear "not found" tool error naming the id.
    with pytest.raises(ToolError) as excinfo:
        _call("read_cover", {"book_id": 999999})

    assert "999999" in str(excinfo.value)


@pytest.mark.e2e
def test_set_cover_plan_then_apply_round_trip(env: Path, tmp_path: Path):
    # SCOVER-01/05: plan (no token) -> current_has_cover False + token, no
    # write; apply (token) -> has_cover flips True with a cover_path, and a
    # fresh get_book/read_cover confirms the change persisted.
    book_id = _seed_empty_book(env)
    image = _valid_cover_png(tmp_path / "cover.png")

    plan = _call("set_cover", {"book_id": book_id, "image_path": str(image)})
    assert plan["status"] == "plan"
    assert plan["current_has_cover"] is False
    assert plan["confirmation_token"]

    applied = _call(
        "set_cover",
        {
            "book_id": book_id,
            "image_path": str(image),
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert applied["status"] == "applied"
    assert applied["has_cover"] is True
    assert applied["cover_path"] and Path(applied["cover_path"]).name == "cover.jpg"
    # independent round trip through the read side of the tool surface
    # (RCOVER-01): a covered book returns viewable image content, not JSON.
    content = _call_raw("read_cover", {"book_id": book_id})
    assert len(content) == 1
    assert isinstance(content[0], ImageContent)
    assert content[0].mimeType == "image/jpeg"


@pytest.mark.e2e
def test_set_cover_missing_path_is_tool_error(env: Path, tmp_path: Path):
    # SCOVER-02: a nonexistent image_path is a clear tool error, not a silent
    # no-op -- calibredb itself would silently ignore a bad path.
    book_id = _seed_empty_book(env)
    missing = tmp_path / "does-not-exist.png"

    with pytest.raises(ToolError):
        _call("set_cover", {"book_id": book_id, "image_path": str(missing)})


# --------------------------------------------------------------------- EDIT


@pytest.mark.e2e
def test_update_metadata_plan_returns_diff_and_token_without_writing(seeded: int):
    # EDIT-01: no token -> diff + confirmation_token, nothing written.
    plan = _call(
        "update_metadata", {"book_id": seeded, "fields": {"tags": ["scifi"]}}
    )

    assert plan["status"] == "plan"
    assert plan["diff"]["tags"]["proposed"] == ["scifi"]
    assert plan["confirmation_token"]
    # library untouched
    assert _call("get_book", {"book_id": seeded})["tags"] == []


@pytest.mark.e2e
def test_update_metadata_apply_with_token_writes_and_rereads(seeded: int):
    # EDIT-02: matching token -> apply via calibredb, return the re-read record.
    plan = _call(
        "update_metadata", {"book_id": seeded, "fields": {"tags": ["scifi"]}}
    )

    applied = _call(
        "update_metadata",
        {
            "book_id": seeded,
            "fields": {"tags": ["scifi"]},
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert applied["status"] == "applied"
    assert applied["book"]["tags"] == ["scifi"]
    # persisted and visible through a fresh read
    assert _call("get_book", {"book_id": seeded})["tags"] == ["scifi"]


@pytest.mark.e2e
def test_update_metadata_invalid_field_is_tool_error(seeded: int):
    # EDIT-04: a field outside the whitelist is rejected, listing allowed fields.
    with pytest.raises(ToolError) as excinfo:
        _call(
            "update_metadata", {"book_id": seeded, "fields": {"bogus_field": "x"}}
        )

    assert "bogus_field" in str(excinfo.value)
    assert "allowed" in str(excinfo.value)


# ---------------------------------------------------------------- BULK EDIT


@pytest.fixture
def two_seeded(env: Path, tmp_path: Path) -> list[int]:
    """Seed two DISTINCT books (different source files) and return their ids."""
    runner = CalibredbRunner(env)
    sources = sample_epub_sources()
    shutil.copy2(sources[0], tmp_path / "one.epub")
    shutil.copy2(sources[1], tmp_path / "two.epub")
    id1 = runner.add(tmp_path / "one.epub").book_id
    id2 = runner.add(tmp_path / "two.epub").book_id
    assert id1 is not None and id2 is not None
    return [id1, id2]


@pytest.mark.e2e
def test_update_metadata_bulk_plan_then_apply_round_trip(two_seeded: list[int]):
    # BEDIT-01/02: plan (no token) -> per-book diff + token, no write; apply
    # (token) -> writes both books, re-read reflects the change.
    plan = _call(
        "update_metadata_bulk",
        {"book_ids": two_seeded, "fields": {"series": "Dune"}},
    )

    assert plan["status"] == "plan"
    assert {d["book_id"] for d in plan["diffs"]} == set(two_seeded)
    assert all(d["diff"]["series"]["proposed"] == "Dune" for d in plan["diffs"])
    assert _call("get_book", {"book_id": two_seeded[0]})["series"] is None

    applied = _call(
        "update_metadata_bulk",
        {
            "book_ids": two_seeded,
            "fields": {"series": "Dune"},
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert applied["status"] == "applied"
    assert applied["failed"] == []
    assert {a["book_id"] for a in applied["applied"]} == set(two_seeded)
    for book_id in two_seeded:
        assert _call("get_book", {"book_id": book_id})["series"] == "Dune"


@pytest.mark.e2e
def test_update_metadata_bulk_partial_failure_reports_applied_and_failed(
    two_seeded: list[int],
):
    # BEDIT-04: one vanished id fails alone; the other book still applies, and
    # the result reports both applied and failed truthfully.
    ok_id = two_seeded[0]
    book_ids = [ok_id, 999999]
    plan = _call(
        "update_metadata_bulk",
        {"book_ids": book_ids, "fields": {"series": "Dune"}},
    )

    applied = _call(
        "update_metadata_bulk",
        {
            "book_ids": book_ids,
            "fields": {"series": "Dune"},
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert {a["book_id"] for a in applied["applied"]} == {ok_id}
    assert {f["book_id"] for f in applied["failed"]} == {999999}
    assert _call("get_book", {"book_id": ok_id})["series"] == "Dune"


@pytest.mark.e2e
def test_update_metadata_bulk_empty_book_ids_is_tool_error(env: Path):
    # BEDIT-06: empty book_ids is rejected before any token/backup/write.
    with pytest.raises(ToolError) as excinfo:
        _call("update_metadata_bulk", {"book_ids": [], "fields": {"series": "Dune"}})

    assert "book_ids" in str(excinfo.value)


@pytest.mark.e2e
def test_update_metadata_bulk_unknown_field_is_tool_error(two_seeded: list[int]):
    # BEDIT-06: an unknown field is rejected as invalid input.
    with pytest.raises(ToolError) as excinfo:
        _call(
            "update_metadata_bulk",
            {"book_ids": two_seeded, "fields": {"bogus_field": "x"}},
        )

    assert "bogus_field" in str(excinfo.value)


@pytest.mark.e2e
def test_update_metadata_bulk_description_documents_list_mode_and_contract():
    # T3 Done-when: docstring documents list_mode + the applied/failed contract.
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    text = tools["update_metadata_bulk"].description.lower()

    assert "host" in text and "surface" in text
    assert "list_mode" in text
    assert "add" in text and "remove" in text and "replace" in text
    assert "applied" in text and "failed" in text


@pytest.mark.e2e
def test_stdout_stays_clean_across_bulk_edit_calls(two_seeded: list[int]):
    # Design Risks: stdout is the MCP framing channel; bulk edit must stay clean.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        plan = _call(
            "update_metadata_bulk",
            {"book_ids": two_seeded, "fields": {"series": "Dune"}},
        )
        _call(
            "update_metadata_bulk",
            {
                "book_ids": two_seeded,
                "fields": {"series": "Dune"},
                "confirmation_token": plan["confirmation_token"],
            },
        )

    assert buffer.getvalue() == ""


# ---------------------------------------------------------------- RENAME AUTHOR


@pytest.fixture
def author_seeded(env: Path, tmp_path: Path) -> tuple[int, int]:
    """Seed two books: one credited to 'Old Name', one to 'Someone Else'."""
    runner = CalibredbRunner(env)
    sources = sample_epub_sources()
    shutil.copy2(sources[0], tmp_path / "old.epub")
    shutil.copy2(sources[1], tmp_path / "other.epub")
    old_id = runner.add(tmp_path / "old.epub").book_id
    other_id = runner.add(tmp_path / "other.epub").book_id
    assert old_id is not None and other_id is not None
    runner.set_metadata(old_id, {"authors": ["Old Name"]})
    runner.set_metadata(other_id, {"authors": ["Someone Else"]})
    return old_id, other_id


@pytest.mark.e2e
def test_rename_author_plan_then_apply_round_trip(author_seeded: tuple[int, int]):
    # ARENAME-01/04/08: plan (no token) -> per-book resolved diff + token, no
    # write; apply (token) -> writes the affected book, re-read reflects the
    # rename, and the unaffected book is untouched.
    old_id, other_id = author_seeded

    plan = _call("rename_author", {"old_name": "Old Name", "new_name": "New Name"})

    assert plan["status"] == "plan"
    assert {d["book_id"] for d in plan["diffs"]} == {old_id}
    assert plan["diffs"][0]["diff"]["authors"]["proposed"] == ["New Name"]
    assert _call("get_book", {"book_id": old_id})["authors"] == ["Old Name"]

    applied = _call(
        "rename_author",
        {
            "old_name": "Old Name",
            "new_name": "New Name",
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert applied["status"] == "renamed"
    assert applied["applied"] == [{"book_id": old_id, "authors": ["New Name"]}]
    assert applied["failed"] == []
    assert _call("get_book", {"book_id": old_id})["authors"] == ["New Name"]
    assert _call("get_book", {"book_id": other_id})["authors"] == ["Someone Else"]


@pytest.mark.e2e
def test_rename_author_not_found_is_tool_error(env: Path):
    # ARENAME-02: an author matching no book surfaces a clear tool error.
    with pytest.raises(ToolError) as excinfo:
        _call(
            "rename_author", {"old_name": "Nobody At All", "new_name": "New Name"}
        )

    assert "not found" in str(excinfo.value).lower()


# ------------------------------------------------------------------- RENAME TAG


@pytest.fixture
def tag_seeded(env: Path, tmp_path: Path) -> tuple[int, int]:
    """Seed two books: one tagged 'old-tag', one tagged 'other-tag'."""
    runner = CalibredbRunner(env)
    sources = sample_epub_sources()
    shutil.copy2(sources[0], tmp_path / "old.epub")
    shutil.copy2(sources[1], tmp_path / "other.epub")
    old_id = runner.add(tmp_path / "old.epub").book_id
    other_id = runner.add(tmp_path / "other.epub").book_id
    assert old_id is not None and other_id is not None
    runner.set_metadata(old_id, {"tags": ["old-tag"]})
    runner.set_metadata(other_id, {"tags": ["other-tag"]})
    return old_id, other_id


@pytest.mark.e2e
def test_rename_tag_plan_then_apply_round_trip(tag_seeded: tuple[int, int]):
    # TRENAME-01/04/08: plan (no token) -> per-book resolved diff + token, no
    # write; apply (token) -> writes the affected book, re-read reflects the
    # rename, and the unaffected book is untouched.
    old_id, other_id = tag_seeded

    plan = _call("rename_tag", {"old_tag": "old-tag", "new_tag": "new-tag"})

    assert plan["status"] == "plan"
    assert {d["book_id"] for d in plan["diffs"]} == {old_id}
    assert set(plan["diffs"][0]["diff"]["tags"]["proposed"]) == {"new-tag"}
    assert _call("get_book", {"book_id": old_id})["tags"] == ["old-tag"]

    applied = _call(
        "rename_tag",
        {
            "old_tag": "old-tag",
            "new_tag": "new-tag",
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert applied["status"] == "renamed"
    assert applied["applied"] == [{"book_id": old_id, "tags": ["new-tag"]}]
    assert applied["failed"] == []
    assert _call("get_book", {"book_id": old_id})["tags"] == ["new-tag"]
    assert _call("get_book", {"book_id": other_id})["tags"] == ["other-tag"]


@pytest.mark.e2e
def test_rename_tag_not_found_is_tool_error(env: Path):
    # TRENAME-02: a tag on no book surfaces a clear tool error.
    with pytest.raises(ToolError) as excinfo:
        _call("rename_tag", {"old_tag": "no-such-tag", "new_tag": "new-tag"})

    assert "not found" in str(excinfo.value).lower()


@pytest.fixture
def series_seeded(env: Path, tmp_path: Path) -> tuple[int, int]:
    """Seed two books: one in series 'Old' (index 7.5), one in 'Other'."""
    runner = CalibredbRunner(env)
    sources = sample_epub_sources()
    shutil.copy2(sources[0], tmp_path / "old.epub")
    shutil.copy2(sources[1], tmp_path / "other.epub")
    old_id = runner.add(tmp_path / "old.epub").book_id
    other_id = runner.add(tmp_path / "other.epub").book_id
    assert old_id is not None and other_id is not None
    runner.set_metadata(old_id, {"series": "Old", "series_index": 7.5})
    runner.set_metadata(other_id, {"series": "Other", "series_index": 1.0})
    return old_id, other_id


@pytest.mark.e2e
def test_rename_series_plan_then_apply_round_trip_preserves_index(
    series_seeded: tuple[int, int],
):
    # SRENAME-01/04/07/08: plan (no token) -> per-book diff + token, no
    # write; apply (token) -> writes the affected book, re-read reflects the
    # rename WITH the original series_index preserved, unaffected book
    # untouched.
    old_id, other_id = series_seeded

    plan = _call("rename_series", {"old_series": "Old", "new_series": "New"})

    assert plan["status"] == "plan"
    assert {d["book_id"] for d in plan["diffs"]} == {old_id}
    assert plan["diffs"][0]["diff"]["series"]["proposed"] == "New"
    assert plan["diffs"][0]["series_index"] == 7.5
    assert _call("get_book", {"book_id": old_id})["series"] == "Old"

    applied = _call(
        "rename_series",
        {
            "old_series": "Old",
            "new_series": "New",
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert applied["status"] == "renamed"
    assert applied["applied"] == [
        {"book_id": old_id, "series": "New", "series_index": 7.5}
    ]
    assert applied["failed"] == []
    assert _call("get_book", {"book_id": old_id})["series"] == "New"
    assert _call("get_book", {"book_id": old_id})["series_index"] == 7.5
    assert _call("get_book", {"book_id": other_id})["series"] == "Other"


@pytest.mark.e2e
def test_rename_series_not_found_is_tool_error(env: Path):
    # SRENAME-02: a series on no book surfaces a clear tool error.
    with pytest.raises(ToolError) as excinfo:
        _call(
            "rename_series",
            {"old_series": "no-such-series", "new_series": "New"},
        )

    assert "not found" in str(excinfo.value).lower()


# ---------------------------------------------------------------------- ADD


@pytest.mark.e2e
def test_add_book_imports_and_returns_id(env: Path, tmp_path: Path):
    # ADD-01: import a file and return its new id + parsed metadata.
    epub = _sample_epub(tmp_path, "import.epub")

    result = _call("add_book", {"path": str(epub)})

    assert result["status"] == "added"
    assert isinstance(result["book_id"], int)
    assert result["book"]["id"] == result["book_id"]


@pytest.mark.e2e
def test_add_book_nonexistent_path_is_tool_error(env: Path):
    # ADD-02: a path that is not a file is an explicit error before calibredb.
    with pytest.raises(ToolError) as excinfo:
        _call("add_book", {"path": "/no/such/file.epub"})

    assert "file" in str(excinfo.value).lower()


# ---------------------------------------------------------------- FOLDER IMPORT


@pytest.mark.e2e
def test_import_folder_happy_path_returns_three_buckets_and_backup(
    env: Path, tmp_path: Path
):
    # BIMPORT-03/06: recursive import returns added (real id + metadata),
    # empty duplicate/failed, and a backup path.
    source = tmp_path / "src"
    source.mkdir()
    epub = _sample_epub(source, "book.epub")

    result = _call("import_folder", {"path": str(source)})

    assert result["status"] == "imported"
    assert len(result["added"]) == 1
    assert result["added"][0]["path"] == str(epub)
    assert isinstance(result["added"][0]["book_id"], int)
    assert result["added"][0]["book"]["id"] == result["added"][0]["book_id"]
    assert result["duplicate"] == []
    assert result["failed"] == []
    assert result["backup"]


@pytest.mark.e2e
def test_import_folder_nonexistent_path_is_tool_error(env: Path):
    # BIMPORT-02: a non-directory path is an explicit tool error.
    with pytest.raises(ToolError) as excinfo:
        _call("import_folder", {"path": "/no/such/directory"})

    assert "directory" in str(excinfo.value).lower()


@pytest.mark.e2e
def test_import_folder_description_documents_contract():
    # T4 Done-when: docstring documents recursive/additive/no-token, the
    # 500 cap, the three buckets, and that non-ebook files are ignored.
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    text = tools["import_folder"].description.lower()

    assert "recursive" in text
    assert "additive" in text and "no confirmation token" in text
    assert "500" in text
    assert "added" in text and "duplicate" in text and "failed" in text
    assert "ignoring" in text or "ignored" in text


@pytest.mark.e2e
def test_stdout_stays_clean_across_import_folder_calls(env: Path, tmp_path: Path):
    # Design Risks: stdout is the MCP framing channel; import_folder must
    # stay clean.
    source = tmp_path / "src"
    source.mkdir()
    _sample_epub(source, "book.epub")
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _call("import_folder", {"path": str(source)})

    assert buffer.getvalue() == ""


# ------------------------------------------------------------------- REMOVE


@pytest.mark.e2e
def test_remove_book_review_returns_recoverable_note_and_token(seeded: int):
    # REM-01: no token -> review (details + recoverable note) + token, no delete.
    review = _call("remove_book", {"book_id": seeded})

    assert review["status"] == "review"
    assert review["recoverable"] is True
    assert "trash" in review["note"] and "recycle bin" in review["note"]
    assert review["confirmation_token"]
    # still present
    assert _call("get_book", {"book_id": seeded})["id"] == seeded


@pytest.mark.e2e
def test_remove_book_unknown_id_is_tool_error(env: Path):
    # REM-03: an unknown id surfaces a clear error, never a false success.
    with pytest.raises(ToolError) as excinfo:
        _call("remove_book", {"book_id": 999999})

    assert "999999" in str(excinfo.value)
    assert "not found" in str(excinfo.value)


@pytest.mark.e2e
def test_remove_book_description_states_recoverable_two_step():
    # REM-06: the tool description states removal is recoverable + two-step review.
    tools = asyncio.run(server.mcp.list_tools())
    remove = next(t for t in tools if t.name == "remove_book")
    text = remove.description.lower()

    assert "recoverable" in text
    assert "recycle bin" in text
    assert "review" in text and "confirm" in text


# ---------------------------------------------------------- MERGE DUPLICATE GROUP


@pytest.fixture
def merge_seeded(env: Path, tmp_path: Path) -> tuple[int, int]:
    """Seed a survivor (EPUB only) and a loser (EPUB + PDF), distinct files."""
    runner = CalibredbRunner(env)
    sources = sample_epub_sources()
    shutil.copy2(sources[0], tmp_path / "survivor.epub")
    shutil.copy2(sources[1], tmp_path / "loser.epub")
    survivor_id = runner.add(tmp_path / "survivor.epub").book_id
    loser_id = runner.add(tmp_path / "loser.epub").book_id
    assert survivor_id is not None and loser_id is not None
    fake_pdf = tmp_path / "extra.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    runner.add_format(loser_id, fake_pdf)
    return survivor_id, loser_id


@pytest.mark.e2e
def test_merge_duplicate_group_plan_then_apply_round_trip(
    merge_seeded: tuple[int, int],
):
    # MERGE-01/04/07/08: plan (no token) -> per-loser format split + token, no
    # write; apply (token) -> survivor gains the unique format, loser is gone.
    survivor_id, loser_id = merge_seeded

    plan = _call(
        "merge_duplicate_group",
        {"survivor_id": survivor_id, "loser_ids": [loser_id]},
    )

    assert plan["status"] == "plan"
    entry = plan["losers"][0]
    assert entry["book_id"] == loser_id
    assert entry["formats_to_add"] == ["PDF"]
    assert entry["formats_already_present"] == ["EPUB"]
    assert _call("get_book", {"book_id": survivor_id})["formats"] == ["EPUB"]

    result = _call(
        "merge_duplicate_group",
        {
            "survivor_id": survivor_id,
            "loser_ids": [loser_id],
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert result["status"] == "merged"
    assert set(result["survivor_formats"]) == {"EPUB", "PDF"}
    assert result["merged"] == [
        {
            "loser_id": loser_id,
            "formats_added": ["PDF"],
            "trash_location": result["merged"][0]["trash_location"],
        }
    ]
    assert result["failed"] == []
    with pytest.raises(ToolError):
        _call("get_book", {"book_id": loser_id})  # gone


@pytest.mark.e2e
def test_merge_duplicate_group_invalid_loser_ids_is_tool_error(seeded: int):
    # MERGE-03: survivor_id inside loser_ids surfaces a clear tool error.
    with pytest.raises(ToolError) as excinfo:
        _call(
            "merge_duplicate_group",
            {"survivor_id": seeded, "loser_ids": [seeded]},
        )

    assert "loser_ids" in str(excinfo.value)


@pytest.mark.e2e
def test_mutation_descriptions_instruct_host_to_surface_the_plan():
    # AD-012 / REM-06: edit + remove descriptions tell the host to surface the
    # plan/review to the user before applying (two-step intent gate).
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}

    for name in ("update_metadata", "remove_book"):
        text = tools[name].description.lower()
        assert "host" in text and "surface" in text
        assert "confirmation_token" in text


# --------------------------------------------------------------- STDOUT HYGIENE


@pytest.mark.e2e
def test_stdout_stays_clean_across_tool_calls(seeded: int):
    # Design Risks: stdout is the MCP framing channel — tools must never write to
    # it (logging is stderr-only). A full round of calls must leave stdout empty.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        server.logger.info("this log must go to stderr, never stdout")
        _call("list_books", {})
        _call("get_book", {"book_id": seeded})
        _call("search_books", {"query": "format:epub"})

    assert buffer.getvalue() == ""


# --------------------------------------------------------------------- CONFIG


@pytest.mark.e2e
def test_missing_library_path_surfaces_config_tool_error(monkeypatch):
    # CFG-01: an unset CALIBRE_LIBRARY_PATH fails with a clear, actionable error.
    monkeypatch.delenv("CALIBRE_LIBRARY_PATH", raising=False)
    monkeypatch.setattr(server, "_library", None)

    with pytest.raises(ToolError) as excinfo:
        _call("list_books", {})

    assert "CALIBRE_LIBRARY_PATH" in str(excinfo.value)


# -------------------------------------------------------------------- CONVERT


@pytest.mark.e2e
def test_convert_book_adds_format_additively(seeded: int):
    # CONV-01 AC-1/AC-2: convert epub -> pdf; both formats present afterward.
    result = _call("convert_book", {"book_id": seeded, "target_format": "pdf"})

    assert result["status"] == "converted"
    assert set(result["book"]["formats"]) == {"EPUB", "PDF"}


@pytest.mark.e2e
def test_convert_book_unsupported_format_is_tool_error(seeded: int):
    # CONV-01 boundary: an unsupported target format is an explicit tool error.
    with pytest.raises(ToolError) as excinfo:
        _call("convert_book", {"book_id": seeded, "target_format": "bogus"})

    assert "bogus" in str(excinfo.value)


@pytest.mark.e2e
def test_convert_book_description_states_additive():
    # CONV-01: the tool description states it keeps existing formats.
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    text = tools["convert_book"].description.lower()

    assert "additive" in text or "keep" in text
    assert "refuse" in text


# --------------------------------------------------------------- BULK CONVERT


@pytest.mark.e2e
def test_convert_book_bulk_additive_round_trip(two_seeded: list[int]):
    # BCONV-01/04: broadcast convert to PDF; both books read back EPUB+PDF
    # (additive) and appear in ``converted`` with their re-read formats.
    result = _call(
        "convert_book_bulk", {"book_ids": two_seeded, "target_format": "pdf"}
    )

    assert result["status"] == "converted"
    assert {c["book_id"] for c in result["converted"]} == set(two_seeded)
    for book_id in two_seeded:
        assert set(_call("get_book", {"book_id": book_id})["formats"]) == {
            "EPUB",
            "PDF",
        }


@pytest.mark.e2e
def test_convert_book_bulk_mixed_batch_returns_three_buckets(two_seeded: list[int]):
    # BCONV-02/03: a book already having the target -> skipped, a missing id ->
    # failed, and a third book -> converted; all three buckets routed correctly.
    already = two_seeded[0]
    _call("convert_book", {"book_id": already, "target_format": "pdf"})  # EPUB+PDF
    to_convert = two_seeded[1]

    result = _call(
        "convert_book_bulk",
        {"book_ids": [already, to_convert, 999999], "target_format": "pdf"},
    )

    assert {c["book_id"] for c in result["converted"]} == {to_convert}
    assert {s["book_id"] for s in result["skipped"]} == {already}
    assert {f["book_id"] for f in result["failed"]} == {999999}


@pytest.mark.e2e
def test_convert_book_bulk_empty_ids_is_tool_error(env: Path):
    # BCONV-06: empty book_ids is rejected as invalid input at the boundary.
    with pytest.raises(ToolError) as excinfo:
        _call("convert_book_bulk", {"book_ids": [], "target_format": "pdf"})

    assert "book_ids" in str(excinfo.value)


@pytest.mark.e2e
def test_convert_book_bulk_over_cap_is_tool_error(env: Path):
    # BCONV-06: a batch over the 50-book cap surfaces a clear tool error.
    with pytest.raises(ToolError) as excinfo:
        _call(
            "convert_book_bulk",
            {"book_ids": list(range(1, 52)), "target_format": "epub"},
        )

    assert "50" in str(excinfo.value)


@pytest.mark.e2e
def test_convert_book_bulk_description_documents_contract():
    # T3 Done-when: docstring documents ADDITIVE/no-token, the 50-book cap, the
    # three buckets, and that skipped is a benign no-op (not a failure).
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    text = tools["convert_book_bulk"].description.lower()

    assert "additive" in text or "keep" in text
    assert "50" in text
    assert "converted" in text and "skipped" in text and "failed" in text
    assert "benign" in text  # skipped is documented as a benign no-op, not a failure


@pytest.mark.e2e
def test_stdout_stays_clean_across_bulk_convert_calls(seeded: int):
    # Design Risks: stdout is the MCP framing channel; bulk convert must stay clean.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _call("convert_book_bulk", {"book_ids": [seeded], "target_format": "pdf"})

    assert buffer.getvalue() == ""


# -------------------------------------------------------------- DUPLICATES


@pytest.mark.e2e
def test_find_duplicates_returns_groups(env: Path, tmp_path: Path):
    # ORG-01 AC-1: two same-title/same-author books -> one group of 2.
    runner = CalibredbRunner(env)
    id1 = runner.add(_sample_epub(tmp_path, "one.epub")).book_id
    shutil.copy2(sample_epub_sources()[1], tmp_path / "two.epub")
    id2 = runner.add(tmp_path / "two.epub").book_id
    runner.set_metadata(id1, {"title": "Same Title", "authors": ["Same Author"]})
    runner.set_metadata(id2, {"title": "Same Title", "authors": ["Same Author"]})

    result = _call("find_duplicates", {})

    assert result["group_count"] == 1
    assert {b["id"] for b in result["groups"][0]["books"]} == {id1, id2}


@pytest.mark.e2e
def test_find_duplicates_no_duplicates_returns_empty_group_set(seeded: int):
    # ORG-01 AC-3: no duplicates -> empty group set, not an error.
    result = _call("find_duplicates", {})

    assert result == {"group_count": 0, "groups": []}


# ------------------------------------------------------------------- EMAIL

_STUB_SMTP_SOURCE = '''#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["STUB_RECORD_FILE"], "w") as f:
    json.dump(sys.argv[1:], f)
sys.exit(0)
'''


@pytest.fixture
def smtp_stub(tmp_path: Path) -> Path:
    stub = tmp_path / "calibre-smtp-stub.py"
    stub.write_text(_STUB_SMTP_SOURCE)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


@pytest.fixture
def smtp_record(tmp_path: Path, monkeypatch) -> Path:
    record = tmp_path / "argv.json"
    monkeypatch.setenv("STUB_RECORD_FILE", str(record))
    return record


@pytest.fixture
def smtp_env(monkeypatch) -> None:
    monkeypatch.setenv(SMTP_RELAY_ENV, "smtp.example.com")
    monkeypatch.setenv(SMTP_USERNAME_ENV, "alice")
    monkeypatch.setenv(SMTP_PASSWORD_ENV, "s3cr3t-p4ss")
    monkeypatch.setenv(SMTP_FROM_ENV, "alice@example.com")


@pytest.fixture
def mailer_seeded(seeded: int, smtp_stub: Path) -> int:
    """Point the cached library's mailer at the stubbed calibre-smtp binary."""
    server._get_library()._mailer = CalibreSmtpRunner(binary=str(smtp_stub))
    return seeded


@pytest.mark.e2e
def test_email_book_plan_then_confirm_sends_via_stub(
    mailer_seeded: int, smtp_record: Path, smtp_env: None
):
    # EMAIL-01 AC-2: plan sends nothing + returns a token.
    plan = _call("email_book", {"book_id": mailer_seeded, "recipient": "bob@x.com"})

    assert plan["status"] == "plan"
    assert plan["confirmation_token"]
    assert not smtp_record.exists()

    # EMAIL-01 AC-1: apply with the token sends via calibre-smtp.
    result = _call(
        "email_book",
        {
            "book_id": mailer_seeded,
            "recipient": "bob@x.com",
            "confirmation_token": plan["confirmation_token"],
        },
    )

    assert result["status"] == "sent"
    argv = json.loads(smtp_record.read_text())
    assert "bob@x.com" in argv


@pytest.mark.e2e
def test_email_book_missing_smtp_env_is_tool_error(
    mailer_seeded: int, smtp_record: Path
):
    # EMAIL-01 AC-6: SMTP unset -> a clear tool error naming the missing var.
    plan = _call("email_book", {"book_id": mailer_seeded, "recipient": "bob@x.com"})

    with pytest.raises(ToolError) as excinfo:
        _call(
            "email_book",
            {
                "book_id": mailer_seeded,
                "recipient": "bob@x.com",
                "confirmation_token": plan["confirmation_token"],
            },
        )

    assert SMTP_RELAY_ENV in str(excinfo.value)
    assert not smtp_record.exists()


@pytest.mark.e2e
def test_email_book_description_instructs_host_to_surface_plan():
    # EMAIL-01: outward-facing send -> host must surface the plan before apply.
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    text = tools["email_book"].description.lower()

    assert "host" in text and "surface" in text
    assert "confirmation_token" in text


@pytest.mark.e2e
def test_stdout_stays_clean_across_p2_tool_calls(mailer_seeded: int, smtp_record: Path):
    # T10 Done-when: stdout stays clean across the 3 new tools too.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _call("find_duplicates", {})
        _call("convert_book", {"book_id": mailer_seeded, "target_format": "pdf"})
        _call("email_book", {"book_id": mailer_seeded, "recipient": "bob@x.com"})

    assert buffer.getvalue() == ""


# --------------------------------------------------------------------- STATS


@pytest.mark.e2e
def test_library_stats_resource_returns_well_formed_profile(
    env: Path, tmp_path: Path
):
    # STATS-01-01: totals.books matches count_books(); the profile shape is
    # well-formed and the known duplicate group is present.
    runner = CalibredbRunner(env)
    id1 = runner.add(_sample_epub(tmp_path, "one.epub")).book_id
    shutil.copy2(sample_epub_sources()[1], tmp_path / "two.epub")
    id2 = runner.add(tmp_path / "two.epub").book_id
    runner.set_metadata(id1, {"title": "Same Title", "authors": ["Same Author"]})
    runner.set_metadata(id2, {"title": "Same Title", "authors": ["Same Author"]})

    stats = _read_resource("calibre://library/stats")

    assert stats["totals"]["books"] == server._get_library().count_books()
    groups = stats["data_quality_flags"]["duplicate_title_groups"]
    assert {b["id"] for b in groups[0]["books"]} == {id1, id2}


@pytest.mark.e2e
def test_library_stats_resource_empty_library_is_zeroed_not_an_error(env: Path):
    # STATS-01-02 (AC-2): empty library -> valid zeroed profile, never an error.
    stats = _read_resource("calibre://library/stats")

    assert stats["totals"]["books"] == 0
    assert stats["data_quality_flags"]["duplicate_title_groups"] == []


@pytest.mark.e2e
def test_library_stats_resource_reports_cover_coverage(env: Path, tmp_path: Path):
    # COVCOV-04: the resource payload carries cover coverage + missing ids.
    covered = _seed_covered_book(env, tmp_path)
    uncovered = _seed_empty_book(env, "No Cover")

    stats = _read_resource("calibre://library/stats")

    assert stats["metadata_completeness"]["cover"] == {"filled": 1, "pct": 50.0}
    assert stats["data_quality_flags"]["missing_cover_ids"] == [uncovered]
    assert covered != uncovered


@pytest.mark.e2e
def test_library_stats_resource_unreadable_db_is_resource_error(env: Path):
    # STATS-01-04 (AC-4): a corrupt metadata.db (present on disk, unreadable
    # as SQLite) -> a named ResourceError, never a silent empty/wrong profile.
    (env / "metadata.db").write_bytes(b"not a real sqlite file at all")

    with pytest.raises(ResourceError) as excinfo:
        _read_resource("calibre://library/stats")

    assert "file is not a database" in str(excinfo.value)


@pytest.mark.e2e
def test_library_stats_resource_two_reads_are_identical(seeded: int):
    # STATS-01-05 (AC-5): deterministic — two reads with no changes match.
    first = _read_resource("calibre://library/stats")
    second = _read_resource("calibre://library/stats")

    assert first == second


@pytest.mark.e2e
def test_library_stats_resource_stdout_stays_clean(seeded: int):
    # Design Risks: reading the resource must never write to stdout.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        _read_resource("calibre://library/stats")

    assert buffer.getvalue() == ""


# ------------------------------------------------------------ ENRICH-01 (LOOKUP)


class _EnrichFake:
    """A no-network enricher for the tool surface: returns a record or raises."""

    def __init__(
        self,
        record: OpenLibraryRecord | None,
        *,
        fetch_error: Exception | None = None,
    ) -> None:
        self._record = record
        self._fetch_error = fetch_error

    def fetch_record(self, isbn: str) -> OpenLibraryRecord | None:
        if self._fetch_error is not None:
            raise self._fetch_error
        return self._record

    def download_cover(self, cover_url: str, dest_dir: Path | None = None) -> Path:
        raise AssertionError("cover download is not exercised by these e2e tests")


def _seed_isbn_book(library_path: Path) -> int:
    book_id = _seed_empty_book(library_path, "Enrich")
    CalibredbRunner(library_path).set_metadata(
        book_id, {"identifiers": "isbn:978-0-553-29335-7"}
    )
    return book_id


@pytest.mark.e2e
def test_enrich_from_identifier_returns_found_true_payload(env: Path):
    # LOOKUP-01: the tool returns the advisory found:true JSON payload, gap-only.
    book_id = _seed_isbn_book(env)
    server._get_library()._enricher = _EnrichFake(
        OpenLibraryRecord("Bantam", "April 2009", "A space opera.", None)
    )

    result = _call("enrich_from_identifier", {"book_id": book_id})

    assert result["found"] is True
    assert result["source"] == "openlibrary"
    assert result["identifier_used"] == {"type": "isbn", "value": "9780553293357"}
    assert result["proposed"] == {
        "comments": "A space opera.",
        "publisher": "Bantam",
        "pubdate": "April 2009",
    }
    assert result["cover"] is None


@pytest.mark.e2e
def test_enrich_from_identifier_found_false_is_normal_json_not_error(env: Path):
    # LOOKUP-02: a book with no ISBN surfaces found:false as normal JSON, not an error.
    book_id = _seed_empty_book(env, "NoIsbn")
    server._get_library()._enricher = _EnrichFake(
        OpenLibraryRecord("X", "Y", "Z", None)
    )

    result = _call("enrich_from_identifier", {"book_id": book_id})

    assert result == {
        "book_id": book_id,
        "found": False,
        "reason": "no usable identifier (ISBN)",
    }


@pytest.mark.e2e
def test_enrich_from_identifier_source_error_maps_to_tool_error(env: Path):
    # LOOKUP-08: an EnrichmentSourceError from the facade maps to a clean ToolError.
    book_id = _seed_isbn_book(env)
    server._get_library()._enricher = _EnrichFake(
        None, fetch_error=EnrichmentSourceError("source offline")
    )

    with pytest.raises(ToolError) as excinfo:
        _call("enrich_from_identifier", {"book_id": book_id})

    assert "source offline" in str(excinfo.value)


@pytest.mark.e2e
def test_enrich_missing_returns_batch_proposals_as_json(env: Path):
    # ENRICH3-01/02: the batch tool returns a proposal per candidate + a summary.
    first = _seed_isbn_book(env)
    second = _seed_empty_book(env, "Second")
    CalibredbRunner(env).set_metadata(second, {"identifiers": "isbn:9780000000002"})
    server._get_library()._enricher = _EnrichFake(
        OpenLibraryRecord("Bantam", "2009", "A space opera.", None)
    )

    result = _call("enrich_missing", {})

    assert result["candidate_count"] == 2
    assert result["processed"] == 2
    assert result["summary"] == {
        "proposed": 2, "no_new_data": 0, "no_record": 0, "error": 0
    }
    assert {r["book_id"] for r in result["results"]} == {first, second}
    assert all(r["status"] == "proposed" for r in result["results"])


@pytest.mark.e2e
def test_enrich_missing_isolates_source_error_as_json_status_not_tool_error(env: Path):
    # ENRICH3-04: a per-book source failure is a JSON status:error, NOT a ToolError.
    book_id = _seed_isbn_book(env)
    server._get_library()._enricher = _EnrichFake(
        None, fetch_error=EnrichmentSourceError("source offline")
    )

    result = _call("enrich_missing", {})  # does NOT raise

    assert result["summary"]["error"] == 1
    assert result["results"][0]["book_id"] == book_id
    assert result["results"][0]["status"] == "error"


@pytest.mark.e2e
def test_enrich_missing_bad_bound_maps_to_tool_error(env: Path):
    # ENRICH3-08: an invalid bound surfaces as a clean ToolError.
    with pytest.raises(ToolError):
        _call("enrich_missing", {"limit": 0})
