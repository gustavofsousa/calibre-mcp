# Calibre Management P2 — Tasks (Convert, Organize & Email)

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier, discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Spec**: `.specs/features/calibre-management-p2/spec.md`
**Design**: `.specs/features/calibre-management-p2/design.md`
**Decisions**: AD-013…AD-017 (`.specs/STATE.md`)
**Builds on**: `calibre-management` (P1, shipped) — extends its facade/runners/reader; does not modify P1 behavior.
**Status**: Draft — awaiting approval
**Scope**: 3 tools — `convert_book` (single-step + backup, additive: **keeps old + new format**), `find_duplicates` (read-only advisory), `email_book` (plan→confirm, outward-facing).

---

## Test Coverage Matrix

> Generated from codebase + P1 conventions + design — confirm before Execute.
> Guidelines found: **none** documented; P1 test conventions (`.specs/features/calibre-management/tasks.md`) are the floor.
> New layers follow the same rules: unit for pure/config, integration for reader/runners/facade, e2e for tools.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| `errors.py` additions (5 new exceptions) | none | build gate only (data-only classes) | `src/calibre_mcp/errors.py` | build gate |
| `config.py` — `SmtpConfig` + `load_smtp_config` | unit | All branches; 1:1 to EMAIL-01 AC-4/5/6; every missing-var edge + password-never-in-repr | `tests/unit/test_config.py` (extend) | `uv run pytest -m unit` |
| `sqlite_reader.py` — `format_files` + `find_duplicate_groups` | integration | Key query paths + error paths: format_files happy/missing-file/not-found; dup grouping hit + no-dup | `tests/integration/test_sqlite_reader.py` (extend) | `uv run pytest` |
| `ebook_convert_runner.py` (NEW) | integration | convert happy + non-zero→`EbookConvertError` + missing-binary path | `tests/integration/test_ebook_convert_runner.py` | `uv run pytest` |
| `calibre_smtp_runner.py` (NEW) | integration | send happy (stubbed binary records argv) + non-zero→`CalibreSmtpError` + **password never in output/stderr** | `tests/integration/test_calibre_smtp_runner.py` | `uv run pytest` |
| `calibredb_runner.py` — `add_format` | integration | add_format happy (keeps old + adds new) + `--dont-replace` + failure classification | `tests/integration/test_calibredb_runner.py` (extend) | `uv run pytest` |
| `library.py` facade — `find_duplicates` / `convert_book` / `email_book` | integration | Every AC: dup grouping; convert keeps old + adds new + refuse-if-exists + backup-before-add_format; email plan-no-send + apply-with-token + token-mismatch + no-SMTP + **password never leaks** | `tests/integration/test_library_p2.py` | `uv run pytest` |
| `server.py` — 3 new tools | e2e | Every tool: happy + input-validation + error mapping; email plan→confirm surfaced; **stdout stays clean** | `tests/e2e/test_server.py` (extend) | `uv run pytest` |

## Parallelism Assessment

> Same isolation model as P1 — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit (config) | Yes | `monkeypatch`/env per test; pure dataclass | P1 `test_config` pattern |
| integration (reader) | Yes | Real library read-only + per-test scratch lib for format_files | P1 reader tests (`mode=ro`) |
| integration (ebook-convert) | Yes | Per-test `tmp_path` scratch lib + tmp output dir; real `ebook-convert` on isolated files | P1 scratch-library isolation |
| integration (calibre-smtp) | Yes | **Stubbed binary** (temp script recording argv) — no network, no shared state | new; fully mocked dependency |
| integration (add_format / facade) | Yes | Each test bootstraps its own scratch library in `tmp_path` | P1 §Testing Approach |
| e2e | Yes | Facade wired to per-test scratch lib; stdout captured per test | P1 e2e pattern |

> `[P]` below is ordering info (no inter-task dependency), not a directive to spawn a sub-agent per task.

## Gate Check Commands

> Generated from codebase — confirm before Execute.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest -m unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest` |
| Build | After phase completion or data-only tasks | `uv run ruff check src tests && uv run pytest` |

---

## Execution Plan

### Phase 1: Foundation (Sequential)

```
T1 → T2
```

### Phase 2: Building blocks (Parallel OK — different files, isolated tests)

```
       ┌→ T3 [P] ─┐
T2 ────┼→ T4 [P] ─┤
       ├→ T5 [P] ─┼──→ (Phase 3)
       └→ T6 [P] ─┘
```

### Phase 3: Facade (Sequential — same file `library.py`)

```
T3 ──────→ T7 → T8 → T9
T4,T6 ───────────↑    ↑
T5 ───────────────────┘
```

### Phase 4: Tool surface (Sequential)

```
T7,T8,T9 ──→ T10
```

> **4 phases → the Execute step will offer one sub-agent per phase (offer-then-confirm) before running.**

---

## Task Breakdown

### T1: Extend error taxonomy (P2 failures)

**What**: Add the five P2 exceptions so convert/email failures are explicit and uniform.
**Where**: `src/calibre_mcp/errors.py` (modify)
**Depends on**: None
**Reuses**: `CalibreMcpError` base; `ConfigError` (parent of `SmtpNotConfiguredError`)
**Requirement**: CONV-01, EMAIL-01 (explicit-failure guarantee)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] Defines `EbookConvertError(cmd, exit_code, stderr)`, `EbookConvertNotFoundError`, `CalibreSmtpError(cmd, exit_code, stderr)`, `CalibreSmtpNotFoundError`, `SmtpNotConfiguredError(missing_var)` — all subclass `CalibreMcpError` (`SmtpNotConfiguredError` subclasses `ConfigError`)
- [x] Each carries the fields the design names; messages never include a password
- [x] Build gate passes: `uv run ruff check src tests`

**Tests**: none (data-only classes — build gate)
**Gate**: build
**Commit**: `feat(errors): P2 failure types for convert and email`

---

### T2: SMTP config from env (AD-015)

**What**: `SmtpConfig` dataclass + `load_smtp_config()` reading `CALIBRE_MCP_SMTP_*`, lazy (not at startup).
**Where**: `src/calibre_mcp/config.py` (modify), `tests/unit/test_config.py` (extend)
**Depends on**: T1
**Reuses**: `errors.SmtpNotConfiguredError`; existing `load_config` env pattern
**Requirement**: EMAIL-01 AC-4/5/6 (AD-015)

**Tools**:
- MCP: NONE
- Skill: `security-engineering-suite` (secret handling: password env-only, never logged/repr'd)

**Done when**:
- [x] `SmtpConfig(relay, port, username, password, encryption, sender)` frozen; `encryption` defaults `TLS`, `port` sane default per encryption (465 SSL / 25 else)
- [x] `load_smtp_config()` reads `CALIBRE_MCP_SMTP_RELAY/PORT/USERNAME/PASSWORD/ENCRYPTION/FROM`; raises `SmtpNotConfiguredError` naming the first missing required var
- [x] Password is **never** exposed by `repr`/`str`/log (custom `__repr__` masks it) — asserted by test
- [x] Not called at startup (server boots without SMTP) — verified by test importing config without SMTP env
- [x] Unit tests: full config parses; missing relay/username/password each raise naming the var; masked repr; default encryption/port
- [x] Quick gate passes: `uv run pytest -m unit`; Test count: ≥5 new tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick
**Commit**: `feat(config): SMTP relay config from env with masked password`

---

### T3: SqliteReader — format_files + find_duplicate_groups [P] (ORG-01, AD-017)

**What**: Resolve a book's on-disk format files, and group likely-duplicate books; constructor gains the library root.
**Where**: `src/calibre_mcp/sqlite_reader.py` (modify), `tests/integration/test_sqlite_reader.py` (extend)
**Depends on**: T1
**Reuses**: read-only connection; `Book`; `errors.BookNotFoundError`
**Requirement**: ORG-01, CONV-01/EMAIL-01 (path resolution)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `SqliteReader(db_path, library_path)` — constructor takes the library root (update `CalibreLibrary` construction in the same task to keep the build green)
- [x] `format_files(book_id)` returns `{FORMAT: absolute Path}` from `data.name` + `books.path` + library root; raises `BookNotFoundError` for unknown id; **verifies each file exists**, raising clearly for a missing file (design Risks)
- [x] `find_duplicate_groups()` returns groups (size ≥ 2) keyed by normalized `(casefold+strip title, casefold+strip primary author)`, each hydrated to full `Book`s; no duplicates → empty list
- [x] Reads stay read-only; no `subprocess` (AD-001)
- [x] Integration tests: format_files happy (real lib) + not-found + missing-file; find_duplicate_groups on a scratch lib with two same title+author books → one group of 2; distinct books → no group
- [x] Full gate passes: `uv run pytest`; Test count: ≥5 new tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(reader): format-file resolution and duplicate grouping`

---

### T4: EbookConvertRunner [P] (CONV-01)

**What**: The single `ebook-convert` subprocess call site.
**Where**: `src/calibre_mcp/ebook_convert_runner.py` (NEW), `tests/integration/test_ebook_convert_runner.py` (NEW)
**Depends on**: T1
**Reuses**: `CalibredbRunner._run` discipline (arg-list, `shell=False`, taxonomy mapping); `errors.EbookConvert*`
**Requirement**: CONV-01 (AD-014)

**Tools**:
- MCP: `context7` (ebook-convert CLI flags) if needed
- Skill: `security-engineering-suite` (subprocess injection: arg-list, `shell=False`)

**Done when**:
- [x] `convert(source: Path, target_ext: str, out_dir: Path) -> Path` runs `ebook-convert <source> <out_dir>/<stem>.<target_ext>`; returns the produced path
- [x] Single subprocess call site; arg-list, `shell=False`; a sane subprocess timeout surfaces as `EbookConvertError`
- [x] Missing binary → `EbookConvertNotFoundError`; non-zero → `EbookConvertError(stderr)` — never a false success
- [x] Integration tests (real `ebook-convert`): convert a small epub→pdf produces the file; a bogus/empty source → `EbookConvertError`
- [x] Full gate passes: `uv run pytest`; Test count: ≥2 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(convert): ebook-convert runner for format conversion`

---

### T5: CalibreSmtpRunner [P] (EMAIL-01) — password hygiene

**What**: The single `calibre-smtp` subprocess call site (compose mode) with strict password hygiene.
**Where**: `src/calibre_mcp/calibre_smtp_runner.py` (NEW), `tests/integration/test_calibre_smtp_runner.py` (NEW)
**Depends on**: T1, T2
**Reuses**: `_run` discipline; `config.SmtpConfig`; `errors.CalibreSmtp*`
**Requirement**: EMAIL-01 (AD-014, AD-015)

**Tools**:
- MCP: `context7` (calibre-smtp CLI flags) if needed
- Skill: `security-engineering-suite` (subprocess + secret hygiene)

**Done when**:
- [x] `send(cfg, sender, recipient, subject, body, attachment)` runs `calibre-smtp -a <file> -s <subject> <from> <to> <body>` with `--relay/--port/-u/-p/-e` from `cfg`; arg-list, `shell=False`
- [x] Missing binary → `CalibreSmtpNotFoundError`; non-zero → `CalibreSmtpError` with stderr **scrubbed of the password**
- [x] Password never logged, never in the exception message/output
- [x] Integration tests use a **stubbed `calibre-smtp`** (temp script recording argv to a file): asserts the right relay/attachment/subject args are passed; asserts a forced non-zero maps to `CalibreSmtpError`; asserts the password string appears in **no** returned value/log/exception text
- [x] Full gate passes: `uv run pytest`; Test count: ≥3 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(email): calibre-smtp runner with password hygiene`

---

### T6: CalibredbRunner.add_format [P] (CONV-01)

**What**: Attach a converted file as a new format on an existing book, keeping existing formats.
**Where**: `src/calibre_mcp/calibredb_runner.py` (modify), `tests/integration/test_calibredb_runner.py` (extend)
**Depends on**: T1
**Reuses**: existing `_run` + `_raise_for_error`
**Requirement**: CONV-01

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [x] `add_format(book_id, path)` runs `calibredb add_format <id> <path> --dont-replace` via `_run`
- [x] Failure classified by existing `_raise_for_error` (lock/not-found/non-zero)
- [x] Integration tests on scratch lib: add a second format to an existing book → **both** old and new formats present (via `format_files`/`get_book`); a bad path/id maps to `CalibredbError`
- [x] Full gate passes: `uv run pytest`; Test count: ≥2 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(runner): calibredb add_format (additive, keeps existing formats)`

---

### T7: Facade — find_duplicates (ORG-01)

**What**: `CalibreLibrary.find_duplicates()` shaping duplicate groups for the tool.
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_p2.py` (NEW)
**Depends on**: T3
**Reuses**: `SqliteReader.find_duplicate_groups`
**Requirement**: ORG-01

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] `find_duplicates()` delegates to the reader; returns `{group_count, groups:[{key, books:[{id,title,authors,formats}]}]}`
- [ ] Read-only; never mutates, never auto-merges (AD-016); facade imports no `sqlite3`/`subprocess`
- [ ] Integration tests: scratch lib with a duplicate pair → one group of 2; no duplicates → `group_count: 0`
- [ ] Full gate passes: `uv run pytest`; Test count: ≥2 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(library): find_duplicates advisory report`

---

### T8: Facade — convert_book (CONV-01, additive + backup)

**What**: `CalibreLibrary.convert_book(id, target_format)` — single-step convert that **keeps the old format and adds the new**.
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_p2.py` (extend)
**Depends on**: T3, T4, T6
**Reuses**: `format_files`, `EbookConvertRunner`, `CalibredbRunner.add_format`, `backup_metadata_db`
**Requirement**: CONV-01 (AD-011, AD-016)

**Tools**:
- MCP: NONE
- Skill: NONE

**Done when**:
- [ ] Validates `target_format` against the supported set (`epub, azw3, mobi, pdf`); `get_book` exists-precheck
- [ ] **Refuses** (`InvalidInputError`) when the book already has `target_format` — stays additive, never overwrites (CONV-01 AC-3)
- [ ] Picks a convertible source via `format_files`; refuses clearly if the book has no source file (AC-4)
- [ ] Converts into a `tempfile.TemporaryDirectory` → `backup_metadata_db()` **then** `add_format` (backup-before-write, AD-011) → re-reads and returns the book with **both** old and new formats (AC-2)
- [ ] Temp file cleaned up even on failure; `ebook-convert` failure propagates with stderr (no false success, no `add_format`) (AC-5)
- [ ] Integration tests on scratch lib: convert epub→pdf ⇒ book has EPUB **and** PDF; convert to an existing format refuses; backup exists before add_format; bogus source surfaces `EbookConvertError`
- [ ] Full gate passes: `uv run pytest`; Test count: ≥4 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(library): convert_book keeps old format and adds new`

---

### T9: Facade — email_book (EMAIL-01, plan→confirm, no leak)

**What**: `CalibreLibrary.email_book(id, recipient, format=None, token=None)` — outward-facing send behind plan→confirm.
**Where**: `src/calibre_mcp/library.py` (modify), `tests/integration/test_library_p2.py` (extend)
**Depends on**: T2, T3, T5
**Reuses**: `plan_token`/`verify` (op `email_book`), `format_files`, `load_smtp_config`, `CalibreSmtpRunner`
**Requirement**: EMAIL-01 (AD-012, AD-015, AD-016)

**Tools**:
- MCP: NONE
- Skill: `security-engineering-suite` (outward-facing action + secret hygiene)

**Done when**:
- [ ] Exists-precheck; resolves attachment format (explicit `format` else order `epub→azw3→mobi→pdf`); refuses if no attachable file (AC-7); basic recipient shape validation
- [ ] No token → returns `{status:"plan", recipient, format, subject, file, confirmation_token}` and **sends nothing** (AC-2)
- [ ] Token match → `load_smtp_config()` (raises `SmtpNotConfiguredError` if unset, AC-6) → `CalibreSmtpRunner.send`; token mismatch → `ConfirmationError`
- [ ] No library mutation → no metadata backup; **SMTP password never appears** in the plan or any returned dict (AC-5, asserted)
- [ ] Integration tests (stubbed calibre-smtp): plan step sends nothing + returns token; apply step invokes send with the right args; mismatch refused; missing SMTP env → `SmtpNotConfiguredError`; password-never-leaks assertion
- [ ] Full gate passes: `uv run pytest`; Test count: ≥5 tests pass (no silent deletions)

**Tests**: integration
**Gate**: full
**Commit**: `feat(library): email_book via plan→confirm with SMTP hygiene`

---

### T10: FastMCP tool surface — convert_book / find_duplicates / email_book

**What**: Declare the 3 new `@mcp.tool()` functions, validate inputs, delegate to the facade, map errors, keep stdout clean.
**Where**: `src/calibre_mcp/server.py` (modify), `tests/e2e/test_server.py` (extend)
**Depends on**: T7, T8, T9
**Reuses**: `_map_errors`, `_jsonify`, `_get_library`
**Requirement**: CONV-01, ORG-01, EMAIL-01 (tool surface)

**Tools**:
- MCP: `context7` (FastMCP tool API) if needed
- Skill: `mcp-builder` (tool docstrings), `security-engineering-suite` (boundary input validation)

**Done when**:
- [ ] `convert_book(book_id, target_format)`, `find_duplicates()`, `email_book(book_id, recipient, format=None, confirmation_token=None)` registered as `@mcp.tool()` with `_map_errors`
- [ ] `email_book` docstring instructs the HOST to surface the plan (recipient + file) and only re-call with the token after user approval — outward-facing send
- [ ] `convert_book` docstring states it is additive (keeps existing formats) and refuses if the target already exists
- [ ] Inputs validated at the boundary; exceptions mapped to explicit tool errors; **stdout stays clean** (asserted)
- [ ] e2e tests drive each tool happy + one validation/error case each; email plan→confirm two-step exercised (stubbed smtp); stdout-clean assertion
- [ ] Full gate passes: `uv run pytest`; Test count: ≥6 new tests pass (no silent deletions)

**Tests**: e2e
**Gate**: full
**Commit**: `feat(server): convert_book, find_duplicates, email_book tools`

---

## Parallel Execution Map

```
Phase 1 (Sequential):
  T1 ──→ T2

Phase 2 (Parallel — after T2):
    ├── T3 [P]
    ├── T4 [P]   } different files, isolated tests
    ├── T5 [P]   (needs T2 ✓ from Phase 1)
    └── T6 [P]

Phase 3 (Sequential — same file library.py):
  T3 ──→ T7
  T3,T4,T6 ──→ T8
  T2,T3,T5 ──→ T9
  (order in file: T7 → T8 → T9)

Phase 4 (Sequential):
  T7,T8,T9 ──→ T10
```

---

## Validation Tables (pre-approval gates)

### Task Granularity Check

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: error taxonomy additions | 1 file, 5 exceptions | ✅ Granular |
| T2: SMTP config | 1 file, 1 dataclass + 1 loader | ✅ Granular |
| T3: reader additions | 1 file, 2 read methods (path + dup) | ✅ Granular (cohesive) |
| T4: ebook-convert runner | 1 file, 1 subprocess concern | ✅ Granular |
| T5: calibre-smtp runner | 1 file, 1 subprocess concern | ✅ Granular |
| T6: add_format | 1 method on existing runner | ✅ Granular |
| T7: facade find_duplicates | 1 method | ✅ Granular |
| T8: facade convert_book | 1 method + 1 flow | ✅ Granular |
| T9: facade email_book | 1 method + plan→confirm flow | ✅ Granular |
| T10: server tools | 3 tool declarations, 1 file | ✅ Granular (cohesive) |

### Diagram–Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| ---- | ----------------- | ------------- | ------ |
| T1 | None | (root) | ✅ Match |
| T2 | T1 | T1→T2 | ✅ Match |
| T3 | T1 | T2→T3 (phase edge; T3 needs only T1, ready after Phase 1) | ✅ Match |
| T4 | T1 | T2→T4 (phase edge) | ✅ Match |
| T5 | T1, T2 | T2→T5 | ✅ Match |
| T6 | T1 | T2→T6 (phase edge) | ✅ Match |
| T7 | T3 | T3→T7 | ✅ Match |
| T8 | T3, T4, T6 | T3,T4,T6→T8 | ✅ Match |
| T9 | T2, T3, T5 | T2,T3,T5→T9 | ✅ Match |
| T10 | T7, T8, T9 | T7,T8,T9→T10 | ✅ Match |

> T3–T6 marked `[P]`: T3/T4/T6 depend only on T1, T5 on T1+T2 (both satisfied by end of Phase 1) → no inter-task dependency in Phase 2 → parallel-safe. Phase-entry edges are drawn from T2 for visual clarity. ✅

### Test Co-location Validation

| Task | Code Layer | Matrix Requires | Task Says | Status |
| ---- | ---------- | --------------- | --------- | ------ |
| T1 | errors (data-only) | none | none | ✅ OK |
| T2 | config | unit | unit | ✅ OK |
| T3 | sqlite_reader | integration | integration | ✅ OK |
| T4 | ebook_convert_runner | integration | integration | ✅ OK |
| T5 | calibre_smtp_runner | integration | integration | ✅ OK |
| T6 | calibredb_runner | integration | integration | ✅ OK |
| T7 | facade | integration | integration | ✅ OK |
| T8 | facade | integration | integration | ✅ OK |
| T9 | facade | integration | integration | ✅ OK |
| T10 | server | e2e | e2e | ✅ OK |

All ✅ — no violations.

---

## Requirement Coverage (3/3 mapped)

| Requirement | Task(s) |
| ----------- | ------- |
| CONV-01 | T3 (format_files), T4 (convert), T6 (add_format), T8 (facade), T10 (tool) |
| ORG-01 | T3 (grouping), T7 (facade), T10 (tool) |
| EMAIL-01 | T1 (errors), T2 (SMTP config), T3 (format_files), T5 (smtp runner), T9 (facade), T10 (tool) |
