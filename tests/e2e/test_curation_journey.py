"""End-to-end curation journey: every write tool, chained, through FastMCP.

The per-tool contracts live in ``test_server.py``. This module pins the thing
those can't: that the tools COMPOSE — each step's output is the next step's
input, the way a host actually drives a curation session (import -> fix
metadata -> organize -> covers -> formats -> dedupe -> remove). It is the
automated twin of the live smoke run in ``docs/live-smoke-test.md``.

Test-safety rule (non-negotiable): runs only against a per-test
``scratch_library``; it NEVER touches the real library.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import struct
import zlib
from pathlib import Path
from typing import Any

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ImageContent

from calibre_mcp import server
from sample_books import sample_epub_sources


def _call(name: str, arguments: dict[str, Any]) -> Any:
    result = asyncio.run(server.mcp.call_tool(name, arguments))
    return json.loads(result[0].text)


def _plan_then_apply(name: str, arguments: dict[str, Any]) -> Any:
    """Run a two-step tool the way a host must: plan, then apply its token."""
    plan = _call(name, arguments)
    return _call(name, {**arguments, "confirmation_token": plan["confirmation_token"]})


def _write_png(path: Path, width: int = 120, height: int = 180) -> Path:
    # Calibre's Qt rejects a degenerate 1x1 image, so emit a real WxH PNG.
    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\xc8\x1e\x1e" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return path


@pytest.fixture
def env(scratch_library: Path, tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("CALIBRE_LIBRARY_PATH", str(scratch_library))
    monkeypatch.setenv("CALIBRE_MCP_BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(server, "_library", None)
    return scratch_library


@pytest.mark.e2e
def test_full_curation_journey_composes_every_write_tool(env: Path, tmp_path: Path):
    first, second = sample_epub_sources()[:2]
    inbox = tmp_path / "inbox"
    (inbox / "nested").mkdir(parents=True)
    shutil.copy2(first, inbox / "first.epub")
    shutil.copy2(second, inbox / "nested" / "second.epub")
    shutil.copy2(second, inbox / "nested" / "second-again.epub")
    (inbox / "notes.txt").write_text("not an ebook", encoding="utf-8")

    # 1. Import: two new books, the byte-identical copy flagged as duplicate,
    #    the .txt silently ignored.
    imported = _call("import_folder", {"path": str(inbox)})
    assert len(imported["added"]) == 2
    assert len(imported["duplicate"]) == 1
    assert imported["failed"] == []
    keep_id, dup_id = sorted(entry["book_id"] for entry in imported["added"])
    keep = _call("get_book", {"book_id": keep_id})

    # 2. Edit: a forged token is refused before any write; the real one turns
    #    the second book into a duplicate of the first and sets a rating.
    edit = {
        "book_id": dup_id,
        "fields": {
            "title": keep["title"],
            "authors": keep["authors"],
            "tags": ["journey"],
            "series": "Journey Series",
            "series_index": 2,
            "rating": 7,
        },
    }
    with pytest.raises(ToolError, match="confirmation token"):
        _call("update_metadata", {**edit, "confirmation_token": "0" * 16})
    edited = _plan_then_apply("update_metadata", edit)
    assert edited["book"]["rating"] == 7
    assert edited["book"]["title"] == keep["title"]

    # 3. Bulk tag both books without clobbering existing tags.
    bulk = _plan_then_apply(
        "update_metadata_bulk",
        {
            "book_ids": [keep_id, dup_id],
            "fields": {"tags": ["bulk"]},
            "list_mode": "add",
        },
    )
    assert bulk["failed"] == []
    tags_by_id = {
        entry["book_id"]: set(entry["fields"]["tags"]) for entry in bulk["applied"]
    }
    assert tags_by_id[dup_id] == {"journey", "bulk"}

    # 4. Organize: tag/author/series renames touch only what they name.
    renamed_tag = _plan_then_apply(
        "rename_tag", {"old_tag": "bulk", "new_tag": "curated"}
    )
    assert {entry["book_id"] for entry in renamed_tag["applied"]} == {keep_id, dup_id}
    renamed_author = _plan_then_apply(
        "rename_author", {"old_name": keep["authors"][0], "new_name": "Journey Author"}
    )
    assert {entry["book_id"] for entry in renamed_author["applied"]} == {
        keep_id,
        dup_id,
    }
    renamed_series = _plan_then_apply(
        "rename_series",
        {"old_series": "Journey Series", "new_series": "Renamed Series"},
    )
    assert renamed_series["applied"] == [
        {"book_id": dup_id, "series": "Renamed Series", "series_index": 2.0}
    ]

    # 5. Cover: set from a local image, then read it back as viewable content.
    covered = _plan_then_apply(
        "set_cover",
        {"book_id": keep_id, "image_path": str(_write_png(tmp_path / "c.png"))},
    )
    assert covered["has_cover"] is True
    cover = asyncio.run(server.mcp.call_tool("read_cover", {"book_id": keep_id}))
    assert isinstance(cover[0], ImageContent)

    # 6. Formats: a bulk convert accounts for every id in exactly one bucket.
    converted = _call(
        "convert_book_bulk", {"book_ids": [keep_id, 999_999], "target_format": "azw3"}
    )
    assert [entry["book_id"] for entry in converted["converted"]] == [keep_id]
    assert [entry["book_id"] for entry in converted["failed"]] == [999_999]

    # 7. Dedupe: the edited pair is reported, then merged onto the survivor.
    duplicates = _call("find_duplicates", {})
    assert [sorted(b["id"] for b in g["books"]) for g in duplicates["groups"]] == [
        [keep_id, dup_id]
    ]
    merged = _plan_then_apply(
        "merge_duplicate_group", {"survivor_id": keep_id, "loser_ids": [dup_id]}
    )
    assert merged["failed"] == []
    assert set(merged["survivor_formats"]) == {"EPUB", "AZW3"}
    assert Path(merged["merged"][0]["trash_location"]).is_dir()

    # 8. Remove: recoverable — files land in the managed trash, record is gone.
    removed = _plan_then_apply("remove_book", {"book_id": keep_id})
    assert removed["files_copied"] is True
    assert Path(removed["trash_location"]).is_dir()
    assert _call("list_books", {})["total"] == 0
