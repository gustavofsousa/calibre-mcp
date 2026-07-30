# Bulk Convert (BULK-02) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, gate, atomic commit, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/bulk-convert/design.md`
**Status**: Approved

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec. Guidelines found: `CLAUDE.md` (test-safety rule, spec-derived tests), `.specs/STATE.md` (AD-001/AD-005/AD-014/AD-016 invariants, scratch-library rule), `pyproject.toml` (pytest markers unit/integration/e2e, ruff). Existing test samples: `tests/integration/test_library_p2.py` (convert_book CONV-01), `tests/integration/test_library_bulk.py` (BULK-01 partial-failure pattern), `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Facade convert core refactor (`_convert_and_attach`, `_classify_convert`) | integration | CONV-01 single-tool suite stays green unchanged; `_classify_convert` covers ready / already-has-format / no-source | `tests/integration/test_library_p2.py` | `uv run pytest -m "unit or integration" -q` |
| Facade (`CalibreLibrary.convert_book_bulk`) | integration | All branches; 1:1 to BCONV-01..06 + every listed edge case (single-id, all-skipped, vanished-id, over-cap=51, exactly-50, duplicate/non-int id, mixed batch, invariant) | `tests/integration/test_library_bulk_convert.py` | `uv run pytest -m "unit or integration" -q` |
| Tool surface (`server.convert_book_bulk`) | e2e | Contract: additive convert round-trip, three-bucket partial-failure shape, invalid input → ToolError, stdout clean | `tests/e2e/test_server.py` | `uv run pytest -q` |

**Coverage Expectation** set from the strong default (domain logic 1:1 to spec ACs; every listed edge case has a test) — conforms to CLAUDE.md "tests derive from acceptance criteria."

## Parallelism Assessment

> Generated from codebase.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| integration | Yes (per-test) | Per-test `scratch_library` in `tmp_path` | `tests/conftest.py` `scratch_library` fixture |
| e2e | No | Mutates module-global `server._library`; env-var/config swap per test | `tests/e2e/test_server.py` rebinds `server._library` |

Conversion tests require a real convertible source in the scratch library (reuse the CONV-01 fixture setup in `test_library_p2.py`). Phases are sequential by dependency; `[P]` unused.

## Gate Check Commands

> Generated from codebase (uv + pytest + ruff per `.specs/STATE.md` Handoff).

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Full | After tasks with integration tests | `uv run pytest -m "unit or integration" -q` |
| Build | After the last task / e2e / full feature | `uv run ruff check . && uv run pytest -q` |

---

## Execution Plan

### Phase 1: Extract shared convert core (Sequential)

```
T1
```

### Phase 2: Bulk convert facade (Sequential)

```
T1 → T2
```

### Phase 3: Tool surface (Sequential)

```
T2 → T3
```

---

## Task Breakdown

### T1: Extract `_convert_and_attach` + `_classify_convert` from `convert_book`

**What**: Behavior-preserving refactor — pull the single `convert_book`'s source-resolve/convert/attach body into a shared `_convert_and_attach(book_id, target, source)` helper, and its skip-precheck logic into `_classify_convert(book, target) -> ("skip", reason) | ("ready", source)`. `convert_book` keeps its exact public contract (skip cases still raise `InvalidInputError` for the single tool). This is the one call site the bulk tool will reuse (no duplicated `ebook-convert`→`add_format` sequence).
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_p2.py` (extend)
**Depends on**: None
**Reuses**: `SqliteReader.format_files`/`get_book`, `EbookConvertRunner.convert`, `CalibredbRunner.add_format`, `backup_metadata_db`, `SUPPORTED_CONVERT_FORMATS`
**Requirement**: BCONV-01, BCONV-03, BCONV-04 (shared core)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `_classify_convert(book, target)` returns `("skip", "already has <FMT>")` when `target.upper() in book.formats`, `("skip", "no source format")` when `format_files` is empty, else `("ready", source_path)`; raises nothing for skip cases
- [ ] `_convert_and_attach(book_id, target, source)` converts into a `TemporaryDirectory` (cleaned up even on failure) and calls `add_format`; raises `EbookConvertError`/`CalibredbError` on real failure; does **no** backup (caller owns it)
- [ ] `convert_book` refactored to use both helpers: validate target → `get_book` → `_classify_convert` → skip → `raise InvalidInputError(reason)` (preserves current single-tool contract) → else `backup_metadata_db` → `_convert_and_attach` → re-read → return the unchanged CONV-01 dict
- [ ] The **existing CONV-01 tests pass unchanged** (behavior-preserving): `test_library_p2.py` convert cases green with no assertion edits
- [ ] New integration cases cover `_classify_convert`'s three outcomes (ready / already-has / no-source) directly
- [ ] Full gate passes: `uv run pytest -m "unit or integration" -q`
- [ ] Test count: existing convert tests still pass + ≥3 new cases (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `refactor(convert): extract shared convert core for reuse`

---

### T2: Add `CalibreLibrary.convert_book_bulk` facade

**What**: Facade method converting N books to one `target_format` via one backup + best-effort three-bucket loop (`converted`/`skipped`/`failed`), plus `_validate_bulk_convert_input`.
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_bulk_convert.py` (new)
**Depends on**: T1
**Reuses**: `_classify_convert`, `_convert_and_attach`, `backup_metadata_db`, `SqliteReader.get_book`, `SUPPORTED_CONVERT_FORMATS`
**Requirement**: BCONV-01, BCONV-02, BCONV-03, BCONV-04, BCONV-05, BCONV-06

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `_validate_bulk_convert_input(book_ids, target_format)` rejects (before any backup/convert): unsupported target (after `.lower()`); empty/duplicate/non-int (incl. `bool`) `book_ids`; `len(book_ids) > 50` — returns the normalized target (BCONV-06)
- [ ] One `backup_metadata_db` **before** the loop, returned as `backup` (unconditional, even if all-skipped) (BCONV-01)
- [ ] Loop over `sorted(book_ids)`: `get_book` → `_classify_convert` → skip → `skipped[{book_id, reason}]`; ready → `_convert_and_attach` → re-read → `converted[{book_id, formats}]`; any `CalibreMcpError` → `failed[{book_id, error}]` and continue (BCONV-02, BCONV-03, BCONV-04)
- [ ] Returns `status:"converted"`, `target_format`, `converted`, `skipped`, `failed`, `backup`; invariant `len(converted)+len(skipped)+len(failed)==len(book_ids)` holds (BCONV-05)
- [ ] Integration tests (scratch library w/ convertible source, assert read-back) cover: all-succeed batch preserves existing format + adds target + exactly one backup + 3 `converted` entries (Independent Test 1); mixed batch — already-has-target → `skipped`, missing id → `failed`, remaining id → `converted` (Independent Test 2); single-id degenerate batch; all-skipped batch (empty converted/failed, backup still present); no-source book → `skipped`; invariant assertion on the mixed batch; every BCONV-06 case — bad target, empty ids, duplicate id, non-int id, 51 rejected / 50 accepted
- [ ] Full gate passes: `uv run pytest -m "unit or integration" -q`
- [ ] Test count: ≥12 integration tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(bulk-convert): add convert_book_bulk facade with three-bucket partial-failure`

---

### T3: Expose `convert_book_bulk` MCP tool

**What**: New `@mcp.tool()` mirroring `convert_book`'s shape, wrapped by `_map_errors`, with a host-facing docstring documenting ADDITIVE/no-token, the 50-book cap, and the honest `converted`/`skipped`/`failed` contract (skipped = benign no-op).
**Where**: `src/calibre_mcp/server.py` (modify), `tests/e2e/test_server.py` (modify)
**Depends on**: T2
**Reuses**: `_map_errors`, `_get_library`, `_jsonify`; e2e `_call` helper and `scratch_library` wiring
**Requirement**: BCONV-01, BCONV-02, BCONV-03, BCONV-06

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `convert_book_bulk(book_ids, target_format)` delegates to the facade and returns its JSON-friendly dict (ids + format strings)
- [ ] Docstring: ADDITIVE (keeps existing formats), no confirmation token; documents the 50-book cap, the three buckets, and that `skipped` (already-has-format / no-source) is a benign no-op — not a failure; notes conversions are sequential and can be slow
- [ ] E2E tests (through `server.mcp.call_tool`): additive convert round-trip against scratch library asserts read-back (target present, original kept); a mixed batch returns all three buckets with correct routing; invalid input (bad target OR over-cap OR empty ids) surfaces a `ToolError`; stdout stays clean (new tool included in the stdout-hygiene assertion)
- [ ] Build gate passes: `uv run ruff check . && uv run pytest -q`
- [ ] Test count: ≥3 new e2e tests pass; full suite green (no silent deletions)

**Tests**: e2e
**Gate**: build
**Commit**: `feat(bulk-convert): expose convert_book_bulk MCP tool`

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: extract shared convert core | 2 private helpers + refactor 1 method, 1 file | ✅ Granular (cohesive) |
| T2: `convert_book_bulk` facade | 1 method + 1 validator, 1 file | ✅ Granular |
| T3: `convert_book_bulk` tool | 1 tool function | ✅ Granular |

## Diagram-Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| ---- | ----------------- | ------------- | ------ |
| T1 | None | (root) | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |

## Test Co-location Validation

| Task | Code Layer | Matrix Requires | Task Says | Status |
| ---- | ---------- | --------------- | --------- | ------ |
| T1 | Facade convert core | integration | integration | ✅ OK |
| T2 | Facade bulk | integration | integration | ✅ OK |
| T3 | Tool surface | e2e | e2e | ✅ OK |

---

## Requirement Coverage

| Requirement | Task(s) |
| --- | --- |
| BCONV-01 | T1, T2, T3 |
| BCONV-02 | T2, T3 |
| BCONV-03 | T1, T2, T3 |
| BCONV-04 | T1, T2 |
| BCONV-05 | T2 |
| BCONV-06 | T2, T3 |
