# Rename a Tag Across the Library (ORGN-02) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/tag-rename/spec.md`
**Design**: `.specs/features/tag-rename/design.md`
**Status**: Ready — 5 tasks (T1-T5) planned; not yet executed.
**Precedent**: ORGN-01 (`author-rename`) Verified — this mirrors it, minus the serialization-fix task
(tags already join with `,`, AD-022; no prerequisite fix needed).

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines: `AGENTS.md` (quality/testing), `pyproject.toml` (`[tool.pytest.ini_options]` markers `unit`/`integration`/`e2e`; `ruff`, `mypy --strict`), `.specs/STATE.md` (test-safety rule, AD-001/011/012/020/022). Existing samples reused as patterns: `tests/unit/test_author_rename.py`, `tests/integration/test_library_author_rename.py`, `tests/integration/test_sqlite_reader.py`, `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Pure logic (`rename_resolve.resolve_renamed_values`) | unit | All branches; 1:1 to TRENAME-07 cases + every edge case (`[old]→[new]`, `[a,old,b]→[a,new,b]`, `[old,new]→[new]`, `[new,old]→[new]`, `[old,old]→[new]`); plus a regression assertion that `author_rename.resolve_renamed_authors` still returns identical results (alias intact) | `tests/unit/test_rename_resolve.py` (+ existing `test_author_rename.py` stays green) | `uv run pytest -m unit` |
| Read layer (`SqliteReader.books_by_tag`) | integration | Exact-match happy path (`"Poetry"` → `[9,15,17,19]` in the real library) + multi-tag book included + no-match returns `[]` + ascending-sorted ids | `tests/integration/test_sqlite_reader.py` | `uv run pytest -m integration` |
| Facade (`CalibreLibrary.rename_tag`) | integration | All branches; 1:1 to TRENAME-01..08 + Edge Cases (plan/apply round-trip, other-tag preserved as a **set**, merge dedupe, token mismatch, per-book failure, backup-before-write order, degenerate 1-book batch) | `tests/integration/test_library_tag_rename.py` | `uv run pytest -m integration` |
| Tool surface (`server.rename_tag`) | e2e | Happy path: plan → apply round-trip via FastMCP; tag-not-found → `ToolError` | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |
| Write primitive (`set_metadata` tags) | none | **No change** — tags already join with `,` (AD-022); covered transitively by facade + existing runner tests | — | build gate only |
| Constants / op id (`_OP_RENAME_TAG`) | none | — (covered transitively by facade + build gate) | — | build gate only |

## Parallelism Assessment

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit | Yes | Pure functions, no shared state | `tests/unit/test_author_rename.py` |
| integration | Yes | Per-test `scratch_library` under `tmp_path`; real library read-only | `tests/conftest.py::scratch_library`, `tests/integration/test_library_author_rename.py` |
| e2e | Yes | Per-test env/library under `tmp_path`, own seeded books via FastMCP | `tests/e2e/test_server.py` |

> Suite runs sequentially (no `pytest-xdist`). `[P]` = order-free within a phase, not a directive to parallelize execution.

## Gate Check Commands

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest -m integration` (and `uv run pytest -m e2e` for the tool layer) |
| Build | After phase completion or config/constant-only tasks | `uv run ruff check src tests && uv run mypy src && uv run pytest` |

---

## Execution Plan

### Phase 1: Independent leaves (Parallel OK)

Two dependency-free changes. No prerequisite serialization fix (unlike ORGN-01).

```
┌→ T1 (resolve_renamed_values pure + author re-export) [P]
└→ T2 (books_by_tag reader) [P]
```

### Phase 2: Facade orchestration (Sequential)

```
T1, T2 ──→ T3 (CalibreLibrary.rename_tag)
```

### Phase 3: Tool surface + closeout (Sequential)

```
T3 ──→ T4 (rename_tag tool, e2e) ──→ T5 (traceability closeout)
```

> 3 phases → inline execution (no per-phase sub-agents). The always-on Verifier still runs after T5.

---

## Task Breakdown

### T1: Generalize the pure resolver to `resolve_renamed_values` [P]

**What**: Extract ORGN-01's `resolve_renamed_authors` body verbatim into a shared pure module
`rename_resolve.py` as `resolve_renamed_values(values, old, new)`; make `author_rename.py`
re-export it as `resolve_renamed_authors` (thin alias — zero behavior change, ORGN-01 stays green).
**Where**: `src/calibre_mcp/rename_resolve.py` (new); `src/calibre_mcp/author_rename.py` (→ alias)
**Depends on**: None
**Reuses**: the exact body at `author_rename.py:13`; unit-test pattern from `tests/unit/test_author_rename.py`.
**Requirement**: TRENAME-07

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `rename_resolve.resolve_renamed_values(values: list[str], old: str, new: str) -> list[str]` holds the current algorithm byte-for-byte (replace old→new, order-preserving dedupe)
- [ ] `author_rename.resolve_renamed_authors` re-exports it (`resolve_renamed_authors = resolve_renamed_values`) — existing `from .author_rename import resolve_renamed_authors` importers unchanged
- [ ] New unit tests in `tests/unit/test_rename_resolve.py` cover, 1:1, every spec case: `[old]→[new]`, `[a,old,b]→[a,new,b]`, `[old,new]→[new]`, `[new,old]→[new]`, `[old,old]→[new]`, and the ≥1-element invariant
- [ ] Regression: existing `tests/unit/test_author_rename.py` still passes unchanged (alias intact)
- [ ] Gate check passes: `uv run pytest -m unit`
- [ ] Test count: new unit tests pass; no silent deletions

**Tests**: unit · **Gate**: quick

**Commit**: `refactor(rename): generalize resolver to resolve_renamed_values, share across author/tag`

---

### T2: `SqliteReader.books_by_tag` discovery method [P]

**What**: New read-layer method returning the ascending-sorted ids of every book carrying a tag by
exact name.
**Where**: `src/calibre_mcp/sqlite_reader.py`
**Depends on**: None
**Reuses**: the read-only connection pattern + the `tags`/`books_tags_link` join in `_tags` (`sqlite_reader.py:196`); structural clone of `books_by_author` (`sqlite_reader.py:137`); test pattern from `tests/integration/test_sqlite_reader.py:89`.
**Requirement**: TRENAME-01, TRENAME-02

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `books_by_tag(self, name: str) -> list[int]` — `SELECT DISTINCT l.book FROM books_tags_link l JOIN tags t ON t.id = l.tag WHERE t.name = ? ORDER BY l.book` (parameterized, exact match)
- [ ] Integration tests (real library, read-only): `books_by_tag("Poetry")` → `[9, 15, 17, 19]` (ascending); a multi-tag book is found (book 15); a non-matching tag returns `[]`
- [ ] Gate check passes: `uv run pytest -m integration`
- [ ] Test count: 3 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(reader): add books_by_tag exact-match discovery (TRENAME-01/02)`

---

### T3: `CalibreLibrary.rename_tag` facade orchestration

**What**: The compound orchestration — validate → discover → plan/confirm (one batch token) → one
backup → best-effort per-book apply → honest `applied`/`failed`. Structural twin of `rename_author`.
**Where**: `src/calibre_mcp/library.py` (new method + `_OP_RENAME_TAG` constant + `_tag_rename_plan_entry` helper)
**Depends on**: T1, T2
**Reuses**: AD-020 skeleton in `rename_author` (`library.py:401`); `plan_token`/`verify` + `_BULK_TOKEN_ID` (`confirmation.py`, `library.py:78`); `backup_metadata_db` (`backup.py`); `_build_diff` (`library.py:846`); `resolve_renamed_values` (T1); `books_by_tag` (T2); `set_metadata` (unchanged); `get_book` re-read; `InvalidInputError`/`ConfirmationError`.
**Requirement**: TRENAME-01, TRENAME-02, TRENAME-03, TRENAME-04, TRENAME-05, TRENAME-06, TRENAME-08

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `rename_tag(self, old_tag, new_tag, token=None) -> dict[str, Any]` with `_OP_RENAME_TAG = "rename_tag"` bound into the token
- [ ] Validation **before** any backup/write: blank `new_tag` or `new_tag == old_tag` → `InvalidInputError` (TRENAME-03); empty discovery → `InvalidInputError("tag not found")` (TRENAME-02)
- [ ] Plan branch (no token): `status:"plan"`, per-book `diffs` (`tags` current→proposed resolved), one `confirmation_token`; writes nothing (TRENAME-01)
- [ ] Apply branch (token): `verify` recomputed payload → mismatch refuses, writes nothing (TRENAME-05); exactly one `metadata.db` backup **before** the first `set_metadata` (TRENAME-04); ascending `book_id` order
- [ ] Best-effort loop: per-book failure → `failed[]`, batch continues (TRENAME-06); each applied book re-read → real `tags` in `applied[]` (TRENAME-08); invariant `len(applied)+len(failed)==len(discovered)`
- [ ] Integration tests derive from the two P1 Independent Tests + Edge Cases: plan-then-apply round trip (other tag preserved, third book untouched — assert tag **sets**); merge/dedupe (`["old","new"]→["new"]`, `["x","old"]→{"x","new"}`, re-run rejected as tag-not-found); token mismatch refused; forced per-book failure → truthful `failed[]`; **backup-runs-before-first-write** order test (monkeypatch, per Design Risk L-001); degenerate 1-book batch runs full path
- [ ] Gate check passes: `uv run pytest -m integration`
- [ ] Test count: ~9 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(tag-rename): add CalibreLibrary.rename_tag plan→confirm batch (TRENAME-01..08)`

---

### T4: `rename_tag` MCP tool (server)

**What**: Expose `rename_tag` on the FastMCP tool surface, wiring `_map_errors` + `_jsonify` around
the facade.
**Where**: `src/calibre_mcp/server.py`
**Depends on**: T3
**Reuses**: the `@mcp.tool() @_map_errors` + `_jsonify` + `_get_library()` pattern from the `rename_author` tool (`server.py:221`); e2e pattern from `tests/e2e/test_server.py:378`.
**Requirement**: TRENAME-01, TRENAME-04, TRENAME-05

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `@mcp.tool() @_map_errors def rename_tag(old_tag: str, new_tag: str, confirmation_token: str | None = None) -> dict:` returning `_jsonify(_get_library().rename_tag(...))`, bare `dict` return annotation
- [ ] Docstring states: exact-match, other-tag-safe, merge-onto-existing, plan→confirm handshake, one backup, honest `applied`/`failed`
- [ ] E2E tests: plan → apply round trip via the tool surface (books read back retagged, third untouched); tag-not-found surfaces as `ToolError`
- [ ] Gate check passes: `uv run pytest -m e2e`
- [ ] Test count: 2 new e2e tests pass; no silent deletions

**Tests**: e2e · **Gate**: full

**Commit**: `feat(tag-rename): expose rename_tag MCP tool (TRENAME-01/04/05)`

---

### T5: Close requirement traceability + STATE handoff

**What**: Flip TRENAME-01..08 to `Implementing` in the spec traceability table, add a short STATE.md
Decisions/handoff note that the value-rename resolver is now shared across ORGN-01/02 (no new AD),
and run the full build gate as the closeout regression. (Verifier flips to `Verified`, per skill
contract — author does not self-mark Verified.)
**Where**: `.specs/features/tag-rename/spec.md`, `.specs/STATE.md`
**Depends on**: T4
**Reuses**: existing AD/handoff entry format in `.specs/STATE.md`.
**Requirement**: (traceability closeout — all TRENAME)

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] Spec Requirement Traceability: TRENAME-01..08 → Status `Implementing` (8/8 mapped to T1..T4)
- [ ] `.specs/STATE.md` notes ORGN-02 shipped + the shared `resolve_renamed_values` (no new AD; reuses AD-011/012/020/022)
- [ ] Full build gate passes as regression: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- [ ] Test count: whole suite green (no silent deletions)

**Tests**: none (docs) — gated by the full build regression above · **Gate**: build

**Commit**: `docs(specs): mark ORGN-02 (tag-rename) implementing; record shared value-rename resolver`

---

## Parallel Execution Map

```
Phase 1 (Parallel — no inter-task deps):
    ├── T1 [P]  (resolve_renamed_values + author alias)
    └── T2 [P]  (books_by_tag)

Phase 2 (Sequential):
    T1, T2 complete, then:
        T3  (rename_tag facade)

Phase 3 (Sequential):
    T3 → T4 (rename_tag tool) → T5 (traceability closeout)
```

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `resolve_renamed_values` + alias | 1 pure module + 1 alias | ✅ Granular |
| T2: `books_by_tag` | 1 read method | ✅ Granular |
| T3: `rename_tag` facade | 1 method (compound, one cohesive orchestration) | ✅ Granular |
| T4: `rename_tag` tool | 1 tool endpoint | ✅ Granular |
| T5: traceability closeout | docs closeout | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T2 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T3 | T1, T2 | T1,T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |
| T5 | T4 | T4 → T5 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Pure logic (`rename_resolve`) | unit | unit | ✅ OK |
| T2 | Read layer (`books_by_tag`) | integration | integration | ✅ OK |
| T3 | Facade (`rename_tag`) | integration | integration | ✅ OK |
| T4 | Tool surface (`server.rename_tag`) | e2e | e2e | ✅ OK |
| T5 | Docs/constants only | none | none | ✅ OK |

All ✅ — tests co-located in the task that creates the code; nothing deferred.

---

## MCPs & Skills per task

No project MCPs are needed (all work is local source + pytest). No specialized skills per task beyond the `spec-driven` Execute flow. 3 phases → inline by default; confirm at Execute time if any task should be delegated to a sub-agent.
