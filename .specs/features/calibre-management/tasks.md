# Calibre Management MCP — Tasks (P1 / MVP)

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/calibre-management/design.md`
**Status**: Draft (awaiting approval)
**Scope**: P1 only (29 requirements). P2 (CONV-01, ORG-01) not in this breakdown.

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute.
> Guidelines found: **none** (greenfield: only `.git` + `.specs`). Strong defaults applied.
> Stack derived from `design.md` (Tech Decisions + Testing Approach): Python `src/` layout, `uv`, `pytest`, real test library read-only + scratch temp library for writes.
> **Proposed addition (my MICRO call): `ruff` as lint gate** — design fixed no linter; flag if unwanted.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Scaffold / config manifest (`pyproject.toml`, fixtures) | none | build gate only | `pyproject.toml`, `tests/conftest.py` | `uv run ruff check src tests` |
| `errors.py` (exception taxonomy) | none | build gate only (data-only classes) | `src/calibre_mcp/errors.py` | build gate |
| `config.py` (startup validation) | unit | All branches; 1:1 to CFG-01; every edge case (unset / no db) | `tests/unit/test_config.py` | `uv run pytest -m unit` |
| `confirmation.py` (plan→confirm) | unit | All branches; 1:1 to EDIT-01/03, REM-01/05; determinism + mismatch | `tests/unit/test_confirmation.py` | `uv run pytest -m unit` |
| `backup.py` (safety net) | unit | All branches; 1:1 to SAFE-01..05; retention prune + unwritable-dir abort + missing-files trash | `tests/unit/test_backup.py` | `uv run pytest -m unit` |
| `sqlite_reader.py` (read layer) | integration | Key query paths + error paths: get_book happy/not-found/invalid, list_books paging/sort, hydrate | `tests/integration/test_sqlite_reader.py` | `uv run pytest` |
| `calibredb_runner.py` (write + search) | integration | All methods: search, set_metadata, add, remove; happy + failure classification (lock/not-found/non-zero) | `tests/integration/test_calibredb_runner.py` | `uv run pytest` |
| `library.py` facade — reads | integration | search happy + empty (SEARCH-03) + list + get not-found | `tests/integration/test_library_reads.py` | `uv run pytest` |
| `library.py` facade — mutations | integration | Every AC: plan-no-token, apply-with-token, token-mismatch, field-whitelist, backup-before-write ordering, not-found, add dup, remove trash+recycle | `tests/integration/test_library_mutations.py` | `uv run pytest` |
| `server.py` (FastMCP tool surface) | e2e | Every tool: happy + input-validation + error mapping; **stdout stays clean** (MCP framing) | `tests/e2e/test_server.py` | `uv run pytest` |

## Parallelism Assessment

> Generated from codebase — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit | Yes | `tmp_path` per test; pure functions; no shared store | `test_config/confirmation/backup` use only stdlib + tmp dirs |
| integration (reads) | Yes | Real library opened **read-only** (`mode=ro` URI) — no mutation, no lock contention | `sqlite_reader` read-only connection (design §Code Reuse) |
| integration (writes) | Yes | **Each test bootstraps its own scratch library** in a per-test `tmp_path`; `calibredb --with-library` isolates | design §Testing Approach ("scratch library in a temp dir") |
| e2e | Yes | Facade wired to a per-test scratch library; stdout captured per test | server driven in-process against isolated scratch lib |

> Note: `[P]` on tasks below is **ordering** info (no inter-task dependency), not a directive to spawn a sub-agent per task.

## Gate Check Commands

> Generated from codebase — confirm before Execute.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest` |
| Build | After phase completion or config/entity-only tasks | `uv run ruff check src tests && uv run pytest` |

---

## Execution Plan

### Phase 1: Foundation (Sequential)

```
T1 → T2 → T3
```

### Phase 2: Core layers (Parallel OK — different files, no shared state)

```
        ┌→ T4 [P] ─┐
T3 ─────┼→ T5 [P] ─┤
        ├→ T6 [P] ─┼──→ (Phase 3)
        └→ T7 [P] ─┘
```

### Phase 3: Facade (Sequential — same file `library.py`)

```
T4,T7 ──→ T8 ──→ T9   (T9 also consumes T5,T6)
```

### Phase 4: Tool surface (Sequential)

```
T8,T9 ──→ T10
```

> **4 phases → the Execute step will offer one sub-agent per phase (offer-then-confirm) before running.**

---

## Task Breakdown

### T1: Project scaffold + test harness  — **Status: ✅ Complete**

**What**: `src/` layout Python package with `pyproject.toml` (uv, pytest, ruff), pytest markers (`unit`/`integration`/`e2e`), and shared fixtures: a read-only handle to the real library and a `scratch_library` fixture that bootstraps an empty Calibre library in `tmp_path`.
**Where**: `pyproject.toml`, `src/calibre_mcp/__init__.py`, `tests/conftest.py`
**Depends on**: None
**Reuses**: nothing (greenfield)
**Requirement**: infra for all (test-safety rule: writes never touch the real library)

**Tools**:
- MCP: `context7` (FastMCP/pytest packaging), else NONE
- Skill: `python-delivery-stack` (project layout)

**Done when**:
- [ ] `uv run python -c "import calibre_mcp"` succeeds
- [ ] `pytest.ini`/`[tool.pytest]` registers markers `unit`, `integration`, `e2e`
- [ ] `scratch_library` fixture creates an empty library via `calibredb` in a temp dir and yields its path; teardown removes it
- [ ] `real_library` fixture points at `CALIBRE_LIBRARY_PATH` (or the known test path) opened read-only, skips cleanly if absent
- [ ] Build gate passes: `uv run ruff check src tests`

**Tests**: none (build gate only)
**Gate**: build
**Commit**: `chore(scaffold): src layout, uv/pytest/ruff, scratch-library fixtures`

---

### T2: Error taxonomy  — **Status: ✅ Complete**

**What**: The exception hierarchy every layer maps failures to.
**Where**: `src/calibre_mcp/errors.py`
**Depends on**: T1
**Reuses**: nothing
**Requirement**: cross-cutting (explicit-failure guarantee, spec §Error Handling)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Defines `ConfigError`, `BookNotFoundError(book_id)`, `InvalidInputError(msg)`, `LibraryLockedError(stderr)`, `CalibredbError(cmd, exit_code, stderr)`, `CalibredbNotFoundError`, `ConfirmationError`
- [ ] Each carries the fields named in design §Components (e.g. `BookNotFoundError.book_id`)
- [ ] Build gate passes: `uv run ruff check src tests`

**Tests**: none (data-only classes — build gate)
**Gate**: build
**Commit**: `feat(errors): failure taxonomy for explicit tool errors`

---

### T3: Startup config & validation (CFG-01)  — **Status: ✅ Complete**

**What**: `load_config()` resolving/validating `CALIBRE_LIBRARY_PATH` and the backup root.
**Where**: `src/calibre_mcp/config.py`, `tests/unit/test_config.py`
**Depends on**: T2
**Reuses**: `errors.ConfigError`
**Requirement**: CFG-01, SAFE-05 (backup root default + `CALIBRE_MCP_BACKUP_DIR`)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `load_config() -> Config` with `library_path`, `db_path`, `backup_root`
- [ ] Raises `ConfigError` naming the path when env unset **or** dir has no `metadata.db` (CFG-01)
- [ ] `backup_root` = `CALIBRE_MCP_BACKUP_DIR` else `<library>/.calibre-mcp-backups/` (SAFE-05)
- [ ] Unit tests cover: valid path, unset env, dir-without-db, custom backup dir
- [ ] Quick gate passes: `uv run pytest -m unit`; Test count: ≥4 tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick
**Commit**: `feat(config): validate CALIBRE_LIBRARY_PATH and resolve backup root`

---

### T4: SQLite read layer [P] (VIEW-01/02/03, SEARCH-02, SEARCH-01 hydrate)  — **Status: ✅ Complete**

**What**: Read-only `metadata.db` access: `get_book`, `hydrate`, `list_books`, returning `Book` dataclasses.
**Where**: `src/calibre_mcp/sqlite_reader.py`, `tests/integration/test_sqlite_reader.py`
**Depends on**: T3
**Reuses**: `errors.BookNotFoundError`, `InvalidInputError`; `Config.db_path`
**Requirement**: VIEW-01, VIEW-02, VIEW-03, SEARCH-02, SEARCH-01 (hydrate half)

**Tools**:
- MCP: `context7` (sqlite3 URI mode) if needed
- Skill: NONE

**Done when**:
- [ ] Opens `file:{db_path}?mode=ro` (uri=True) — read-only, never writes
- [ ] `get_book(id)` returns full `Book` (all fields in design §Data Models); raises `BookNotFoundError` on missing id (VIEW-01/02); raises `InvalidInputError` on non-int before DB access (VIEW-03)
- [ ] `hydrate(ids)` batch-fetches full metadata preserving order (SEARCH-01)
- [ ] `list_books(limit, offset, sort)` paginates + sorts by requested field (SEARCH-02)
- [ ] JOIN queries verified against the real library (authors/tags/series/ratings/comments/data links)
- [ ] Integration tests: get_book happy vs id 999999 vs non-int; list_books paging + sort; hydrate multi-id order
- [ ] Full gate passes: `uv run pytest`; Test count: ≥6 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(reader): read-only SQLite layer for get/list/hydrate`

---

### T5: Backup & trash safety net [P] (SAFE-01..05, supports REM)

**What**: `backup_metadata_db()` (copy + rolling retention + abort-if-unwritable) and `trash_book_files()`.
**Where**: `src/calibre_mcp/backup.py`, `tests/unit/test_backup.py`
**Depends on**: T3
**Reuses**: `Config.backup_root`, `errors`
**Requirement**: SAFE-01, SAFE-02, SAFE-03, SAFE-04, SAFE-05

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `backup_metadata_db()` copies `metadata.db → backups/metadata-<ts>.db` (SAFE-01)
- [ ] Retention prunes **only** oldest surplus beyond cap (default 20) (SAFE-02)
- [ ] Raises before returning if backup dir can't be created/written (SAFE-04)
- [ ] `trash_book_files(book)` copies book files → `backups/trash/<id>-<ts>/`; if files missing, returns a "no files copied" outcome without raising (design Risks) (SAFE-03)
- [ ] Unit tests (tmp_path): backup created; 25 backups → 20 kept, oldest pruned; unwritable dir aborts; trash copies files; trash with missing files reports no-copy
- [ ] Quick gate passes: `uv run pytest -m unit`; Test count: ≥5 tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick
**Commit**: `feat(backup): metadata backup with retention + recoverable trash`

---

### T6: Plan→confirm intent gate [P] (EDIT-01/03, REM-01/05)

**What**: Deterministic `plan_token` + `verify` handshake.
**Where**: `src/calibre_mcp/confirmation.py`, `tests/unit/test_confirmation.py`
**Depends on**: T3
**Reuses**: `errors.ConfirmationError`
**Requirement**: EDIT-01, EDIT-03, REM-01, REM-05 (token half)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `plan_token(op, book_id, payload)` = truncated `sha256` of normalized `op|book_id|payload` (json sorted keys) — deterministic
- [ ] `verify(op, book_id, payload, token)` raises `ConfirmationError` when recomputed ≠ supplied
- [ ] Unit tests: same input → same token; payload change → different token; matching token verifies; mismatch raises; key-order-independent normalization
- [ ] Quick gate passes: `uv run pytest -m unit`; Test count: ≥5 tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick
**Commit**: `feat(confirm): deterministic plan→confirm token gate`

---

### T7: calibredb runner (write + search) [P] (SEARCH-01, EDIT-02/05, ADD, REM-02)

**What**: The single subprocess call site: `search`, `set_metadata`, `add`, `remove`, plus `_run` failure classification.
**Where**: `src/calibre_mcp/calibredb_runner.py`, `tests/integration/test_calibredb_runner.py`
**Depends on**: T3
**Reuses**: `errors` (Locked/NotFound/CalibredbError); `Config.library_path`
**Requirement**: SEARCH-01 (id resolution), EDIT-02, EDIT-05, ADD-01, ADD-03, ADD-04, REM-02, REM-04

**Tools**:
- MCP: `context7` (calibredb CLI flags) if needed
- Skill: `security-engineering-suite` (subprocess injection: arg-list, `shell=False`)

**Done when**:
- [ ] `_run(args)` is the ONLY `subprocess` call; arg-list, `shell=False`; classifies lock → `LibraryLockedError`, missing binary → `CalibredbNotFoundError`, other non-zero → `CalibredbError(stderr)`
- [ ] `search(query)` returns ids via `calibredb search` (SEARCH-01)
- [ ] `set_metadata(id, fields)` emits one `--field` per pair; comma-joins list fields (EDIT-02)
- [ ] `add(path)` parses new id from stdout; if unparseable, re-resolves or raises (never guesses) (ADD-01); surfaces duplicate outcome (ADD-03)
- [ ] `remove(id)` runs **without** `--permanent` (recycle bin) (REM-02, AD-009)
- [ ] Integration tests on scratch library: search finds/empty; set_metadata applies; add returns id + duplicate note; remove uses recycle bin; a forced non-zero maps to `CalibredbError`
- [ ] Full gate passes: `uv run pytest`; Test count: ≥6 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(runner): calibredb subprocess for search/set/add/remove with error mapping`

---

### T8: Facade — reads (SEARCH-01/03, SEARCH-02, VIEW-01/02)

**What**: `CalibreLibrary` read methods: `search_books` (runner.search → reader.hydrate), `list_books`, `get_book`.
**Where**: `src/calibre_mcp/library.py`, `tests/integration/test_library_reads.py`
**Depends on**: T4, T7
**Reuses**: `SqliteReader`, `CalibredbRunner`
**Requirement**: SEARCH-01, SEARCH-02, SEARCH-03, VIEW-01, VIEW-02

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `search_books(query)` resolves ids via runner then hydrates via reader; **empty query → empty list, not error** (SEARCH-03)
- [ ] `list_books(limit, offset, sort)` delegates to reader with a sane default cap (SEARCH-02, edge case default 50)
- [ ] `get_book(id)` delegates; propagates `BookNotFoundError` (VIEW-01/02)
- [ ] Facade never imports `sqlite3`/`subprocess` directly (invariant)
- [ ] Integration tests: search hit + nonsense→empty; list paging; get_book valid + not-found
- [ ] Full gate passes: `uv run pytest`; Test count: ≥5 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(library): facade read methods (search/list/get)`

---

### T9: Facade — mutations (EDIT-01..07, ADD-01..04, REM-01..06, SAFE ordering)

**What**: `CalibreLibrary` mutation methods with the plan→confirm + backup-before-write flow: `update_metadata`, `add_book`, `remove_book`.
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_mutations.py`
**Depends on**: T5, T6, T8
**Reuses**: `backup`, `confirmation`, `SqliteReader`, `CalibredbRunner`
**Requirement**: EDIT-01..07, ADD-01..04, REM-01..06, SAFE-01/03/04 (ordering enforcement)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `update_metadata(id, fields, token=None)`: book-exists precheck (EDIT-06); field whitelist reject listing allowed (EDIT-04); `series_index` w/o `series` and rating∉0–10 rejected at plan (EDIT-07); no token → diff + `plan_token`, no write (EDIT-01); token match → `backup_metadata_db()` **then** `set_metadata` then re-read (EDIT-02); token mismatch → `ConfirmationError` (EDIT-03); calibredb non-zero → failure w/ stderr, no false success (EDIT-05)
- [ ] `add_book(path)`: validate path is existing file before subprocess (ADD-02); `backup_metadata_db()` then `add` then return new id + metadata (ADD-01); surface duplicate (ADD-03); calibredb failure w/ stderr (ADD-04)
- [ ] `remove_book(id, token=None)`: not-found no-op review (REM-03); no token → review + `plan_token` (REM-01); token match → `trash_book_files` → `backup_metadata_db` → `remove` (recycle bin) → confirm + trash location (REM-02); mismatch → refuse (REM-05); calibredb failure → no false "removed", trash leftovers safe (REM-04)
- [ ] **Backup failure aborts before any calibredb write** for all three (SAFE-04) — asserted by test
- [ ] Integration tests on scratch library covering every AC above + backup-before-write ordering + unwritable-backup abort
- [ ] Full gate passes: `uv run pytest`; Test count: ≥12 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(library): facade mutations with plan→confirm and backup-before-write`

---

### T10: FastMCP tool surface (all P1 tools, input validation, stdout hygiene)

**What**: `server.py` declaring the 6 `@mcp.tool()` functions, validating inputs, delegating to `CalibreLibrary`, mapping exceptions to explicit tool errors, logging to stderr only.
**Where**: `src/calibre_mcp/server.py`, `tests/e2e/test_server.py`
**Depends on**: T8, T9
**Reuses**: `CalibreLibrary`, `config`, `errors`
**Requirement**: all tool-surface ACs; VIEW-03/EDIT-05 input validation at boundary; REM-06 (docstring: recoverable + two-step); CFG-01 startup

**Tools**:
- MCP: `context7` (FastMCP stdio/tool API)
- Skill: `mcp-builder` (tool design + docstrings), `security-engineering-suite` (input validation at boundary)

**Done when**:
- [ ] `search_books`, `list_books`, `get_book`, `update_metadata`, `add_book`, `remove_book` registered as `@mcp.tool()`
- [ ] Inputs validated/narrowed at the boundary; exceptions mapped to explicit tool errors (never silent wrong result)
- [ ] `remove_book` docstring states removal is **recoverable** (recycle bin + trash) and requires review→confirm (REM-06)
- [ ] `update_metadata`/`remove_book` docstrings instruct the host to surface the plan before applying
- [ ] **stdout stays clean** — logging configured to stderr only; e2e test asserts no stray stdout writes (design Risks)
- [ ] e2e tests drive every tool happy + one validation-failure each + stdout-clean assertion
- [ ] Full gate passes: `uv run pytest`; Test count: ≥8 tests pass (no silent deletions)

**Tests**: e2e
**Gate**: full
**Commit**: `feat(server): FastMCP tool surface for the 6 P1 tools`

---

## Parallel Execution Map

```
Phase 1 (Sequential):
  T1 ──→ T2 ──→ T3

Phase 2 (Parallel — after T3):
    ├── T4 [P]
    ├── T5 [P]   } different files, no shared state, isolated tests
    ├── T6 [P]
    └── T7 [P]

Phase 3 (Sequential — same file library.py):
  T4,T7 ──→ T8 ──→ T9   (T9 also needs T5,T6)

Phase 4 (Sequential):
  T8,T9 ──→ T10
```

---

## Validation Tables (pre-approval gates)

### Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: scaffold + fixtures | 1 cohesive infra unit | ✅ Granular |
| T2: errors | 1 file, exception set | ✅ Granular |
| T3: config | 1 file, 1 function | ✅ Granular |
| T4: sqlite_reader | 1 file, 1 read concern | ✅ Granular |
| T5: backup | 1 file, 1 safety concern | ✅ Granular |
| T6: confirmation | 1 file, 2 pure functions | ✅ Granular |
| T7: calibredb_runner | 1 file, 1 subprocess concern | ✅ Granular |
| T8: facade reads | 3 read methods, 1 file | ✅ Granular (cohesive) |
| T9: facade mutations | 3 mutation methods, 1 flow | ✅ Granular (cohesive; split from T8 to isolate the safety-critical flow) |
| T10: server | tool declarations, 1 file | ✅ Granular |

### Diagram–Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| ---- | ----------------- | ------------- | ------ |
| T1 | None | (root) | ✅ Match |
| T2 | T1 | T1→T2 | ✅ Match |
| T3 | T2 | T2→T3 | ✅ Match |
| T4 | T3 | T3→T4 | ✅ Match |
| T5 | T3 | T3→T5 | ✅ Match |
| T6 | T3 | T3→T6 | ✅ Match |
| T7 | T3 | T3→T7 | ✅ Match |
| T8 | T4, T7 | T4,T7→T8 | ✅ Match |
| T9 | T5, T6, T8 | T8→T9 (+T5,T6) | ✅ Match |
| T10 | T8, T9 | T8,T9→T10 | ✅ Match |

> T4–T7 marked `[P]`: none depend on each other (all depend only on T3) → parallel-safe. ✅

### Test Co-location Validation

| Task | Code Layer | Matrix Requires | Task Says | Status |
| ---- | ---------- | --------------- | --------- | ------ |
| T1 | scaffold | none | none | ✅ OK |
| T2 | errors (data-only) | none | none | ✅ OK |
| T3 | config | unit | unit | ✅ OK |
| T4 | sqlite_reader | integration | integration | ✅ OK |
| T5 | backup | unit | unit | ✅ OK |
| T6 | confirmation | unit | unit | ✅ OK |
| T7 | calibredb_runner | integration | integration | ✅ OK |
| T8 | facade reads | integration | integration | ✅ OK |
| T9 | facade mutations | integration | integration | ✅ OK |
| T10 | server | e2e | e2e | ✅ OK |

All ✅ — no violations.

---

## Requirement Coverage (P1 — 29/29 mapped)

| Requirement | Task(s) |
| ----------- | ------- |
| CFG-01 | T3 |
| SEARCH-01 | T4 (hydrate), T7 (ids), T8 |
| SEARCH-02 | T4, T8 |
| SEARCH-03 | T8 |
| VIEW-01/02/03 | T4, T8, T10 |
| EDIT-01..07 | T6, T7, T9, T10 |
| ADD-01..04 | T7, T9, T10 |
| REM-01..06 | T5, T6, T7, T9, T10 |
| SAFE-01..05 | T3 (SAFE-05), T5, T9 |
