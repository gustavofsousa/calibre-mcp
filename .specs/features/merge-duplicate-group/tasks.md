# Merge a Duplicate Group (ORGN-03) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/merge-duplicate-group/spec.md`
**Design**: `.specs/features/merge-duplicate-group/design.md`
**Status**: Ready — 4 tasks (T1-T4) planned; not yet executed.
**Precedent**: `remove_book` (REM-01..05, Verified) for the recoverable-delete primitives; ORGN-01/02
for the AD-020 batch + AD-012 token shape. No new mutation primitive — pure orchestration.

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines: `AGENTS.md`, `pyproject.toml` (markers `unit`/`integration`/`e2e`; `ruff`, `mypy --strict`), `.specs/STATE.md` (test-safety rule, AD-001/011/012/017/020). Existing samples reused as patterns: `tests/integration/test_library_mutations.py` (REM-01..05, SAFE-03/04), `tests/integration/test_library_tag_rename.py` (AD-020 batch shape).

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Pure logic (`plan_loser_formats`) | unit | All branches: no overlap, full overlap, partial overlap, empty loser formats | `tests/unit/test_library.py` (or a small dedicated file if cleaner) | `uv run pytest -m unit` |
| Facade (`CalibreLibrary.merge_duplicate_group`) | integration | All branches; 1:1 to MERGE-01..08 + Edge Cases (plan/apply round-trip, format union on survivor, conflict survivor-wins, attach-failure keeps loser, token mismatch, backup-before-write order, degenerate single-loser batch, invalid-input rejects) | `tests/integration/test_library_merge_duplicate_group.py` | `uv run pytest -m integration` |
| Tool surface (`server.merge_duplicate_group`) | e2e | Happy path: plan → apply round-trip via FastMCP; invalid loser_ids → `ToolError` | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |
| Write primitives (`add_format`, `remove`, `trash_book_files`) | none | **No change** — all three already Verified (CONV-01, REM-01..05); covered transitively by facade | — | build gate only |
| Constants / op id (`_OP_MERGE_GROUP`) | none | — (covered transitively by facade + build gate) | — | build gate only |

## Parallelism Assessment

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit | Yes | Pure function, no shared state | `tests/unit/test_rename_resolve.py` |
| integration | Yes | Per-test `scratch_library` under `tmp_path`; real library read-only for sample files | `tests/conftest.py::scratch_library`, `tests/integration/test_library_mutations.py` |
| e2e | Yes | Per-test env/library under `tmp_path`, own seeded books via FastMCP | `tests/e2e/test_server.py` |

> Suite runs sequentially (no `pytest-xdist`). `[P]` = order-free within a phase.

## Gate Check Commands

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest -m integration` (and `uv run pytest -m e2e` for the tool layer) |
| Build | After phase completion or config/constant-only tasks | `uv run ruff check src tests && uv run mypy src && uv run pytest` |

---

## Execution Plan

### Phase 1: Pure leaf (standalone)

```
T1 (plan_loser_formats pure helper)
```

### Phase 2: Facade orchestration (Sequential)

Consumes T1's output plus the already-Verified `format_files`/`add_format`/`trash_book_files`/`remove`.

```
T1 ──→ T2 (CalibreLibrary.merge_duplicate_group)
```

### Phase 3: Tool surface + closeout (Sequential)

```
T2 ──→ T3 (merge_duplicate_group tool, e2e) ──→ T4 (traceability closeout)
```

> 3 phases → inline execution (no per-phase sub-agents). The always-on Verifier still runs after T4.

---

## Task Breakdown

### T1: `plan_loser_formats` pure helper

**What**: Compute, for one loser, which formats need to be added to the survivor vs. which are
already present — a pure set-split. No I/O.
**Where**: `src/calibre_mcp/library.py` (module-level helper, near `_build_diff`)
**Depends on**: None
**Reuses**: nothing new; mirrors the small-pure-helper style of `resolve_renamed_values`.
**Requirement**: MERGE-01, MERGE-07

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `plan_loser_formats(loser_formats: Iterable[str], survivor_formats: Iterable[str]) -> tuple[list[str], list[str]]` returns `(to_add, already_present)`, both sorted
- [ ] Unit tests cover: no overlap (`to_add=all`, `already_present=[]`), full overlap (`to_add=[]`, `already_present=all`), partial overlap, loser has no formats (`([],[])`)
- [ ] Gate check passes: `uv run pytest -m unit`
- [ ] Test count: 4 new unit tests pass; no silent deletions

**Tests**: unit · **Gate**: quick

**Commit**: `feat(merge-duplicate-group): add plan_loser_formats pure helper (MERGE-01/07)`

---

### T2: `CalibreLibrary.merge_duplicate_group` facade orchestration

**What**: The compound orchestration — validate → plan (per-loser format split) → confirm (one batch
token) → one backup → best-effort per-loser (attach formats, then recoverable trash+remove) → honest
`merged`/`failed`. Data-safe: a loser is removed only after all its formats are confirmed attached.
**Where**: `src/calibre_mcp/library.py` (new method + `_OP_MERGE_GROUP` constant)
**Depends on**: T1
**Reuses**: AD-020 skeleton (`rename_tag`, `library.py`); `plan_token`/`verify` + `_BULK_TOKEN_ID`; `backup_metadata_db`; `trash_book_files`; `CalibredbRunner.add_format`/`remove`; `SqliteReader.format_files`/`get_book`; `plan_loser_formats` (T1); `InvalidInputError`/`BookNotFoundError`.
**Requirement**: MERGE-01, MERGE-02, MERGE-03, MERGE-04, MERGE-05, MERGE-06, MERGE-07, MERGE-08

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `merge_duplicate_group(self, survivor_id, loser_ids, token=None) -> dict[str, Any]` with `_OP_MERGE_GROUP = "merge_duplicate_group"` bound into the token
- [ ] Validation **before** any backup/write: empty `loser_ids`, `survivor_id in loser_ids`, or duplicate ids → `InvalidInputError` (MERGE-03); `get_book(survivor_id)` and each loser → `BookNotFoundError` propagates if missing (MERGE-02)
- [ ] Plan branch (no token): per-loser `formats_to_add`/`formats_already_present` (via T1), `recoverable: True` + note, one `confirmation_token`; writes nothing (MERGE-01)
- [ ] Apply branch (token): `verify` recomputed payload → mismatch refuses, writes nothing (MERGE-05); exactly one `metadata.db` backup **before** the first mutation (MERGE-04); ascending `loser_id` order
- [ ] Best-effort loop, data-safe ordering: attach ALL of a loser's formats first (`add_format`, `--dont-replace` already in the primitive); only if every attach succeeds, `trash_book_files` + `runner.remove`; on any attach exception → `failed[]`, loser **NOT** removed (MERGE-06); invariant `len(merged)+len(failed)==len(loser_ids)`
- [ ] `merged[]` entries carry `formats_added` + `trash_location`; final re-read of `survivor.formats` returned as `survivor_formats` (MERGE-08)
- [ ] Integration tests derive from the two P1 Independent Tests + Edge Cases: plan-then-apply round trip (format union on survivor, conflict format not duplicated — MERGE-07); attach-failure keeps the loser present and unremoved (MERGE-06, monkeypatch `add_format` to raise); token mismatch refused; **backup-runs-before-first-mutation** order test (monkeypatch, per Design Risk L-001); degenerate single-loser batch runs full path; invalid inputs (empty loser_ids, survivor in loser_ids, duplicate loser_ids, unknown survivor/loser id) all reject before backup
- [ ] Gate check passes: `uv run pytest -m integration`
- [ ] Test count: ~9 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(merge-duplicate-group): add CalibreLibrary.merge_duplicate_group plan→confirm batch (MERGE-01..08)`

---

### T3: `merge_duplicate_group` MCP tool (server)

**What**: Expose `merge_duplicate_group` on the FastMCP tool surface, wiring `_map_errors` +
`_jsonify` around the facade.
**Where**: `src/calibre_mcp/server.py`
**Depends on**: T2
**Reuses**: the `@mcp.tool() @_map_errors` + `_jsonify` + `_get_library()` pattern from `remove_book`/`rename_tag` tools; e2e pattern from `tests/e2e/test_server.py` (`rename_tag` block).
**Requirement**: MERGE-01, MERGE-04, MERGE-05

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `@mcp.tool() @_map_errors def merge_duplicate_group(survivor_id: int, loser_ids: list[int], confirmation_token: str | None = None) -> dict:` returning `_jsonify(_get_library().merge_duplicate_group(...))`, bare `dict` return annotation
- [ ] Docstring states: caller-chosen survivor, formats-only merge, survivor-wins on conflict, recoverable delete, attach-before-delete data-safety, plan→confirm handshake, one backup, honest `merged`/`failed`
- [ ] E2E tests: plan → apply round trip via the tool surface (survivor gains the loser's unique format, loser is gone); invalid loser_ids (empty or self-referential) surfaces as `ToolError`
- [ ] Gate check passes: `uv run pytest -m e2e`
- [ ] Test count: 2 new e2e tests pass; no silent deletions

**Tests**: e2e · **Gate**: full

**Commit**: `feat(merge-duplicate-group): expose merge_duplicate_group MCP tool (MERGE-01/04/05)`

---

### T4: Close requirement traceability

**What**: Flip MERGE-01..08 to `Implementing` in the spec traceability table, run the full build gate
as the closeout regression. (Independent Verifier flips to `Verified`, per skill contract — author
does not self-mark Verified.)
**Where**: `.specs/features/merge-duplicate-group/spec.md`
**Depends on**: T3
**Reuses**: existing traceability table format.
**Requirement**: (traceability closeout — all MERGE)

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] Spec Requirement Traceability: MERGE-01..08 → Status `Implementing` (8/8 mapped to T1..T3)
- [ ] Full build gate passes as regression: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- [ ] Test count: whole suite green (no silent deletions)

**Tests**: none (docs) — gated by the full build regression above · **Gate**: build

**Commit**: `docs(specs): mark ORGN-03 (merge-duplicate-group) implementing`

---

## Parallel Execution Map

```
Phase 1 (standalone):
    T1  (plan_loser_formats)

Phase 2 (Sequential):
    T1 complete, then:
        T2  (merge_duplicate_group facade)

Phase 3 (Sequential):
    T2 → T3 (merge_duplicate_group tool) → T4 (traceability closeout)
```

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `plan_loser_formats` | 1 pure helper | ✅ Granular |
| T2: `merge_duplicate_group` facade | 1 method (compound, one cohesive orchestration) | ✅ Granular |
| T3: `merge_duplicate_group` tool | 1 tool endpoint | ✅ Granular |
| T4: traceability closeout | docs closeout | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | -------------- | ------ |
| T1 | None | Phase-1 standalone, no arrows in | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Pure logic (`plan_loser_formats`) | unit | unit | ✅ OK |
| T2 | Facade (`merge_duplicate_group`) | integration | integration | ✅ OK |
| T3 | Tool surface (`server.merge_duplicate_group`) | e2e | e2e | ✅ OK |
| T4 | Docs/constants only | none | none | ✅ OK |

All ✅ — tests co-located in the task that creates the code; nothing deferred.

---

## MCPs & Skills per task

No project MCPs are needed (all work is local source + pytest). No specialized skills per task beyond the `spec-driven` Execute flow. 3 phases → inline by default.
