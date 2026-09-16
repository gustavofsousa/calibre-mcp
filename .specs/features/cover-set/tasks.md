# Set a Book's Cover From a Local File (COVER-02) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/cover-set/spec.md`
**Design**: `.specs/features/cover-set/design.md`
**Status**: Ready — 2 tasks (T1–T2) planned; not yet executed.
**Precedent**: `CalibreLibrary.update_metadata` (AD-012, Verified) — single-book plan→confirm + one
backup. COVER-02 is the cover-typed twin.

> **PREREQUISITE — COVER-01 first.** COVER-02 reuses `SqliteReader.cover_file` (COVER-01) for the
> plan's `current_has_cover` and the post-apply re-read. Do **not** start COVER-02 Execute until
> COVER-01's `cover_file` is merged. T1 `Depends on` names it explicitly.

> **Library-data note (affects test seeding):** seed a `scratch_library` and generate a valid cover
> image **in-test** with a stdlib **zlib-PNG** helper (Pillow/ImageMagick not guaranteed present).
> Verified 2026-07-31: a hand-built 100×150 PNG becomes a 392-byte `cover.jpg` and flips
> `has_cover` 0→1; a **missing** cover path makes `calibredb` **silently no-op** (no error) — this is
> why the missing-path test asserts `InvalidInputError` **and no backup created**.

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute. Guidelines: `AGENTS.md` (quality/testing), `pyproject.toml` (markers `unit`/`integration`/`e2e`; `ruff`, `mypy --strict`), `.specs/STATE.md` (test-safety rule, AD-011/012). Existing samples reused as patterns: `tests/integration/test_library_update_metadata.py` (or the nearest plan→confirm facade test), `tests/e2e/test_server.py`.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| Facade (`CalibreLibrary.set_cover`) | integration | All branches 1:1 to SCOVER-01..07: plan (no write, `current_has_cover` false→true, `new_cover`, token); apply round-trip (`has_cover` flips, `cover_path` present, one backup); **missing path → `InvalidInputError` + no backup**; non-image extension → `InvalidInputError`; unknown id → `BookNotFoundError`; token mismatch → `ConfirmationError` (no write); **replace** an existing cover; **backup-before-write order** (monkeypatch); **undecodable image → `has_cover: false`** (demonstrated, not asserted) | `tests/integration/test_library_set_cover.py` | `uv run pytest -m integration` |
| Tool surface (`server.set_cover`) | e2e | Plan → apply round trip via FastMCP (book reads back `has_cover: true` with a `cover_path`); missing path → `ToolError` | `tests/e2e/test_server.py` | `uv run pytest -m e2e` |
| Write primitive (`set_metadata` cover) | none | **No change** — scalar `--field cover:<path>`; covered transitively by facade + existing runner tests | — | build gate only |
| Constants (`_OP_SET_COVER`, `_IMAGE_SUFFIXES`) | none | — (covered transitively by facade + build gate) | — | build gate only |

## Parallelism Assessment

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| integration | Yes | Per-test `scratch_library` under `tmp_path`; in-test generated cover image; real library untouched | `tests/conftest.py::scratch_library` |
| e2e | Yes | Per-test env/library under `tmp_path`, own seeded book + image via FastMCP | `tests/e2e/test_server.py` |

> Suite runs sequentially (no `pytest-xdist`). `[P]` = order-free within a phase, not a directive to parallelize execution.

## Gate Check Commands

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Full | After tasks with integration/e2e tests | `uv run pytest -m integration` (and `uv run pytest -m e2e` for the tool layer) |
| Build | After phase completion or docs-only work | `uv run ruff check src tests && uv run mypy src && uv run pytest` |

---

## Execution Plan

### Phase 1: Facade orchestration

```
→ T1 (CalibreLibrary.set_cover)   [reuses cover_file from COVER-01]
```

### Phase 2: Tool surface + closeout (Sequential)

```
T1 ──→ T2 (set_cover tool, e2e + traceability/STATE/AD-025 closeout)
```

> 2 phases → inline execution (no per-phase sub-agents). The always-on Verifier still runs after T2.

---

## Task Breakdown

### T1: `CalibreLibrary.set_cover` facade orchestration

**What**: The single-book cover mutation — validate (before backup) → plan/confirm (one token, real
`book_id`) → one backup → `set_metadata --field cover:<path>` → **re-read `cover_file` to
demonstrate**. Cover-typed twin of `update_metadata`.
**Where**: `src/calibre_mcp/library.py` (new method + `_OP_SET_COVER` constant + `_IMAGE_SUFFIXES`
whitelist)
**Depends on**: **COVER-01 `SqliteReader.cover_file`** (cross-feature prerequisite)
**Reuses**: `update_metadata` plan→confirm shape (`library.py:319`); `plan_token`/`verify`
(`confirmation.py`, `library.py:23`); `backup_metadata_db` (`backup.py`); `set_metadata` (unchanged,
`calibredb_runner.py:96`); `cover_file` + `get_book` (`sqlite_reader.py`);
`InvalidInputError`/`BookNotFoundError`/`ConfirmationError`.
**Requirement**: SCOVER-01, SCOVER-02, SCOVER-03, SCOVER-04, SCOVER-05, SCOVER-06, SCOVER-07

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [x] `set_cover(self, book_id, image_path, token=None) -> dict[str, Any]` with `_OP_SET_COVER = "set_cover"` and `_IMAGE_SUFFIXES = {".jpg",".jpeg",".png",".webp",".gif",".bmp"}`
- [x] Validation **before** any backup/write: `get_book` (SCOVER-04); `Path(image_path).is_file()` else `InvalidInputError` (SCOVER-02); suffix in `_IMAGE_SUFFIXES` else `InvalidInputError` (SCOVER-03)
- [x] Plan branch (no token): `status:"plan"`, `current_has_cover` (= `cover_file(id) is not None`), `new_cover` (resolved path), one `confirmation_token` over `(book_id, {"image_path": resolved})`; writes nothing (SCOVER-01/07)
- [x] Apply branch (token): `verify` → mismatch refuses, writes nothing (SCOVER-06); exactly one `metadata.db` backup **before** `set_metadata` (SCOVER-05); write `{"cover": resolved}`; **re-read `cover_file`** → return `has_cover` + `cover_path` + `backup` (SCOVER-05, demonstrated)
- [x] Integration tests derive from the P1 Independent Test + Edge Cases: plan-then-apply round trip (`has_cover` false→true, `cover.jpg` on disk, one backup); **missing path → `InvalidInputError` AND no backup file created**; non-image extension → `InvalidInputError`; unknown id → `BookNotFoundError`; token mismatch refused; **replace** an existing cover (plan `current_has_cover: true`, apply overwrites); **backup-before-write order** (monkeypatch, L-001); ~~undecodable image → result `has_cover: false`~~ **SPEC_DEVIATION**: empirically verified 2026-07-31 that a decode failure makes `calibredb` exit non-zero (raises `CalibredbError`), not a silent no-op — the design's assumed scenario doesn't occur. Test asserts the real, stronger guarantee: the failure propagates loudly and `has_cover` stays `false` (never a fake success). See module docstring in `tests/integration/test_library_set_cover.py`.
- [x] Gate check passes: `uv run pytest -m integration` (200 passed)
- [x] Test count: 9 new integration tests pass; no silent deletions

**Tests**: integration · **Gate**: full

**Commit**: `feat(cover-set): add CalibreLibrary.set_cover plan→confirm mutation (SCOVER-01..07)`

---

### T2: `set_cover` MCP tool (server) + closeout

**What**: Expose `set_cover` on the FastMCP tool surface (`_map_errors` + `_jsonify` around the
facade); then close traceability + STATE handoff (incl. proposed **AD-025**).
**Where**: `src/calibre_mcp/server.py`, `.specs/features/cover-set/spec.md`, `.specs/STATE.md`
**Depends on**: T1
**Reuses**: the `@mcp.tool() @_map_errors` + `_jsonify` + `_get_library()` pattern from
`update_metadata` (`server.py`); e2e pattern from `tests/e2e/test_server.py`; existing AD/handoff
format in `.specs/STATE.md`.
**Requirement**: SCOVER-01, SCOVER-05, SCOVER-06 (+ traceability closeout for all SCOVER)

**Tools**: MCP: NONE · Skill: NONE

**Done when**:

- [x] `@mcp.tool() @_map_errors def set_cover(book_id: int, image_path: str, confirmation_token: str | None = None) -> dict:` returning `_jsonify(_get_library().set_cover(book_id, image_path, token=confirmation_token))`
- [x] Docstring states: plan→confirm handshake (surface plan, apply after approval); **local** image file path; one backup; replace-vs-add (`current_has_cover`); re-reads to confirm the cover actually changed (never a fake success)
- [x] E2E tests: plan → apply round trip via the tool surface (book reads back `has_cover: true` + `cover_path`); missing path → `ToolError`
- [x] Spec Requirement Traceability: SCOVER-01..07 → Status `Implementing` (Verifier flips to `Verified`)
- [x] `.specs/STATE.md`: handoff note that COVER-02 shipped (closes the Phase-3 covers pair with COVER-01) + **AD-025** recorded (dedicated `set_cover` tool; `calibredb --field cover:` silently no-ops on a bad path → pre-validate + re-read to demonstrate)
- [x] Full build gate passes as regression: `uv run ruff check src tests && uv run mypy src && uv run pytest` (329 passed)
- [x] Test count: 2 new e2e tests pass; whole suite green; no silent deletions

**Tests**: e2e (+ full build regression) · **Gate**: full

**Commit**: `feat(cover-set): expose set_cover MCP tool + AD-025 (SCOVER-01/05/06)`

---

## Parallel Execution Map

```
Phase 1 (facade):
    └── T1  (set_cover facade)   [prereq: COVER-01 cover_file]

Phase 2 (Sequential):
    T1 → T2  (set_cover tool + closeout)
```

---

## Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: `set_cover` facade | 1 method (compound, one cohesive plan→confirm orchestration) | ✅ Granular |
| T2: `set_cover` tool + closeout | 1 tool endpoint + docs closeout | ✅ Granular |

---

## Diagram-Definition Cross-Check

| Task | Depends On (task body) | Diagram Shows | Status |
| ---- | ---------------------- | ------------- | ------ |
| T1 | COVER-01 `cover_file` (cross-feature) | Phase-1 facade, prereq noted | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |

---

## Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | Facade (`set_cover`) | integration | integration | ✅ OK |
| T2 | Tool surface (`server.set_cover`) | e2e | e2e | ✅ OK |

All ✅ — tests co-located in the task that creates the code; nothing deferred.

---

## MCPs & Skills per task

No project MCPs are needed (all work is local source + pytest). No specialized skills per task beyond the `spec-driven` Execute flow. 2 phases → inline by default; confirm at Execute time if any task should be delegated to a sub-agent.
