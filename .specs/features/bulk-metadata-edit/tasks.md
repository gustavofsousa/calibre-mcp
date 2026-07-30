# Bulk Metadata Edit (BULK-01) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, gate, atomic commit, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/bulk-metadata-edit/design.md`
**Status**: Approved

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec. Guidelines found: `CLAUDE.md` (test-safety rule, spec-derived tests), `.specs/STATE.md` (AD-001/AD-005 invariants, scratch-library rule), `pyproject.toml` (pytest markers unit/integration/e2e, ruff). Existing test samples: `tests/unit/test_confirmation.py`, `tests/integration/test_library_mutations.py`, `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Pure module (`bulk_edit.py`) | unit | All branches; 1:1 to BEDIT-08/09 ACs; every list-mode edge case (union-dedup, ignore-missing, empty result, replace pass-through, non-list passthrough) | `tests/unit/test_bulk_edit.py` | `uv run pytest -m unit -q` |
| Facade (`CalibreLibrary.update_metadata_bulk`) | integration | All branches; 1:1 to BEDIT-01..09 ACs + every listed edge case (single-id, vanished-id, remove-to-empty, invalid list_mode, list_mode w/o list field) | `tests/integration/test_library_bulk.py` | `uv run pytest -m "unit or integration" -q` |
| Tool surface (`server.update_metadata_bulk`) | e2e | Contract: plan (no token) + apply (token) round-trip, partial-failure shape, invalid input → ToolError, docstring guidance | `tests/e2e/test_server.py` | `uv run pytest -q` |

**Coverage Expectation** set from the strong default (domain logic 1:1 to spec ACs; every listed edge case has a test) — conforms to CLAUDE.md "tests derive from acceptance criteria."

## Parallelism Assessment

> Generated from codebase.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit | Yes | Pure functions, no shared state | `tests/unit/test_confirmation.py` (no fixtures, no I/O) |
| integration | Yes (per-test) | Per-test `scratch_library` in `tmp_path` | `tests/conftest.py:20` `scratch_library` fixture |
| e2e | No | Mutates module-global `server._library`; env-var/config swap per test | `tests/e2e/test_server.py` rebinds `server._library` |

Phases are sequential by dependency regardless; `[P]` unused.

## Gate Check Commands

> Generated from codebase (uv + pytest + ruff per `.specs/STATE.md` Handoff).

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit -q` |
| Full | After tasks with integration tests | `uv run pytest -m "unit or integration" -q` |
| Build | After the last task / e2e / full feature | `uv run ruff check . && uv run pytest -q` |

---

## Execution Plan

### Phase 1: Pure set algebra (Sequential)

```
T1
```

### Phase 2: Facade orchestration (Sequential)

```
T1 → T2
```

### Phase 3: Tool surface (Sequential)

```
T2 → T3
```

---

## Task Breakdown

### T1: Create `bulk_edit.py` pure list-mode module

**What**: New leaf module with `LIST_FIELDS`, `LIST_MODES`, `apply_list_mode`, `resolve_fields` — the only new logic in BULK-01, kept pure (no I/O).
**Where**: `src/calibre_mcp/bulk_edit.py` (new), `tests/unit/test_bulk_edit.py` (new)
**Depends on**: None
**Reuses**: nothing (new leaf module; duck-typed `Book` via `getattr`)
**Requirement**: BEDIT-08, BEDIT-09

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `LIST_FIELDS = frozenset({"authors", "tags", "languages"})`, `LIST_MODES = frozenset({"replace", "add", "remove"})`
- [ ] `apply_list_mode(current, supplied, mode)`: `add` = order-preserving union (idempotent, no dup); `remove` = current minus supplied (missing ignored); `replace` = supplied as-is (BEDIT-08 AC1-3, BEDIT-09)
- [ ] `resolve_fields(current_book, fields, mode)`: list fields under non-`replace` mode resolved via `apply_list_mode`; every other field passed through unchanged — single source for plan diff AND write (BEDIT-08 AC4)
- [ ] Unit tests cover: add-union-dedup, add-idempotent, remove-difference, remove-ignore-missing, remove-to-empty, replace-passthrough, resolve mixed list+scalar fields, resolve non-list field untouched under add/remove
- [ ] Quick gate passes: `uv run pytest -m unit -q`
- [ ] Test count: ≥8 unit tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick
**Commit**: `feat(bulk-edit): add pure list-mode set algebra module`

---

### T2: Add `CalibreLibrary.update_metadata_bulk` facade

**What**: Facade method broadcasting `fields` to N books via plan→confirm, one backup, best-effort per-book apply, plus `_validate_bulk_input` and `_bulk_plan_entry` private helpers.
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_bulk.py` (new)
**Depends on**: T1
**Reuses**: `bulk_edit.resolve_fields`, `_validate_edit_fields`, `_build_diff` shape, `plan_token`/`verify`, `backup_metadata_db`, `SqliteReader.get_book`, `CalibredbRunner.set_metadata`
**Requirement**: BEDIT-01, BEDIT-02, BEDIT-03, BEDIT-04, BEDIT-05, BEDIT-06, BEDIT-07, BEDIT-08, BEDIT-09

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `_validate_bulk_input(book_ids, fields, list_mode)` rejects (before any token/backup/write): empty/duplicate/non-int (incl. `bool`) `book_ids`; `list_mode ∉ LIST_MODES`; empty `fields` or fails `_validate_edit_fields`; `list_mode ∈ {add,remove}` with no `LIST_FIELDS` member in `fields` (BEDIT-06 + edge cases)
- [ ] Plan branch (no token): `sorted(book_ids)`; vanished id → `{book_id, found: False}`, existing id → `{book_id, found: True, diff}` with `proposed` = resolved set; returns `status:"plan"`, `list_mode`, `diffs`, `confirmation_token` (sentinel id `0`, payload `{book_ids: sorted, fields, list_mode}`); writes nothing (BEDIT-01, BEDIT-08 AC4)
- [ ] Apply branch (token): `verify` (BEDIT-03) → `backup_metadata_db` ONCE before loop (BEDIT-05) → iterate `sorted(book_ids)`: get_book → resolve_fields → set_metadata → re-read affected fields → `applied`; `CalibreMcpError` per book → `failed` and continue (BEDIT-04); returns `status:"applied"`, `applied`, `failed`, `backup`, `list_mode`; invariant `len(applied)+len(failed)==len(book_ids)`
- [ ] Applied entries re-read affected fields only: `{name: getattr(reread, name) for name in fields}` (BEDIT-07)
- [ ] Integration tests (scratch library, assert read-back) cover: plan diff+token no-write; apply all-succeed + exactly one backup; token mismatch refused no-write; one vanished id → other books applied + failed reported (Independent Test 1); add preserves existing (`[a,b]` + add `[b,c]` → `[a,b,c]`); remove ignores missing (`remove [a,z]` → `[b,c]`) (Independent Test 2); remove-to-empty writes `[]`; single-id degenerate batch; every BEDIT-06 invalid-input case; list_mode w/o list field rejected
- [ ] Full gate passes: `uv run pytest -m "unit or integration" -q`
- [ ] Test count: ≥13 integration tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(bulk-edit): add update_metadata_bulk facade with plan/confirm and list modes`

---

### T3: Expose `update_metadata_bulk` MCP tool

**What**: New `@mcp.tool()` mirroring `update_metadata`'s shape, wrapped by `_map_errors`, with host-facing docstring documenting `list_mode`, the per-book plan, and the honest `applied`/`failed` partial-failure contract.
**Where**: `src/calibre_mcp/server.py` (modify), `tests/e2e/test_server.py` (modify)
**Depends on**: T2
**Reuses**: `_map_errors`, `_book_to_dict`, `_get_library`; e2e `_call` helper and `scratch_library` wiring
**Requirement**: BEDIT-01, BEDIT-02, BEDIT-04, BEDIT-06

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `update_metadata_bulk(book_ids, fields, list_mode="replace", confirmation_token=None)` delegates to the facade and shapes output (re-read fields are already plain values, so JSON-friendly)
- [ ] Docstring instructs the HOST to surface the per-book plan and only re-call with the token after approval; documents `list_mode` (replace=overwrite footgun / add / remove) and the honest `applied`/`failed` contract; notes Calibre may re-normalize written list values
- [ ] E2E tests (through `server.mcp.call_tool`): plan→apply round-trip against scratch library asserts read-back; a partial-failure batch returns both `applied` and `failed`; empty `book_ids` (or unknown field) surfaces a `ToolError`; stdout stays clean
- [ ] Build gate passes: `uv run ruff check . && uv run pytest -q`
- [ ] Test count: ≥3 new e2e tests pass; full suite green (no silent deletions)

**Tests**: e2e
**Gate**: build
**Commit**: `feat(bulk-edit): expose update_metadata_bulk MCP tool`

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `bulk_edit.py` pure module | 1 leaf module (4 cohesive symbols) | ✅ Granular |
| T2: `update_metadata_bulk` facade | 1 method + 2 private helpers, 1 file | ✅ Granular (cohesive) |
| T3: `update_metadata_bulk` tool | 1 tool function | ✅ Granular |

## Diagram-Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| ---- | ----------------- | ------------- | ------ |
| T1 | None | (root) | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |

## Test Co-location Validation

| Task | Code Layer | Matrix Requires | Task Says | Status |
| ---- | ---------- | --------------- | --------- | ------ |
| T1 | Pure module | unit | unit | ✅ OK |
| T2 | Facade | integration | integration | ✅ OK |
| T3 | Tool surface | e2e | e2e | ✅ OK |

---

## Requirement Coverage

| Requirement | Task(s) |
| --- | --- |
| BEDIT-01 | T2, T3 |
| BEDIT-02 | T2, T3 |
| BEDIT-03 | T2 |
| BEDIT-04 | T2, T3 |
| BEDIT-05 | T2 |
| BEDIT-06 | T2, T3 |
| BEDIT-07 | T2 |
| BEDIT-08 | T1, T2 |
| BEDIT-09 | T1, T2 |
