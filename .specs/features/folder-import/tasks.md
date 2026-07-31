# Folder Import (BULK-03) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute
flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source
of truth for the full flow (per-task cycle, gate, atomic commit, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/folder-import/design.md`
**Spec**: `.specs/features/folder-import/spec.md`
**Status**: Done — Verifier PASS (`validation.md`)

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines found:
> `CONTRIBUTING.md` (test commands + scratch-library rule), `pyproject.toml` (pytest markers
> unit/integration/e2e, ruff, strict mypy), `ARCHITECTURE.md#testing-strategy`. Existing samples:
> `tests/unit/test_bulk_edit.py` (pure module), `tests/integration/test_library_bulk_convert.py`
> (facade batch), `tests/e2e/test_server.py` (tool surface).

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| Pure module (`folder_scan.py`) | unit | All branches; 1:1 to BIMPORT-01 discovery rules; every listed edge case (recursion, whitelist case-insensitivity, non-ebook ignore, hidden/dotfile exclusion, no symlink follow, empty tree, sorted order) | `tests/unit/test_folder_scan.py` | `uv run pytest -m unit` |
| Facade (`CalibreLibrary.import_folder`, `_import_one`) | integration | All branches; 1:1 to BIMPORT-02..07; all listed edge cases (non-dir, over-cap boundary 500/501, unreadable dir, per-file failure, duplicate on re-run, added real id, bucket-sum invariant, zero-candidate no-op, one backup before loop) | `tests/integration/test_library_folder_import.py` | `uv run pytest -m integration` |
| `add_book` refactor (regression) | integration | Existing ADD-01..04 behavior unchanged (backup→add order, duplicate surfaced, non-file rejected, stderr surfaced) — the current suite stays green | `tests/integration/test_library_mutations.py` | `uv run pytest -m integration` |
| Tool surface (`import_folder` in `server.py`) | e2e | Tool registered; happy path returns three buckets + backup; non-dir surfaces `ToolError` | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |

**Coverage Expectation** set from `CONTRIBUTING.md`/`ARCHITECTURE.md` (cover the write path via
integration/e2e; pure logic via unit) — strong default applied where a layer had no explicit rule.

## Parallelism Assessment

> Generated from codebase — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --- | --- | --- | --- |
| unit (`folder_scan`) | Yes | Per-test `tmp_path` dirs/files, no shared store, no `calibredb` | `tests/unit/test_bulk_edit.py` (pure, tmp-only) |
| integration (facade) | No | Each test bootstraps its own `scratch_library` via `calibredb` subprocess; runner + backup dir are per-test but the suite is run serially by convention and shells out | `tests/conftest.py::scratch_library`; existing integration suites not marked parallel |
| e2e (server) | No | Drives FastMCP tool surface against a bootstrapped library; subprocess-backed | `tests/e2e/test_server.py` |

Default to sequential for anything subprocess/`calibredb`-backed. Only the pure `folder_scan` unit
task is `[P]`-eligible.

## Gate Check Commands

> Generated from codebase — confirm before Execute.

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | After a unit-only task (T1) | `uv run pytest -m unit` |
| Full | After an integration/e2e task (T2, T3, T4) | `uv run pytest` |
| Build | After the last task / before Verifier | `uv run ruff check src tests && uv run mypy && uv run pytest` |

---

## Execution Plan

### Phase 1: Discovery primitive (Sequential)

```
T1
```

### Phase 2: Facade (Sequential — shared library.py, calibredb-backed tests)

```
T1 → T2 → T3
```

### Phase 3: Tool surface (Sequential)

```
T3 → T4
```

Three phases → executed inline (no sub-agent offer; the >3-phase trigger is not met).

---

## Task Breakdown

### T1: Create `folder_scan` pure discovery module [P]

**What**: New pure module that returns the sorted list of ebook-candidate files under a directory,
recursively, applying the whitelist + hidden/symlink exclusions. No `calibredb`/`sqlite3`.
**Where**: `src/calibre_mcp/folder_scan.py` (new)
**Depends on**: None
**Reuses**: `pathlib`/`os` only; mirrors the "pure module" role of `src/calibre_mcp/bulk_edit.py`
**Requirement**: BIMPORT-01 (and the discovery half of BIMPORT-07's determinism)

**Tools**:

- MCP: NONE
- Skill: NONE

**Interface**:

- `EBOOK_EXTENSIONS: frozenset[str]` — `{.epub, .mobi, .azw, .azw3, .azw4, .kfx, .fb2, .fbz, .pdf,
  .djvu, .cbz, .cbr, .cbc, .lit, .lrf, .pdb, .prc, .snb, .tcr}`
- `scan_ebook_files(root: Path) -> list[Path]` — `os.walk(root, followlinks=False)`; prune hidden
  dirs in-place; keep regular files where `name` is not hidden and `suffix.lower() ∈ EBOOK_EXTENSIONS`;
  return sorted by path string.

**Done when**:

- [x] `scan_ebook_files` returns only whitelist matches, recursively (nested subfolder file found)
- [x] Extension match is case-insensitive (`Book.EPUB` found); non-ebook (`readme.txt`) excluded
- [x] Dotfiles/hidden dirs excluded; symlinks not followed (`followlinks=False`)
- [x] Empty tree / tree with no candidates → `[]` (no error); result is sorted by path
- [x] Unit tests written covering every bullet above (1:1 to BIMPORT-01 + edge cases)
- [x] Gate check passes: `uv run pytest -m unit`
- [x] Test count: ≥7 unit tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(folder-import): add folder_scan ebook discovery module (BIMPORT-01)`

---

### T2: Extract `_import_one`; refactor `add_book` to reuse it (regression-safe)

**What**: Extract the post-`calibredb add` classification (add vs duplicate vs unreachable-None
guard, re-read on success) into `CalibreLibrary._import_one`, and rewrite `add_book` to call it —
identical observable behavior. Backup stays in `add_book` **before** `_import_one` (no new
side-effect order; lesson L-006).
**Where**: `src/calibre_mcp/library.py` (modify)
**Depends on**: T1 (not code-coupled, but keeps the module landing first for a clean history)
**Reuses**: `CalibredbRunner.add`, `SqliteReader.get_book`, existing `add_book` body
**Requirement**: BIMPORT-05, BIMPORT-06 (shared classification) + ADD-01..04 regression

**Tools**:

- MCP: NONE
- Skill: NONE

**Interface**:

- `_import_one(self, file_path: Path) -> dict[str, Any]` — `runner.add` → `{duplicate: True,
  book_id: None}` | `InvalidInputError` (None id, non-duplicate) | `{duplicate: False, book_id,
  book: get_book(id)}`. **No backup inside.**

**Done when**:

- [x] `_import_one` created with the three branches above; `add_book` delegates to it, still doing
      `is_file` precheck (ADD-02) → backup → `_import_one` → wrap with `status`/`duplicate`/`backup`
- [x] The existing `test_library_mutations.py` ADD-01..04 tests pass unchanged (regression gate —
      no test edited to accommodate the refactor)
- [x] Add/extend integration tests directly on `_import_one`'s duplicate + added branches
- [x] Gate check passes: `uv run pytest`
- [x] Test count: existing mutation suite count preserved + new `_import_one` cases (no deletions)

**Tests**: integration
**Gate**: full

**Commit**: `refactor(add): extract shared _import_one add-classification core (BIMPORT-05/06)`

---

### T3: Implement `CalibreLibrary.import_folder` facade method

**What**: The orchestration — validate (non-dir/over-cap/unreadable before backup), one backup,
best-effort sorted loop over candidates via `_import_one`, honest three-bucket result.
**Where**: `src/calibre_mcp/library.py` (modify); add `FOLDER_IMPORT_MAX = 500` constant
**Depends on**: T1 (`scan_ebook_files`), T2 (`_import_one`)
**Reuses**: `folder_scan.scan_ebook_files`, `backup_metadata_db`, `_import_one`, AD-020 skeleton
from `convert_book_bulk`
**Requirement**: BIMPORT-02, BIMPORT-03, BIMPORT-04, BIMPORT-07 (+ BIMPORT-05/06 via `_import_one`)

**Tools**:

- MCP: NONE
- Skill: NONE

**Interface**:

- `import_folder(self, path: str | Path) -> dict[str, Any]` → `{status, added[], duplicate[],
  failed[], backup}`
- private `_safe_scan(folder)` converting `OSError` → `InvalidInputError` (AD-021)

**Done when**:

- [x] Non-directory / missing path → `InvalidInputError` before scan/backup (BIMPORT-02)
- [x] `> 500` ebook candidates → `InvalidInputError` before backup; exactly 500 accepted, 501
      rejected (BIMPORT-02 boundary)
- [x] Unreadable dir (`OSError`) surfaces as `InvalidInputError`, not a raw error (AD-021)
- [x] Exactly one backup taken before the loop, even with zero candidates (BIMPORT-03)
- [x] Per-file `calibredb` failure → `failed[{path, error}]`, batch continues (BIMPORT-04)
- [x] Duplicate file → `duplicate[{path}]` (no fake id); success → `added[{path, book_id, book}]`
      with a real id (BIMPORT-05/06); re-running the same import moves entries to `duplicate`
- [x] `len(added)+len(duplicate)+len(failed) == len(candidates)`; order is sorted (BIMPORT-07)
- [x] Integration tests written covering every bullet + zero-candidate no-op + recursion (build a
      temp source tree with real `.epub`s in a subfolder plus a `readme.txt` and a dotfile, using
      the `_sample_epub` pattern from `test_library_mutations.py`) — writes use `scratch_library`
- [x] Gate check passes: `uv run pytest`
- [x] Test count: ≥9 new integration tests pass (no silent deletions)

**Tests**: integration
**Gate**: full

**Commit**: `feat(folder-import): add import_folder facade with three-bucket best-effort (BIMPORT-02..07)`

---

### T4: Expose `import_folder` MCP tool

**What**: New `@mcp.tool() @_map_errors def import_folder(path)` returning `_jsonify(...)`, with a
docstring stating recursive scan, additive/no-token, one backup, honest three buckets, non-ebook
silently ignored.
**Where**: `src/calibre_mcp/server.py` (modify)
**Depends on**: T3
**Reuses**: `_get_library`, `_map_errors`, `_jsonify` (mirror `add_book` tool)
**Requirement**: BIMPORT-03 (surface), full-feature integration on the tool surface

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [x] Tool registered and callable; returns `{status, added, duplicate, failed, backup}` (jsonified)
- [x] Non-directory path surfaces a `ToolError` (via `_map_errors`)
- [x] E2E tests added in `tests/e2e/test_server.py`: happy path (three buckets + backup present) and
      a non-dir error path
- [x] Gate check passes (Build): `uv run ruff check src tests && uv run mypy && uv run pytest`
- [x] Test count: full suite green (previous total + all new BULK-03 tests), mypy + ruff clean

**Tests**: e2e
**Gate**: build

**Commit**: `feat(folder-import): expose import_folder MCP tool (BIMPORT-03)`

---

## Parallel Execution Map

```
Phase 1:
  T1 [P]        (pure module; parallel-safe unit tests — but nothing to parallelize against)

Phase 2 (Sequential — shared library.py, calibredb-backed):
  T1 ──→ T2 ──→ T3

Phase 3 (Sequential):
  T3 ──→ T4
```

`[P]` on T1 marks its unit tests as parallel-safe; it has no sibling to run beside it, so execution
is effectively sequential T1 → T2 → T3 → T4.

---

## Task Granularity Check

| Task | Scope | Status |
| --- | --- | --- |
| T1: `folder_scan` module (1 pure module, 1 function + 1 constant) | 1 module | ✅ Granular |
| T2: extract `_import_one` + refactor `add_book` (1 cohesive change, same file) | 1 function extract | ✅ Granular |
| T3: `import_folder` facade method (1 method + 1 helper + 1 constant, same file) | 1 method | ✅ Granular |
| T4: `import_folder` tool (1 tool function) | 1 endpoint | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | (root) | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T1, T2 | T1 → T2 → T3 (T1 reused via scan, T2 via `_import_one`) | ✅ Match |
| T4 | T3 | T3 → T4 | ✅ Match |

No task marked `[P]` depends on another `[P]` task (T1 is the only `[P]`, standalone). ✅

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | Pure module `folder_scan.py` | unit | unit | ✅ OK |
| T2 | Facade `_import_one` + `add_book` refactor | integration | integration | ✅ OK |
| T3 | Facade `import_folder` | integration | integration | ✅ OK |
| T4 | Tool surface `server.py` | e2e | e2e | ✅ OK |

No `Tests: none` used; no test deferral across tasks. ✅

---

## Requirement Traceability (task → requirement)

| Requirement ID | Tasks | Status |
| --- | --- | --- |
| BIMPORT-01 | T1 | Verified |
| BIMPORT-02 | T3 | Verified |
| BIMPORT-03 | T3, T4 | Verified |
| BIMPORT-04 | T3 | Verified |
| BIMPORT-05 | T2, T3 | Verified |
| BIMPORT-06 | T2, T3 | Verified |
| BIMPORT-07 | T3 (+ T1 ordering) | Verified |

**Coverage:** 7 requirements, all mapped to tasks. 0 unmapped.
