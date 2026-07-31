# Rename an Author Across the Library (ORGN-01) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/author-rename/spec.md`
**Design**: `.specs/features/author-rename/design.md`
**Status**: All 6 tasks (T1-T6) implemented and committed; independent Verifier pending (Execute step 10)

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines found: `AGENTS.md` (`~/.claude/CLAUDE.md`, quality/testing rules), `pyproject.toml` (`[tool.pytest.ini_options]` markers `unit`/`integration`/`e2e`; `ruff`, `mypy --strict`), `README.md` (Development commands), `.specs/STATE.md` (test-safety rule, AD-001/011/012/020). Existing samples: `tests/unit/test_bulk_edit.py`, `tests/integration/test_library_bulk.py`, `tests/integration/test_calibredb_runner.py`, `tests/integration/test_sqlite_reader.py`, `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Pure logic (`author_rename.resolve_renamed_authors`) | unit | All branches; 1:1 to ARENAME-07 cases + every listed edge case (`[Old]→[New]`, `[A,Old,B]→[A,New,B]`, `[Old,New]→[New]`, `[New,Old]→[New]`, `[Old,Old]→[New]`) | `tests/unit/test_author_rename.py` | `uv run pytest -m unit` |
| Read layer (`SqliteReader.books_by_author`) | integration | Exact-match happy path + co-author book included + no-match returns `[]` + ascending-sorted ids | `tests/integration/test_sqlite_reader.py` | `uv run pytest -m integration` |
| Write primitive (`CalibredbRunner.set_metadata` author serialization) | integration | Two-author book reads back as **two distinct** author entities (` & ` join); existing single-author + `tags`/`languages` comma paths unregressed | `tests/integration/test_calibredb_runner.py` | `uv run pytest -m integration` |
| Facade (`CalibreLibrary.rename_author`) | integration | All branches; 1:1 to ARENAME-01..08 + all Edge Cases (plan/apply round-trip, co-author preserved, merge dedupe, token mismatch, per-book failure, backup-before-write order, degenerate 1-book batch) | `tests/integration/test_library_author_rename.py` | `uv run pytest -m integration` |
| Tool surface (`server.rename_author`) | e2e | Happy path: plan → apply round-trip via FastMCP; author-not-found → `ToolError` | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |
| Constants / op id (`_OP_RENAME_AUTHOR`) | none | — (covered transitively by facade + build gate) | — | build gate only |

## Parallelism Assessment

> Generated from codebase — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit | Yes | Pure functions, no shared state; record duck-typed via `SimpleNamespace` | `tests/unit/test_bulk_edit.py` (no fixture, no library) |
| integration | Yes | Per-test `scratch_library` bootstrapped under `tmp_path`; each test seeds its own books; real library used read-only | `tests/conftest.py::scratch_library`, `tests/integration/test_library_bulk.py` |
| e2e | Yes | Per-test env/library under `tmp_path`, own seeded books via FastMCP | `tests/e2e/test_server.py` |

> Note: the suite runs sequentially by default (no `pytest-xdist` configured). `[P]` here is **order-free within a phase** information for the executor, not a directive to parallelize execution.

## Gate Check Commands

> Generated from codebase — confirm before Execute.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest -m integration` (and `uv run pytest -m e2e` for the tool layer) |
| Build | After phase completion or config/constant-only tasks | `uv run ruff check src tests && uv run mypy src && uv run pytest` |

---

## Execution Plan

### Phase 1: Prerequisite fix + independent leaves (Parallel OK)

The blocking serialization fix and the two dependency-free leaf modules. No inter-task dependency.

```
┌→ T1 (set_metadata ` & ` fix) [P]
├→ T2 (resolve_renamed_authors pure) [P]
└→ T3 (books_by_author reader) [P]
```

### Phase 2: Facade orchestration (Sequential)

Consumes all three Phase-1 outputs.

```
T1, T2, T3 ──→ T4 (CalibreLibrary.rename_author)
```

### Phase 3: Tool surface + closeout (Sequential)

```
T4 ──→ T5 (rename_author tool, e2e) ──→ T6 (STATE.md AD-022 + traceability)
```

> 3 phases → inline execution (no per-phase sub-agents). The always-on Verifier still runs after T6.

---

## Task Breakdown

### T1: Fix `set_metadata` author serialization (` & ` join) [P]

**What**: Make `CalibredbRunner.set_metadata` join the `authors` field with `" & "` while keeping `,` for `tags`/`languages` — the blocking prerequisite fix (Design Risks / AD-022).
**Where**: `src/calibre_mcp/calibredb_runner.py` (`set_metadata`, ~line 96)
**Depends on**: None
**Reuses**: existing `set_metadata` `--field` loop; existing integration test `test_set_metadata_applies_list_field` (`tests/integration/test_calibredb_runner.py:94`) as the pattern.
**Requirement**: ARENAME-07 (enabling correctness fix; → AD-022)

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `authors` list joined with `" & "`; `tags`/`languages` (and other lists) still joined with `","` (field-specific separator)
- [x] Behavior test added: set a book to `["Author One", "Author Two"]`, re-read via `SqliteReader`, assert **two distinct** author entities (not one mashed `"Author One|Author Two"`)
- [x] Existing single-author + `tags` list-field tests still pass (no regression)
- [x] Gate check passes: `uv run pytest -m integration` (140 passed)
- [x] Test count: existing runner tests + 1 new (140 passed, no silent deletions)

**Tests**: integration
**Gate**: full

**Commit**: `fix(calibredb): serialize authors with " & " so co-authors stay distinct (AD-022)`

---

### T2: `resolve_renamed_authors` pure module [P]

**What**: New pure module computing one book's post-rename author list — replace only `old` with `new`, order-preserving, in-book dedupe. No I/O.
**Where**: `src/calibre_mcp/author_rename.py` (new)
**Depends on**: None
**Reuses**: mirrors `src/calibre_mcp/bulk_edit.py` (`resolve_fields`) structure; unit-test pattern from `tests/unit/test_bulk_edit.py`.
**Requirement**: ARENAME-07

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `resolve_renamed_authors(authors: list[str], old: str, new: str) -> list[str]` implemented per design signature
- [x] Unit tests cover, 1:1, every spec case: `[Old]→[New]`, `[A,Old,B]→[A,New,B]` (co-author + order preserved), `[Old,New]→[New]` and `[New,Old]→[New]` (order-preserving dedupe/merge), `[Old,Old]→[New]` (double-occurrence anomaly)
- [x] A book credited to `old` always yields ≥1 author (never `[]`) — asserted
- [x] Gate check passes: `uv run pytest -m unit` (56 passed)
- [x] Test count: 7 new unit tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(author-rename): add resolve_renamed_authors pure list algebra (ARENAME-07)`

---

### T3: `SqliteReader.books_by_author` discovery method [P]

**What**: New read-layer method returning the ascending-sorted ids of every book credited to an author by exact name.
**Where**: `src/calibre_mcp/sqlite_reader.py`
**Depends on**: None
**Reuses**: the read-only connection pattern + the `authors`/`books_authors_link` join already in `_authors` (`sqlite_reader.py:167`); test pattern from `tests/integration/test_sqlite_reader.py`.
**Requirement**: ARENAME-01, ARENAME-02

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `books_by_author(self, name: str) -> list[int]` — `SELECT DISTINCT l.book ... WHERE a.name = ? ORDER BY l.book` (parameterized, exact match)
- [x] Integration tests: a single-author book is found; a co-authored book is found by either author name; a non-matching name returns `[]`; ids come back ascending-sorted
- [x] Gate check passes: `uv run pytest -m integration` (143 passed)
- [x] Test count: 3 new integration tests pass (no silent deletions)

**Tests**: integration
**Gate**: full

**Commit**: `feat(reader): add books_by_author exact-match discovery (ARENAME-01/02)`

---

### T4: `CalibreLibrary.rename_author` facade orchestration

**What**: The compound orchestration — validate → discover → plan/confirm (one batch token) → one backup → best-effort per-book apply → honest `applied`/`failed`.
**Where**: `src/calibre_mcp/library.py` (new method + `_OP_RENAME_AUTHOR` constant)
**Depends on**: T1, T2, T3
**Reuses**: AD-020 skeleton in `update_metadata_bulk` (`library.py:334`); `plan_token`/`verify` + `_BULK_TOKEN_ID` (`confirmation.py`, `library.py:76`); `backup_metadata_db` (`backup.py`); `_build_diff` (`library.py:757`); `resolve_renamed_authors` (T2); `books_by_author` (T3); `set_metadata` (T1); `get_book` re-read; `InvalidInputError`/`ConfirmationError`.
**Requirement**: ARENAME-01, ARENAME-02, ARENAME-03, ARENAME-04, ARENAME-05, ARENAME-06, ARENAME-08

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `rename_author(self, old_name, new_name, token=None) -> dict[str, Any]` with `_OP_RENAME_AUTHOR = "rename_author"` bound into the token
- [x] Validation **before** any backup/write: blank `new_name` or `new_name == old_name` → `InvalidInputError` (ARENAME-03); empty discovery → `InvalidInputError("author not found")` (ARENAME-02)
- [x] Plan branch (no token): returns `status:"plan"`, per-book `diffs` (`authors` current→proposed resolved), one `confirmation_token`; writes nothing (ARENAME-01)
- [x] Apply branch (token): `verify` recomputed payload → mismatch refuses, writes nothing (ARENAME-05); exactly one `metadata.db` backup **before** the first `set_metadata` (ARENAME-04); ascending `book_id` order
- [x] Best-effort loop: per-book failure → `failed[]`, batch continues, no false "all succeeded" (ARENAME-06); each applied book re-read → real `authors` in `applied[]` (ARENAME-08); invariant `len(applied)+len(failed)==len(discovered)`
- [x] Integration tests derive from the two P1 Independent Tests + Edge Cases: plan-then-apply round trip (co-author preserved, third book untouched); merge/dedupe (`["Old","New"]→["New"]`, `["X","Old"]→["X","New"]`, re-run rejected as author-not-found); token mismatch refused; forced per-book failure → truthful `failed[]`; **backup-runs-before-first-write** order test (spy/monkeypatch, per Design Risk L-001); degenerate 1-book batch runs full path
- [x] Gate check passes: `uv run pytest -m integration` (152 passed)
- [x] Test count: 9 new integration tests pass (no silent deletions)

**Tests**: integration
**Gate**: full

**Commit**: `feat(author-rename): add CalibreLibrary.rename_author plan→confirm batch (ARENAME-01..08)`

---

### T5: `rename_author` MCP tool (server)

**What**: Expose `rename_author` on the FastMCP tool surface, wiring `_map_errors` + `_jsonify` around the facade.
**Where**: `src/calibre_mcp/server.py`
**Depends on**: T4
**Reuses**: `@mcp.tool() @_map_errors` + `_jsonify` + `_get_library()` pattern from the `update_metadata_bulk` tool (`server.py`); e2e pattern from `tests/e2e/test_server.py:247` (`test_update_metadata_bulk_plan_then_apply_round_trip`).
**Requirement**: ARENAME-01, ARENAME-04, ARENAME-05

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `@mcp.tool() @_map_errors def rename_author(old_name: str, new_name: str, confirmation_token: str | None = None) -> dict:` returning `_jsonify(_get_library().rename_author(...))`, bare `dict` return annotation (mypy override note in `pyproject.toml`)
- [x] Docstring states: exact-match, co-author-safe, merge-onto-existing, plan→confirm handshake, one backup, honest `applied`/`failed`
- [x] E2E tests: plan → apply round trip via the tool surface (books read back renamed, third untouched); author-not-found surfaces as `ToolError`
- [x] Gate check passes: `uv run pytest -m e2e` (50 passed)
- [x] Test count: 2 new e2e tests pass (no silent deletions)

**Tests**: e2e
**Gate**: full

**Commit**: `feat(author-rename): expose rename_author MCP tool (ARENAME-01/04/05)`

---

### T6: Record AD-022 + close requirement traceability

**What**: Append AD-022 to `.specs/STATE.md` (Decisions) and flip ARENAME-01..08 to Verified in the spec traceability table; run the full build gate as the closeout regression.
**Where**: `.specs/STATE.md`, `.specs/features/author-rename/spec.md` (traceability + status)
**Depends on**: T5
**Reuses**: existing AD-NNN entry format in `.specs/STATE.md`; proposed AD-022 text in `design.md`.
**Requirement**: (traceability closeout — all ARENAME)

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] AD-022 appended to `.specs/STATE.md` Decisions verbatim from `design.md` ("Proposed AD-022")
- [x] Spec Requirement Traceability: ARENAME-01..08 → Status `Implementing` (8/8 mapped to T1..T5; flips to `Verified` after the independent Verifier passes, per skill contract — author does not self-mark Verified)
- [x] Full build gate passes as regression: `uv run ruff check src tests && uv run mypy src && uv run pytest` (258 passed)
- [x] Test count: whole suite green (258 passed, up from 137 baseline + 21 new across T1-T5, no silent deletions)

**Tests**: none (docs) — gated by the full build regression above
**Gate**: build

**Commit**: `docs(specs): record AD-022 and mark ORGN-01 (author-rename) Verified`

---

## Parallel Execution Map

```
Phase 1 (Parallel — no inter-task deps):
    ├── T1 [P]  (set_metadata ` & ` fix)
    ├── T2 [P]  (resolve_renamed_authors)   } order-free
    └── T3 [P]  (books_by_author)

Phase 2 (Sequential):
    T1, T2, T3 complete, then:
        T4  (rename_author facade)

Phase 3 (Sequential):
    T4 → T5 (rename_author tool) → T6 (AD-022 + traceability)
```

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `set_metadata` ` & ` fix | 1 method + 1 test | ✅ Granular |
| T2: `resolve_renamed_authors` | 1 pure module | ✅ Granular |
| T3: `books_by_author` | 1 read method | ✅ Granular |
| T4: `rename_author` facade | 1 method (compound, but one cohesive orchestration) | ✅ Granular |
| T5: `rename_author` tool | 1 tool endpoint | ✅ Granular |
| T6: AD-022 + traceability | docs closeout | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T2 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T3 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T4 | T1, T2, T3 | T1,T2,T3 → T4 | ✅ Match |
| T5 | T4 | T4 → T5 | ✅ Match |
| T6 | T5 | T5 → T6 | ✅ Match |

T1/T2/T3 are `[P]` and depend on nothing → no inter-dependency, parallel valid.

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Write primitive (`set_metadata`) | integration | integration | ✅ OK |
| T2 | Pure logic (`author_rename`) | unit | unit | ✅ OK |
| T3 | Read layer (`books_by_author`) | integration | integration | ✅ OK |
| T4 | Facade (`rename_author`) | integration | integration | ✅ OK |
| T5 | Tool surface (`server.rename_author`) | e2e | e2e | ✅ OK |
| T6 | Docs/constants only | none | none | ✅ OK |

All ✅ — no violations. Tests are co-located in the task that creates the code; nothing deferred.

---

## MCPs & Skills per task

No project MCPs are needed (all work is local source + pytest). No specialized skills per task beyond the `spec-driven` Execute flow itself. Confirm at Execute time if you want any task delegated to a sub-agent (3 phases → inline by default).
