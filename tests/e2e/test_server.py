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
  CONV-01    convert_book adds a format additively; unsupported target is an error.
  ORG-01     find_duplicates returns groups; no duplicates -> empty group set.
  EMAIL-01   email_book plan->confirm two-step, sent via a stubbed calibre-smtp.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import shutil
import stat
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

from calibre_mcp import server
from calibre_mcp.calibre_smtp_runner import CalibreSmtpRunner
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import (
    SMTP_FROM_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_RELAY_ENV,
    SMTP_USERNAME_ENV,
)

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
    sources = list(REAL_LIBRARY.glob("**/*.epub"))
    if len(sources) < 2:
        pytest.skip("not enough distinct sample .epub files in the real library")
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
    shutil.copy2(list(REAL_LIBRARY.glob("**/*.epub"))[1], tmp_path / "two.epub")
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
    shutil.copy2(list(REAL_LIBRARY.glob("**/*.epub"))[1], tmp_path / "two.epub")
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
