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
  EDIT-01    update_metadata without a token returns a diff + token, no write.
  EDIT-02    update_metadata with a matching token applies and re-reads.
  EDIT-04    an out-of-whitelist field surfaces an explicit tool error.
  ADD-01     add_book imports and returns the new id + metadata.
  ADD-02     a nonexistent path is an explicit tool error.
  REM-01     remove_book without a token returns a recoverable review + token.
  REM-03     an unknown id surfaces a clear tool error (no false success).
  REM-06     the tool description states removal is recoverable + two-step.
  CFG-01     a missing library path surfaces a clear config tool error.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from calibre_mcp import server
from calibre_mcp.calibredb_runner import CalibredbRunner

REAL_LIBRARY = Path("/home/gustavo/Documents/BibliotecaCalibre")


def _sample_epub(tmp_path: Path, name: str = "sample.epub") -> Path:
    """Copy one real .epub into a temp path (reading the real library is safe)."""
    sources = list(REAL_LIBRARY.glob("**/*.epub"))
    if not sources:
        pytest.skip("no sample .epub available in the real library")
    dest = tmp_path / name
    shutil.copy2(sources[0], dest)
    return dest


def _call(name: str, arguments: dict[str, Any]) -> Any:
    """Invoke a registered tool in-process and parse its JSON result payload."""
    result = asyncio.run(server.mcp.call_tool(name, arguments))
    return json.loads(result[0].text)


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
