# Library Baseline Stats (STATS-01) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute
flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source
of truth for the full flow (per-task cycle, gate, atomic commit, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/library-stats/design.md`
**Status**: Draft

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute.
> Guidelines found: `~/.claude/CLAUDE.md` (tests derive from acceptance criteria, runner decides,
> no weakening tests) + `pyproject.toml` (`[tool.pytest.ini_options]` markers, `ruff` select
> E/F/I/UP/B). Existing tests sampled: `tests/integration/test_sqlite_reader.py`,
> `tests/integration/test_library_reads.py`, `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| `sqlite_reader.py` — `library_stats()` + `LibraryStats` | integration | Key query paths + edge: every AC-1 sub-object present; empty-library zeroed snapshot; determinism (two calls identical); grounded facts (170 books, 64 placeholder pubdates, 14 Unknown authors, "A fé explicada" dup) | `tests/integration/test_sqlite_reader.py` (extend) | `uv run pytest` |
| `library.py` facade — `library_stats()` | integration | AC-1 full shape composed; `duplicate_title_groups` reuses `find_duplicate_groups()`; no `sqlite3`/`subprocess` touched; empty-library path | `tests/integration/test_library_reads.py` (extend) | `uv run pytest` |
| `server.py` — `calibre://library/stats` resource + `_map_resource_errors` | e2e | Happy round-trip (`totals.books` matches `count_books`, known dup present); empty-library; unreadable-db → `ResourceError` naming failure; two reads identical (AC-5); **stdout stays clean** | `tests/e2e/test_server.py` (extend) | `uv run pytest` |

**Coverage Expectation basis:** strong default (domain/read logic 1:1 to spec ACs, all listed edge
cases; route/e2e = happy + edge + error) — the read layer is the domain logic here.

## Parallelism Assessment

> Generated from codebase — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --- | --- | --- | --- |
| integration (reader) | Yes (read-only) | Points `SqliteReader` at `real_library`/`scratch_library`; no shared mutable state | `tests/integration/test_sqlite_reader.py:47` (`reader` fixture, read-only) |
| integration (facade) | Yes | Per-test `CalibreLibrary` over a fixture library | `tests/integration/test_library_reads.py` construction pattern |
| e2e (resource) | No | Mutates module-global `server._library` singleton via `monkeypatch.setattr(server, "_library", None)` | `tests/e2e/test_server.py:83` |

Tasks form a linear chain (T1→T2→T3), so no `[P]` applies regardless.

## Gate Check Commands

> Generated from codebase — confirm before Execute.

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest` |
| Build | After phase completion or final task | `uv run ruff check src tests && uv run pytest` |

---

## Execution Plan

### Phase 1: Read layer (Sequential)

```
T1
```

### Phase 2: Facade compose (Sequential)

```
T1 → T2
```

### Phase 3: Resource surface (Sequential)

```
T2 → T3
```

3 phases, one task each, linear — executed inline (no sub-agent offer; threshold is >3 phases).

---

## Task Breakdown

### T1: Add `SqliteReader.library_stats()` + `LibraryStats` dataclass

**What**: One read method (single `mode=ro` connection) computing the full aggregate profile
(totals, formats, languages+unset, metadata_completeness, identifier_types, authors, tags,
data_quality minus duplicate groups), returned as a typed `LibraryStats`.
**Where**: `src/calibre_mcp/sqlite_reader.py` (add dataclass + method); tests in
`tests/integration/test_sqlite_reader.py`.
**Depends on**: None
**Reuses**: `SqliteReader._connect()` (`sqlite_reader.py:57`); query set + grounded facts from
design §Data Models.
**Requirement**: STATS-01-01, STATS-01-02, STATS-01-05, STATS-01-06

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `LibraryStats` dataclass added with the design fields (all JSON-friendly).
- [x] `library_stats()` computes every AC-1 sub-object in ONE connection; `unset` language bucket
      present; `pct` guarded to `0.0` when `books == 0`; `comments` filled = row exists AND
      non-empty text; every list/top query has an explicit tie-breaker (`… DESC, name ASC`).
- [x] Integration tests assert, against `real_library` (read-only): `totals.books == count_books()`,
      `placeholder_pubdate_0101 == 64`, `unknown_author_books == 14`, `next_id_hint == max_id+1`,
      and that two consecutive calls return equal snapshots (AC-5).
- [x] Integration test against `scratch_library` (empty) returns a zeroed/empty snapshot, no error
      (AC-2).
- [x] Full gate passes: `uv run pytest`; Test count: ≥4 new tests pass (no silent deletions).

**Tests**: integration
**Gate**: full

**Commit**: `feat(reader): add library_stats aggregate profile (STATS-01)`

---

### T2: Add `CalibreLibrary.library_stats()` facade compose

**What**: Facade method that calls `self._reader.library_stats()` + `self._reader
.find_duplicate_groups()` and composes the AC-1 JSON dict, adding
`data_quality_flags.duplicate_title_groups` via the existing group shaping.
**Where**: `src/calibre_mcp/library.py` (add method); tests in
`tests/integration/test_library_reads.py`.
**Depends on**: T1
**Reuses**: `SqliteReader.find_duplicate_groups()` (`sqlite_reader.py:268`);
`CalibreLibrary._shape_duplicate_group()` (`library.py:387`); `dataclasses.asdict`.
**Requirement**: STATS-01-01, STATS-01-06

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `library_stats() -> dict` returns the full AC-1 shape; `data_quality_flags
      .duplicate_title_groups` reuses `find_duplicate_groups()` output (no second dedupe impl).
- [x] Method touches no `sqlite3`/`subprocess` directly (invariant AD-001).
- [x] Integration test against `real_library` asserts the "A fé explicada" duplicate (ids 68 & 132)
      appears in `duplicate_title_groups` and the top-10 author/tag lists are length-capped and
      ordered.
- [x] Integration test against `scratch_library` returns the same shape with empty lists / zero
      counts (AC-2).
- [x] Full gate passes: `uv run pytest`; Test count: ≥2 new tests pass (no silent deletions).

**Tests**: integration
**Gate**: full

**Commit**: `feat(library): compose library_stats profile with duplicate flags (STATS-01)`

---

### T3: Register `calibre://library/stats` resource + `_map_resource_errors`

**What**: Add the FastMCP resource handler that returns `_get_library().library_stats()` as JSON,
wrapped by a new `_map_resource_errors` that surfaces `CalibreMcpError`/`sqlite3.Error`/`OSError`
as `ResourceError`.
**Where**: `src/calibre_mcp/server.py` (add decorator + mapper); tests in
`tests/e2e/test_server.py`.
**Depends on**: T2
**Reuses**: `_get_library()` (`server.py:41`); `_map_errors` shape (`server.py:53`);
`ResourceError` from `mcp.server.fastmcp.exceptions`; e2e `env`/`seeded` fixtures + `read_resource`
(`server.mcp.read_resource(uri)`).
**Requirement**: STATS-01-01, STATS-01-03, STATS-01-04, STATS-01-05

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] `@mcp.resource("calibre://library/stats", name="library_stats",
      mime_type="application/json")` handler returns the facade dict.
- [x] `_map_resource_errors` catches `CalibreMcpError` + `sqlite3.Error`/`OSError`, raises
      `ResourceError(str(exc))` naming the failure (AC-4).
- [x] E2E test reads the resource on a seeded scratch library and asserts `totals.books` matches
      and the profile shape is well-formed (AC-1); a second read returns identical bytes (AC-5).
- [x] E2E test: pointing the server at a missing/corrupt `metadata.db` yields a `ResourceError`
      naming the failure, never an empty/wrong profile (AC-4).
- [x] E2E test: reading the resource writes NOTHING to stdout (extend the stdout-clean assertion).
- [x] Build gate passes: `uv run ruff check src tests && uv run pytest`; Test count: ≥3 new tests
      pass (no silent deletions).

**Tests**: e2e
**Gate**: build

**Commit**: `feat(server): expose calibre://library/stats resource (STATS-01)`

---

## Parallel Execution Map

```
Phase 1 (Sequential):  T1
Phase 2 (Sequential):  T1 ──→ T2
Phase 3 (Sequential):  T2 ──→ T3
```

No `[P]` tasks — the chain is strictly linear (each layer depends on the one below).

---

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1: reader `library_stats()` + dataclass | 1 method + 1 dataclass, 1 file | ✅ Granular |
| T2: facade `library_stats()` compose | 1 method, 1 file | ✅ Granular |
| T3: resource + error mapper | 1 handler + 1 helper, 1 file | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | (root) | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | `sqlite_reader.py` read logic | integration | integration | ✅ OK |
| T2 | `library.py` facade | integration | integration | ✅ OK |
| T3 | `server.py` resource + mapper | e2e | e2e | ✅ OK |

All tasks co-locate their required tests; no deferral.
