# Rename/Merge a Series Across the Library (ORGN-04) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/series-rename/spec.md`
**Design**: `.specs/features/series-rename/design.md`
**Status**: Ready — 4 tasks (T1-T4) planned; not yet executed.
**Precedent**: ORGN-02 (`tag-rename`) Verified — this mirrors it, **minus** the resolver task (series
is single-valued: no `resolve_renamed_values`) and **plus** an explicit `series_index`-preservation
assertion (the one thing the siblings never faced).

> **Library-data note (affects test seeding):** the real library currently has **0 books in any
> series** (`series_unused` flag; verified read-only 2026-07-31). So — unlike ORGN-02's reader test,
> which anchored on the real library (`"Poetry"` → real ids) — ORGN-04's read-layer and facade tests
> **must seed a `scratch_library`** with books placed in a series (`calibredb add --empty` +
> `set_metadata --field series:… --field series_index:…`). No real-library read fixture applies here.

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines: `AGENTS.md` (quality/testing), `pyproject.toml` (`[tool.pytest.ini_options]` markers `unit`/`integration`/`e2e`; `ruff`, `mypy --strict`), `.specs/STATE.md` (test-safety rule, AD-001/011/012/020). Existing samples reused as patterns: `tests/integration/test_library_tag_rename.py`, `tests/integration/test_sqlite_reader.py`, `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Read layer (`SqliteReader.books_by_series`) | integration | Exact-match happy path over a **seeded scratch library** (2 books in series `Old`, 1 in `Other`) → returns the two `Old` ids ascending; a non-matching name returns `[]`; ascending-sorted ids | `tests/integration/test_sqlite_reader.py` | `uv run pytest -m integration` |
| Facade (`CalibreLibrary.rename_series`) | integration | All branches; 1:1 to SRENAME-01..08 + Edge Cases (plan/apply round-trip, **`series_index` preserved across the rename — fractional value like `7.5`**, merge-onto-existing, token mismatch, per-book failure, backup-before-write order, degenerate 1-book batch, series-not-found rejected before backup) | `tests/integration/test_library_series_rename.py` | `uv run pytest -m integration` |
| Tool surface (`server.rename_series`) | e2e | Happy path: plan → apply round-trip via FastMCP (book reads back new series **with original index**); series-not-found → `ToolError` | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |
| Write primitive (`set_metadata` series) | none | **No change** — `series` is a scalar `--field series:<name>`; index preserved by writing series only; covered transitively by facade + existing runner tests | — | build gate only |
| Constants / op id (`_OP_RENAME_SERIES`) | none | — (covered transitively by facade + build gate) | — | build gate only |

## Parallelism Assessment

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| integration | Yes | Per-test `scratch_library` under `tmp_path`; real library read-only (unused here) | `tests/conftest.py::scratch_library`, `tests/integration/test_library_tag_rename.py` |
| e2e | Yes | Per-test env/library under `tmp_path`, own seeded books via FastMCP | `tests/e2e/test_server.py` |

> Suite runs sequentially (no `pytest-xdist`). `[P]` = order-free within a phase, not a directive to parallelize execution.

## Gate Check Commands

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Full | After tasks with integration/e2e tests | `uv run pytest -m integration` (and `uv run pytest -m e2e` for the tool layer) |
| Build | After phase completion or config/constant-only tasks | `uv run ruff check src tests && uv run mypy src && uv run pytest` |

---

## Execution Plan

### Phase 1: Independent leaf

One dependency-free change (no resolver task — single-valued field).

```
→ T1 (books_by_series reader)
```

### Phase 2: Facade orchestration (Sequential)

```
T1 ──→ T2 (CalibreLibrary.rename_series)
```

### Phase 3: Tool surface + closeout (Sequential)

```
T2 ──→ T3 (rename_series tool, e2e) ──→ T4 (traceability closeout)
```

> 3 phases → inline execution (no per-phase sub-agents). The always-on Verifier still runs after T4.

---

## Task Breakdown

### T1: `SqliteReader.books_by_series` discovery method

**What**: New read-layer method returning the ascending-sorted ids of every book whose series is
`name`, by exact match.
**Where**: `src/calibre_mcp/sqlite_reader.py`
**Depends on**: None
**Reuses**: the read-only connection pattern + the `series`/`books_series_link` join in `_series` (`sqlite_reader.py:225`); structural clone of `books_by_tag` (`sqlite_reader.py:157`); scratch-seeding pattern from `tests/integration/test_library_tag_rename.py`.
**Requirement**: SRENAME-01, SRENAME-02

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `books_by_series(self, name: str) -> list[int]` — `SELECT DISTINCT l.book FROM books_series_link l JOIN series s ON s.id = l.series WHERE s.name = ? ORDER BY l.book` (parameterized, exact match)
- [ ] Integration tests over a **seeded scratch library** (2 books in series `Old`, 1 in `Other`): `books_by_series("Old")` → the two `Old` ids ascending; `books_by_series("Nope")` → `[]`; ids ascending-sorted
- [ ] Gate check passes: `uv run pytest -m integration`
- [ ] Test count: ~2-3 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(reader): add books_by_series exact-match discovery (SRENAME-01/02)`

---

### T2: `CalibreLibrary.rename_series` facade orchestration

**What**: The compound orchestration — validate → discover → plan/confirm (one batch token) → one
backup → best-effort per-book apply (**series field only, index preserved**) → honest
`applied`/`failed`. Structural twin of `rename_tag`, minus the resolver.
**Where**: `src/calibre_mcp/library.py` (new method + `_OP_RENAME_SERIES` constant + `_series_rename_plan_entry` helper)
**Depends on**: T1
**Reuses**: AD-020 skeleton in `rename_tag` (`library.py:507`); `plan_token`/`verify` + `_BULK_TOKEN_ID` (`confirmation.py`, `library.py:78`); `backup_metadata_db` (`backup.py`); `_build_diff` (`library.py:846`); `books_by_series` (T1); `set_metadata` (unchanged, series field only); `get_book` re-read (`series` + `series_index`); `InvalidInputError`/`ConfirmationError`.
**Requirement**: SRENAME-01, SRENAME-02, SRENAME-03, SRENAME-04, SRENAME-05, SRENAME-06, SRENAME-07, SRENAME-08

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `rename_series(self, old_series, new_series, token=None) -> dict[str, Any]` with `_OP_RENAME_SERIES = "rename_series"` bound into the token
- [ ] Validation **before** any backup/write: blank `new_series` or `new_series == old_series` → `InvalidInputError` (SRENAME-03); empty discovery → `InvalidInputError("series not found")` (SRENAME-02)
- [ ] Plan branch (no token): `status:"plan"`, per-book `diffs` (`series` current→`new_series`) + each book's unchanged `series_index` surfaced, one `confirmation_token`; writes nothing (SRENAME-01)
- [ ] Apply branch (token): `verify` recomputed payload → mismatch refuses, writes nothing (SRENAME-05); exactly one `metadata.db` backup **before** the first `set_metadata` (SRENAME-04); ascending `book_id` order
- [ ] Apply writes **`{"series": new_series}` only** — never `series_index` (SRENAME-07)
- [ ] Best-effort loop: per-book failure → `failed[]`, batch continues (SRENAME-06); each applied book re-read → real `series` + `series_index` in `applied[]` (SRENAME-08); invariant `len(applied)+len(failed)==len(discovered)`
- [ ] Integration tests derive from the two P1 Independent Tests + Edge Cases: plan-then-apply round trip (third book untouched); **`series_index` unchanged after rename — seed a book at index `7.5`, assert it reads back `7.5` under the new name** (the star assertion, per Design Risk); merge-onto-existing (book in `Old`#3.0 → `New`, existing `New`#1.0 untouched; re-run rejected as series-not-found); token mismatch refused; forced per-book failure → truthful `failed[]`; **backup-runs-before-first-write** order test (monkeypatch, per Design Risk L-001); degenerate 1-book batch runs full path
- [ ] Gate check passes: `uv run pytest -m integration`
- [ ] Test count: ~8 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(series-rename): add CalibreLibrary.rename_series plan→confirm batch (SRENAME-01..08)`

---

### T3: `rename_series` MCP tool (server)

**What**: Expose `rename_series` on the FastMCP tool surface, wiring `_map_errors` + `_jsonify`
around the facade.
**Where**: `src/calibre_mcp/server.py`
**Depends on**: T2
**Reuses**: the `@mcp.tool() @_map_errors` + `_jsonify` + `_get_library()` pattern from the `rename_tag` tool (`server.py`); e2e pattern from `tests/e2e/test_server.py`.
**Requirement**: SRENAME-01, SRENAME-04, SRENAME-05

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] `@mcp.tool() @_map_errors def rename_series(old_series: str, new_series: str, confirmation_token: str | None = None) -> dict:` returning `_jsonify(_get_library().rename_series(...))`, bare `dict` return annotation
- [ ] Docstring states: exact-match, **series_index preserved** (only the name changes), merge-onto-existing (index collisions left as-is), plan→confirm handshake, one backup, honest `applied`/`failed`
- [ ] E2E tests: plan → apply round trip via the tool surface (book reads back the new series **with its original index**); series-not-found surfaces as `ToolError`
- [ ] Gate check passes: `uv run pytest -m e2e`
- [ ] Test count: 2 new e2e tests pass; no silent deletions

**Tests**: e2e · **Gate**: full

**Commit**: `feat(series-rename): expose rename_series MCP tool (SRENAME-01/04/05)`

---

### T4: Close requirement traceability + STATE handoff

**What**: Flip SRENAME-01..08 to `Implementing` in the spec traceability table, add a short STATE.md
handoff note that ORGN-04 shipped (closing the AD-019 author/tag/series organization triad; series
rename writes the series field only to preserve `series_index` — no new AD), and run the full build
gate as the closeout regression. (Verifier flips to `Verified`, per skill contract — author does not
self-mark Verified.)
**Where**: `.specs/features/series-rename/spec.md`, `.specs/STATE.md`
**Depends on**: T3
**Reuses**: existing AD/handoff entry format in `.specs/STATE.md`.
**Requirement**: (traceability closeout — all SRENAME)

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [ ] Spec Requirement Traceability: SRENAME-01..08 → Status `Implementing` (8/8 mapped to T1..T3)
- [ ] `.specs/STATE.md` notes ORGN-04 shipped + closes the AD-019 organization triad (reuses AD-011/012/020; no new AD; series-field-only write preserves `series_index`)
- [ ] Full build gate passes as regression: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- [ ] Test count: whole suite green (no silent deletions)

**Tests**: none (docs) — gated by the full build regression above · **Gate**: build

**Commit**: `docs(specs): mark ORGN-04 (series-rename) implementing; record AD-019 triad closed`

---

## Parallel Execution Map

```
Phase 1 (leaf):
    └── T1  (books_by_series)

Phase 2 (Sequential):
    T1 complete, then:
        T2  (rename_series facade)

Phase 3 (Sequential):
    T2 → T3 (rename_series tool) → T4 (traceability closeout)
```

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `books_by_series` | 1 read method | ✅ Granular |
| T2: `rename_series` facade | 1 method (compound, one cohesive orchestration) | ✅ Granular |
| T3: `rename_series` tool | 1 tool endpoint | ✅ Granular |
| T4: traceability closeout | docs closeout | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Read layer (`books_by_series`) | integration | integration | ✅ OK |
| T2 | Facade (`rename_series`) | integration | integration | ✅ OK |
| T3 | Tool surface (`server.rename_series`) | e2e | e2e | ✅ OK |
| T4 | Docs/constants only | none | none | ✅ OK |

All ✅ — tests co-located in the task that creates the code; nothing deferred.

---

## MCPs & Skills per task

No project MCPs are needed (all work is local source + pytest). No specialized skills per task beyond the `spec-driven` Execute flow. 3 phases → inline by default; confirm at Execute time if any task should be delegated to a sub-agent.
</content>
