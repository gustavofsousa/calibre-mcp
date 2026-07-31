# Read a Book's Cover (COVER-01) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/cover-read/spec.md`
**Design**: `.specs/features/cover-read/design.md`
**Status**: Ready — 3 tasks (T1–T3) planned; not yet executed.
**Precedent**: `SqliteReader.format_files` (AD-017, Verified) — `cover_file` is its cover-scoped
sibling. The one new surface is the tool returning **image content** (first non-text result).

> **Library-data note (affects test seeding):** covers must be **seeded into a `scratch_library`** —
> do not depend on the real library's covers. Seed with `calibredb add --empty` +
> `calibredb set_metadata <id> --field cover:<image>`. Because Pillow/ImageMagick are **not**
> guaranteed present, generate a valid cover image in-test with a stdlib **zlib-PNG** helper
> (calibre re-encodes it to `cover.jpg` — verified 2026-07-31; a hand-built 100×150 PNG produced a
> 392-byte `cover.jpg` and flipped `has_cover` 0→1). A degenerate 1×1 PNG is rejected by Qt
> ("Image is empty") — the helper must emit a real multi-pixel image.

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines: `AGENTS.md` (quality/testing), `pyproject.toml` (`[tool.pytest.ini_options]` markers `unit`/`integration`/`e2e`; `ruff`, `mypy --strict`), `.specs/STATE.md` (test-safety rule, AD-001/017). Existing samples reused as patterns: `tests/integration/test_sqlite_reader.py`, `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Read layer (`SqliteReader.cover_file`) | integration | Over a **seeded scratch library**: covered book → returns its `cover.jpg` `Path` (`is_file()` true); uncovered book (`has_cover=0`) → `None`; unknown id → `BookNotFoundError`; covered book with `cover.jpg` deleted (has_cover left 1) → `InvalidInputError` | `tests/integration/test_sqlite_reader.py` | `uv run pytest -m integration` |
| Facade (`CalibreLibrary.read_cover`) | integration | Covered → `{has_cover: True, cover_path: <str>}`; uncovered → `{has_cover: False, cover_path: None}`; unknown id → `BookNotFoundError`; **no `metadata.db` backup created** by any call (RCOVER-05) | `tests/integration/test_library_read_cover.py` | `uv run pytest -m integration` |
| Tool surface (`server.read_cover`) | e2e | Covered → image content with MIME `image/jpeg` and non-empty data (RCOVER-01); uncovered → structured `{has_cover: False}` (RCOVER-02); unknown id → `ToolError` (RCOVER-03) | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |
| `_map_errors` generic re-type | none | Pure typing change; covered transitively by the whole existing tool suite + `mypy --strict` | — | build gate only |

## Parallelism Assessment

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| integration | Yes | Per-test `scratch_library` under `tmp_path`; real library read-only (unused here) | `tests/conftest.py::scratch_library`, `tests/integration/test_sqlite_reader.py` |
| e2e | Yes | Per-test env/library under `tmp_path`, own seeded book via FastMCP | `tests/e2e/test_server.py` |

> Suite runs sequentially (no `pytest-xdist`). `[P]` = order-free within a phase, not a directive to parallelize execution.

## Gate Check Commands

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Full | After tasks with integration/e2e tests | `uv run pytest -m integration` (and `uv run pytest -m e2e` for the tool layer) |
| Build | After phase completion or typing/docs-only tasks | `uv run ruff check src tests && uv run mypy src && uv run pytest` |

---

## Execution Plan

### Phase 1: Independent leaf

```
→ T1 (SqliteReader.cover_file reader)
```

### Phase 2: Facade

```
T1 ──→ T2 (CalibreLibrary.read_cover)
```

### Phase 3: Tool surface + closeout (Sequential)

```
T2 ──→ T3 (read_cover tool + _map_errors generic + traceability closeout)
```

> 3 phases → inline execution (no per-phase sub-agents). The always-on Verifier still runs after T3.

---

## Task Breakdown

### T1: `SqliteReader.cover_file` resolution method

**What**: New read-layer method resolving a book's on-disk `cover.jpg` path, keyed on
`books.has_cover` — `None` when the book has no cover, the validated `Path` when it does, raising on
an unknown id or a metadata↔disk inconsistency. Cover-scoped sibling of `format_files`.
**Where**: `src/calibre_mcp/sqlite_reader.py`
**Depends on**: None
**Reuses**: `_connect` read-only pattern; the `books.path` → book-folder resolution + `is_file()`
validation shape from `format_files` (`sqlite_reader.py:302`); scratch-seeding pattern from
`tests/integration/test_sqlite_reader.py`; a stdlib zlib-PNG cover helper (see Library-data note).
**Requirement**: RCOVER-01, RCOVER-02, RCOVER-03, RCOVER-04

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [x] `cover_file(self, book_id: int) -> Path | None`: `SELECT path, has_cover FROM books WHERE id = ?`; no row → `BookNotFoundError`; `has_cover` falsy → `None`; else `{library}/{path}/cover.jpg`, return it if `is_file()` else `InvalidInputError`
- [x] Integration tests over a **seeded scratch library**: covered book → `Path` (`is_file()` true); uncovered book → `None`; unknown id → `BookNotFoundError`; covered book with `cover.jpg` deleted (has_cover still 1) → `InvalidInputError`
- [x] Gate check passes: `uv run pytest -m integration`
- [x] Test count: ~4 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(reader): add cover_file has_cover-keyed resolution (RCOVER-01..04)`

---

### T2: `CalibreLibrary.read_cover` facade method

**What**: MCP-agnostic facade reporting cover presence + resolved path as a plain dict `{book_id,
has_cover, cover_path}`. No backup, no runner, no network.
**Where**: `src/calibre_mcp/library.py`
**Depends on**: T1
**Reuses**: `cover_file` (T1); the facade's existing reader accessor; `BookNotFoundError` /
`InvalidInputError` propagation (no new handling).
**Requirement**: RCOVER-01, RCOVER-02, RCOVER-03, RCOVER-05

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [x] `read_cover(self, book_id: int) -> dict[str, Any]` returning `{"book_id", "has_cover": cover is not None, "cover_path": str(cover) if cover else None}` from `self._reader.cover_file(book_id)`
- [x] No mutation: no `backup_metadata_db`, no `calibredb`, no network in the path (RCOVER-05)
- [x] Integration tests: covered → `{has_cover: True, cover_path: <str>}`; uncovered → `{has_cover: False, cover_path: None}`; unknown id → `BookNotFoundError`; assert **no `metadata.db` backup file** is created by any call
- [x] Gate check passes: `uv run pytest -m integration`
- [x] Test count: ~4 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(cover-read): add CalibreLibrary.read_cover (RCOVER-01/02/03/05)`

---

### T3: `read_cover` MCP tool (image content) + `_map_errors` generic + closeout

**What**: Expose `read_cover` on the FastMCP tool surface returning **image content** on the
has-cover path and a structured dict on the no-cover path; re-type `_map_errors` generically so a
non-`dict` return typechecks; then close traceability + STATE handoff (incl. proposed **AD-024**).
**Where**: `src/calibre_mcp/server.py`, `.specs/features/cover-read/spec.md`, `.specs/STATE.md`
**Depends on**: T2
**Reuses**: the `@mcp.tool() @_map_errors` + `_get_library()` pattern (`server.py`); `FastMCP.Image`;
e2e pattern from `tests/e2e/test_server.py`; existing AD/handoff format in `.specs/STATE.md`.
**Requirement**: RCOVER-01, RCOVER-02, RCOVER-03 (+ traceability closeout for all RCOVER)

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [x] `_map_errors` re-typed generic (PEP 695 `def _map_errors[T](fn: Callable[..., T]) -> Callable[..., T]`, ruff UP047-preferred over `TypeVar`) — pure typing change; behavior identical; existing suite still green
- [x] `@mcp.tool() @_map_errors def read_cover(book_id: int) -> Any:` → `result = _get_library().read_cover(book_id); return Image(path=result["cover_path"]) if result["has_cover"] else result` (imports `Image` from `mcp.server.fastmcp`) — **SPEC_DEVIATION**: annotated `-> Any` instead of `Image | dict` (design's proposed annotation crashes tool registration under the installed mcp SDK 1.28.1; `-> Any` gives identical runtime wire behavior — see AD-024)
- [x] Docstring states: returns viewable `image/jpeg` when present; `{has_cover: false}` when absent; not-found for bad id; invalid-input on metadata↔disk mismatch; pure read (no write/network)
- [x] E2E tests: covered → image content, MIME `image/jpeg`, non-empty data; uncovered → structured `{has_cover: False}`; unknown id → `ToolError`
- [x] Spec Requirement Traceability: RCOVER-01..05 → Status `Implementing` (Verifier flips to `Verified`)
- [x] `.specs/STATE.md`: handoff note that COVER-01 shipped + **AD-024** recorded (tool may return MCP image content; read layer resolves the path, FastMCP reads the bytes; `_map_errors` generic)
- [x] Full build gate passes as regression: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- [x] Test count: ~3 new e2e tests pass; whole suite green; no silent deletions

**Tests**: e2e (+ full build regression) · **Gate**: full

**Commit**: `feat(cover-read): expose read_cover image-content tool + AD-024 (RCOVER-01/02/03)`

---

## Parallel Execution Map

```
Phase 1 (leaf):
    └── T1  (cover_file reader)

Phase 2 (Sequential):
    T1 → T2  (read_cover facade)

Phase 3 (Sequential):
    T2 → T3  (read_cover tool + _map_errors generic + closeout)
```

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `cover_file` | 1 read method | ✅ Granular |
| T2: `read_cover` facade | 1 method | ✅ Granular |
| T3: `read_cover` tool + typing + closeout | 1 tool endpoint + 1 typing change + docs | ✅ Granular (cohesive: the tool, its enabling typing change, and its closeout) |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | None | Phase-1 leaf, no arrows in | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Read layer (`cover_file`) | integration | integration | ✅ OK |
| T2 | Facade (`read_cover`) | integration | integration | ✅ OK |
| T3 | Tool surface (`read_cover`) + `_map_errors` typing | e2e | e2e | ✅ OK |

All ✅ — tests co-located in the task that creates the code; nothing deferred.

---

## MCPs & Skills per task

No project MCPs are needed (all work is local source + pytest). No specialized skills per task beyond the `spec-driven` Execute flow. 3 phases → inline by default; confirm at Execute time if any task should be delegated to a sub-agent.
