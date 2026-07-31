# Read a Book's Cover (COVER-01) Validation

**Date**: 2026-07-31
**Spec**: `.specs/features/cover-read/spec.md`
**Diff range**: `f4f3a16^..4cb751c` (4 commits)
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status  | Notes |
| ---- | ------- | ----- |
| T1 `SqliteReader.cover_file` | ✅ Done | `has_cover`-keyed resolution; sibling of `format_files`. |
| T2 `CalibreLibrary.read_cover` | ✅ Done | Dict-typed facade `{book_id, has_cover, cover_path}`. |
| T3 `read_cover` tool + `_map_errors` generic + closeout | ✅ Done | `-> Any` SPEC_DEVIATION (justified below); AD-024 recorded. |

---

## Spec-Anchored Acceptance Criteria

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| ------------------------- | -------------------- | ----------------------- | ------ |
| RCOVER-01: covered book → viewable image content, no write | `image/jpeg`, non-empty bytes of `cover.jpg` | `tests/e2e/test_server.py:266-268` — `isinstance(content[0], ImageContent)`, `content[0].mimeType == "image/jpeg"`, `content[0].data`; reader `tests/integration/test_sqlite_reader.py:355-357` — `cover.is_file()`, `cover.name == "cover.jpg"`; facade `tests/integration/test_library_read_cover.py:117-122` | ✅ PASS |
| RCOVER-02: no-cover → `{book_id, has_cover: false, cover_path: null}` | exact dict, not error/image | `tests/e2e/test_server.py:278` — `payload == {"book_id": book_id, "has_cover": False, "cover_path": None}`; facade `test_library_read_cover.py:132`; reader returns `None` `test_sqlite_reader.py:372` | ✅ PASS |
| RCOVER-03: unknown id → not-found error naming id | `BookNotFoundError`/`ToolError` naming id | `tests/e2e/test_server.py:287` — `"999999" in str(excinfo.value)` (ToolError); facade `test_library_read_cover.py:141` — `excinfo.value.book_id == 999999`; reader `test_sqlite_reader.py:383` | ✅ PASS |
| RCOVER-04: has_cover=1 but file missing → InvalidInputError | `InvalidInputError` naming book, no silent degrade | `tests/integration/test_sqlite_reader.py:401,403` — deletes `cover.jpg`, `pytest.raises(InvalidInputError)`, `str(book_id) in str(excinfo.value)` | ✅ PASS |
| RCOVER-05: pure read — no metadata.db backup / calibredb / network | no backup file created, any outcome | `tests/integration/test_library_read_cover.py:162` — after covered+uncovered+unknown calls, `assert not backup_root.exists()` | ✅ PASS |

**Status**: ✅ All 5 ACs covered and matched to spec-defined outcomes.

**Coverage note (not a gap):** RCOVER-04 is proven at the reader layer only (per the Test Coverage
Matrix, which scopes it to T1). Facade/tool propagation is pure (no new handling; `_map_errors`
maps `InvalidInputError → ToolError`), transitively covered by the existing tool suite + mypy. The
reader test plus discrimination-sensor mutation 2 (below) establish the behavior authoritatively.

---

## SPEC_DEVIATION scrutiny (`-> Any` instead of `Image | dict`)

Independently reproduced under the installed `mcp 1.28.1` (throwaway probe, `FastMCP` in-process):

- `@tool def bad(...) -> Image | dict:` → **crashes registration** with
  `PydanticSchemaGenerationError: Unable to generate pydantic-core schema for <Image>`.
- `@tool def good(...) -> Any:` → registers, `outputSchema = None`.

So the design's annotation is genuinely unusable on the pinned SDK; `-> Any` is the correct fix and
matches AD-024's description in `.specs/STATE.md`. Runtime wire behavior is unchanged and **proven**:
the e2e test asserts real `ImageContent` (mimeType/data), and sensor mutation 3 shows that forcing
the dict branch yields `TextContent`, failing the `isinstance(..., ImageContent)` assertion — the
test is not weakened. The only loss is a static union annotation (documentation), mitigated by the
docstring, the inline `# SPEC_DEVIATION` comment, and AD-024. No RCOVER-01..05 guarantee depends on
that static annotation (they are runtime contracts). **Deviation accepted — not a gap.**

---

## Discrimination Sensor

| Mutation | File:line | Description | Killed? |
| -------- | --------- | ----------- | ------- |
| 1 | `src/calibre_mcp/sqlite_reader.py` (`if not row["has_cover"]` → `if row["has_cover"]`) | Flip the has_cover branch | ✅ Killed — 3 cover_file integration tests fail |
| 2 | `src/calibre_mcp/sqlite_reader.py` (`if not cover.is_file()` → `if False`) | Drop the metadata↔disk guard (RCOVER-04) | ✅ Killed — `test_cover_file_missing_on_disk_raises_invalid_input` fails |
| 3 | `src/calibre_mcp/server.py` (`if result["has_cover"]` → `if False`) | Never return `Image`, always dict | ✅ Killed — e2e `isinstance(content[0], ImageContent)` fails (got TextContent) |

**Sensor depth**: lightweight (3 behavior-level mutations on the highest-risk new code).
**Result**: 3/3 killed — PASS ✅. Working tree restored to `4cb751c` after each (verified clean).

---

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum code (no features beyond asked) | ✅ |
| No abstractions for single-use code | ✅ |
| Surgical changes (only required files) | ✅ |
| Matches existing patterns (`format_files` sibling, `_map_errors`/`_get_library` tool pattern) | ✅ |
| Spec-anchored outcome check (asserted values match spec) | ✅ |
| Per-layer coverage: reader 1:1 ACs; facade happy+edge+error+no-backup; e2e happy+edge+error | ✅ |
| Every test maps to a spec requirement — no unclaimed tests | ✅ |
| Documented guidelines followed: `AGENTS.md` (quality/testing), `pyproject.toml` markers, `.specs/STATE.md` | ✅ |

`_map_errors` re-typed generic (PEP 695) is a pure typing change; whole suite green confirms no
behavior change for existing dict-returning tools.

---

## Edge Cases

- [x] `has_cover = 0` → structured no-cover result (RCOVER-02)
- [x] `has_cover = 1` but `cover.jpg` missing → `InvalidInputError`, no silent degrade (RCOVER-04)
- [x] unknown id → `BookNotFoundError`/`ToolError` before filesystem access (RCOVER-03)
- [x] cover present → MIME `image/jpeg` (RCOVER-01)
- [x] repeated calls side-effect-free — no backup (RCOVER-05)

---

## Gate Check

- **Gate command**: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- **Result**: ruff `All checks passed!`; mypy `Success: no issues found in 16 source files`; pytest **318 passed** (508s)
- **Full-marker runs**: `uv run pytest -m integration` → 191 passed; `uv run pytest -m e2e` → 59 passed
- **Test count after feature**: 318 (integration 191 + e2e 59 + unit 68)
- **Delta**: +11 new tests for COVER-01 (4 reader cover_file + 4 facade read_cover + 3 e2e read_cover)
- **Skipped**: none
- **Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| ----------- | --------------- | ---------- |
| RCOVER-01 | Implementing | ✅ Verified |
| RCOVER-02 | Implementing | ✅ Verified |
| RCOVER-03 | Implementing | ✅ Verified |
| RCOVER-04 | Implementing | ✅ Verified |
| RCOVER-05 | Implementing | ✅ Verified |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 5/5 ACs matched spec-defined outcomes, 0 spec-precision gaps
**Sensor**: 3/3 mutations killed
**Gate**: 318 passed, 0 failed, 0 skipped

**What works**: `read_cover` returns real MCP `ImageContent` (`image/jpeg`, non-empty) for a covered
book; a normal `{has_cover: false, cover_path: null}` dict for an uncovered book; a not-found
`ToolError` naming the id for an unknown book; `InvalidInputError` for a `has_cover=1`/file-missing
inconsistency; and creates no `metadata.db` backup under any outcome. The `-> Any` SPEC_DEVIATION was
independently reproduced as necessary and confirmed behavior-equivalent.

**Issues found**: none.

**Next steps**: mark RCOVER-01..05 Verified in spec.md (done); COVER-01 ready to close.
