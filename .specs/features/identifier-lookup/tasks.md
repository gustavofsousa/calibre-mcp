# Identifier-Based Metadata Lookup (ENRICH-01) Tasks

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: **activate it by name and follow its Execute
flow and Critical Rules.** Do not search for skill files by filesystem path. The skill is the source
of truth for the full flow (per-task cycle, sub-agent delegation, adequacy review, Verifier,
discrimination sensor).

**If the skill cannot be activated, STOP and tell the user — do not proceed without it.**

---

**Design**: `.specs/features/identifier-lookup/design.md`
**Spec**: `.specs/features/identifier-lookup/spec.md`
**Status**: Draft
**Prerequisite (already shipped):** `SqliteReader.cover_file` (COVER-01) at `sqlite_reader.py:343`,
`get_book`/`_require_int` at `sqlite_reader.py:77/198`, placeholder-pubdate rule at
`sqlite_reader.py:531`.

---

## Test Coverage Matrix

> Generated from codebase, project guidelines, and spec — confirm before Execute.
> Guidelines found: `CONTRIBUTING.md` (gate commands: `uv run pytest` / `ruff check src tests` /
> `mypy`), `pyproject.toml` (`[tool.pytest.ini_options]` markers `unit`/`integration`/`e2e`;
> `ruff` E,F,I,UP,B; `mypy --strict` on `src`), plus `~/.claude/CLAUDE.md` (tests derive from ACs,
> never mirror implementation). Test-safety rule from spec: **network tests never hit the real Open
> Library** — feed canned bytes through the injectable `http_get` seam.

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| ---------- | ------------------ | -------------------- | ---------------- | ----------- |
| `openlibrary_client.py` — new pure I/O module (parse, retry, cover download) | unit | All branches; 1:1 to LOOKUP-04/07/08/09/10 ACs + every listed edge case (`{value}` shape, 404 not-found, retry-once, timeout passthrough, User-Agent) | `tests/unit/test_openlibrary_client.py` | `uv run pytest tests/unit` |
| `library.py` — `enrich_from_identifier` facade + gap-proposal helpers | integration | 1:1 to LOOKUP-01/02/03/04/05/06/07/09 ACs + ISBN-normalization & "all present" edge cases, via scratch library + injected fake enricher | `tests/integration/test_library_enrich.py` | `uv run pytest tests/integration` |
| `server.py` — `enrich_from_identifier` tool wrapper | e2e | Tool surface: happy `found:true`, `found:false` negative, and `EnrichmentSourceError → ToolError` mapping | `tests/e2e/test_server.py` (extend) | `uv run pytest tests/e2e` |
| `errors.py` — `EnrichmentSourceError` class (entity/config) | none | build gate only (exercised indirectly by client + facade tests) | — | build gate only |

## Parallelism Assessment

> Generated from codebase — confirm before Execute.

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --------- | -------------- | --------------- | -------- |
| unit | Yes | Pure functions + injected `http_get` seam + `tmp_path` for cover files; no shared store | `tests/unit/test_folder_scan.py` (pure, `tmp_path`); spec network test-safety rule |
| integration | Yes | Per-test `scratch_library` fixture bootstraps an empty library under `tmp_path` (function-scoped) | `tests/conftest.py:20` `scratch_library` fixture |
| e2e | Yes | Same per-test `scratch_library`; ENRICH-01 writes nothing, so no cross-test state | `tests/conftest.py:20`; `tests/e2e/test_server.py` |

> Note: the repo does not run `pytest-xdist`, so execution is sequential regardless; `[P]` below is
> ordering/independence information only, not a directive to spawn a worker per task.

## Gate Check Commands

> Generated from codebase — confirm before Execute.

| Gate Level | When to Use | Command |
| ---------- | ----------- | ------- |
| Quick | After tasks with unit tests only | `uv run pytest tests/unit` |
| Full | After tasks with integration/e2e tests | `uv run pytest` |
| Build | After phase completion or config/entity-only tasks | `uv run ruff check src tests && uv run mypy && uv run pytest` |

---

## Execution Plan

### Phase 1: Foundation — error taxonomy (Sequential)

```
T1
```

### Phase 2: Open Library client — the sole outbound-I/O module (Sequential, same file)

```
T1 → T2 → T3 → T4
```

`T3` and `T4` both build on `T2`'s scaffold and both edit `openlibrary_client.py`, so they run in
order (not `[P]`) to avoid concurrent edits to one file.

### Phase 3: Facade orchestration (Sequential)

```
T1, T3, T4 → T5
```

### Phase 4: Tool surface + closeout (Sequential)

```
T5 → T6 → T7
```

---

## Parallel Execution Map

```
Phase 1 (Sequential):
  T1

Phase 2 (Sequential — one file, openlibrary_client.py):
  T1 ──→ T2 ──→ T3 ──→ T4

Phase 3 (Sequential):
  {T1, T3, T4} ──→ T5

Phase 4 (Sequential):
  T5 ──→ T6 ──→ T7
```

No task is marked `[P]`: Phase 2 is a single-file build-up (ordered), and Phases 1/3/4 are strict
dependency chains. Parallelism exists only at the test-runner level (all layers are parallel-safe),
not at the task level.

---

## Task Breakdown

### T1: Add `EnrichmentSourceError` to the failure taxonomy

**What**: Add `class EnrichmentSourceError(CalibreMcpError)` — external source
unreachable/timeout/HTTP≥400/parse failure; carries a short reason (optionally the URL, no secrets).
**Where**: `src/calibre_mcp/errors.py`
**Depends on**: None
**Reuses**: `CalibreMcpError` base (`errors.py:11`); mirror the shape of `CalibredbError` (`errors.py:45`).
**Requirement**: LOOKUP-08

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [ ] `EnrichmentSourceError(CalibreMcpError)` defined with a docstring naming the transport/HTTP/parse cause
- [ ] Exported/importable as `from calibre_mcp.errors import EnrichmentSourceError`
- [ ] Build gate passes: `uv run ruff check src tests && uv run mypy && uv run pytest`

**Tests**: none (entity/config layer — build gate only)
**Gate**: build

**Commit**: `feat(errors): add EnrichmentSourceError for outbound-source failures`

---

### T2: Scaffold `OpenLibraryClient` — record dataclass, injectable transport, retry + error mapping

**What**: Create `openlibrary_client.py` with the `OpenLibraryRecord` frozen dataclass, the
`OpenLibraryClient.__init__(*, http_get, timeout=10.0, retries=1, user_agent=_DEFAULT_UA)` seam, the
private `_urllib_get(url, timeout) -> bytes` real call site (sets `User-Agent`; wraps
`URLError`/`HTTPError`/`socket.timeout` → `EnrichmentSourceError`), and the ≤1-retry loop around it.
No `fetch_record`/`download_cover` bodies yet (added in T3/T4).
**Where**: `src/calibre_mcp/openlibrary_client.py` (new)
**Depends on**: T1
**Reuses**: sibling-runner discipline (`calibredb_runner.py`, AD-014); stdlib `urllib.request`,
`socket`; `errors.EnrichmentSourceError`.
**Requirement**: LOOKUP-08, LOOKUP-10

**Tools**:

- MCP: NONE
- Skill: `python-delivery-stack` (stdlib urllib + injectable-seam module design)

**Done when**:

- [ ] `OpenLibraryRecord(publisher, pubdate, description, cover_url)` frozen dataclass, all `str | None`
- [ ] `__init__` stores the injectable `http_get`, `timeout`, `retries`, `user_agent`; `HttpGet = Callable[[str, float], bytes]`
- [ ] A private retry helper calls the seam, retries at most once on `EnrichmentSourceError`, then re-raises
- [ ] `_urllib_get` wraps `URLError`/`HTTPError`/`socket.timeout` → `EnrichmentSourceError` and sets a descriptive `User-Agent`
- [ ] Unit tests: (a) fake seam raising once-then-succeeds → exactly **one** retry (call count == 2); (b) fake seam raising always → `EnrichmentSourceError` (no crash); (c) the configured `timeout` is passed through to the seam (spy the arg); (d) `retries=0` → no retry
- [ ] `mypy --strict` clean on the new module
- [ ] Quick gate passes: `uv run pytest tests/unit`
- [ ] Test count: ≥4 unit tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(openlibrary): scaffold client with injectable transport, bounded retry`

---

### T3: Implement `fetch_record` — Books API + work-record description follow-up

**What**: Add `fetch_record(self, isbn) -> OpenLibraryRecord | None`: GET the Books API
(`/api/books?bibkeys=ISBN:<isbn>&format=json&jscmd=data`) parsing publisher / publish_date /
cover-**id** URL; when the structured record omits a description, one follow-up GET to the work
record for `description`, flattening the `{"value": ...}` object form to its string; return `None` on
a clean 404/empty; raise `EnrichmentSourceError` on parse failure. The description follow-up is
**non-fatal** (publisher/pubdate still returned if it fails).
**Where**: `src/calibre_mcp/openlibrary_client.py` (modify)
**Depends on**: T2
**Reuses**: T2's retry seam; stdlib `json`; verified endpoints in design §Research notes.
**Requirement**: LOOKUP-04, LOOKUP-07, LOOKUP-08

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [ ] Books API JSON keyed by `"ISBN:<isbn>"` parsed into publisher, raw `publish_date`, cover-id URL (largest available)
- [ ] Description absent in structured record → work-record follow-up GET populates `description` (LOOKUP-04)
- [ ] Work `description` accepts **both** a bare string and the `{"type":..,"value":..}` object → string extracted
- [ ] Clean not-found (empty/404 body) → returns `None` (LOOKUP-07)
- [ ] Unparseable/HTTP≥400 body → `EnrichmentSourceError` (LOOKUP-08)
- [ ] Failed description follow-up is non-fatal: `description=None`, publisher/pubdate still returned
- [ ] Unit tests cover: happy (books + work follow-up), both description shapes, no-description-needed (present in structured), clean not-found → `None`, parse error → `EnrichmentSourceError`, non-fatal follow-up failure — all with canned bytes through the seam (zero real network)
- [ ] Quick gate passes: `uv run pytest tests/unit`
- [ ] Test count: ≥6 unit tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(openlibrary): fetch_record with description work-follow-up`

---

### T4: Implement `download_cover` — id-URL image to a surviving temp file

**What**: Add `download_cover(self, cover_url, dest_dir=None) -> Path`: GET the image bytes and write
them to a uniquely-named temp file (prefix `calibre-mcp-enrich-`) under the system temp dir (NOT an
auto-cleaned context-managed dir — the file must outlive the call for COVER-02); return the path;
raise `EnrichmentSourceError` on failure (the facade, in T5, decides that's non-fatal).
**Where**: `src/calibre_mcp/openlibrary_client.py` (modify)
**Depends on**: T2
**Reuses**: T2's retry seam; stdlib `tempfile`, `pathlib`.
**Requirement**: LOOKUP-06 (download half), LOOKUP-09 (raises; non-fatality handled in facade)

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [ ] On success writes the exact fetched bytes to a uniquely-named file and returns its `Path`
- [ ] The file **survives** the call (not deleted on return) — asserted by reading it back after the method returns
- [ ] Filename prefix `calibre-mcp-enrich-`; respects an optional `dest_dir`
- [ ] Fetch failure → `EnrichmentSourceError` (no partial/zero-byte file left as a valid result)
- [ ] Unit tests: success (bytes on disk equal canned image, file exists post-return), failure → `EnrichmentSourceError`, custom `dest_dir` honored — canned bytes through the seam
- [ ] Quick gate passes: `uv run pytest tests/unit`
- [ ] Test count: ≥3 unit tests pass (no silent deletions)

**Tests**: unit
**Gate**: quick

**Commit**: `feat(openlibrary): download_cover to a surviving temp file`

---

### T5: Facade `enrich_from_identifier` — read-only orchestration + gap-only proposal

**What**: Add `CalibreLibrary.enrich_from_identifier(self, book_id) -> dict[str, Any]` and its private
helpers (`_normalize_isbn`, `_field_missing`, `_gap_proposal`, `_propose_cover`); wire
`self._enricher = OpenLibraryClient()` in `__init__`. Flow per design §Components: `get_book`
precheck → normalize ISBN (early `found:false` no-network if absent) → `fetch_record` (`None` →
`found:false` no-record) → gap-only `proposed`/`skipped_present` (pubdate uses the `0101-01-01%`
rule) → best-effort cover via `cover_file` + `download_cover` (download failure → `cover.local_path:
null, error`, non-fatal). Writes nothing; no token, no backup.
**Where**: `src/calibre_mcp/library.py` (modify — method + helpers + `__init__` wiring)
**Depends on**: T1, T3, T4
**Reuses**: `find_duplicates` advisory shape (`library.py:165`); `get_book` (`sqlite_reader.py:77`);
`cover_file` COVER-01 (`sqlite_reader.py:343`); placeholder-pubdate rule (`sqlite_reader.py:531`).
**Requirement**: LOOKUP-01, LOOKUP-02, LOOKUP-03, LOOKUP-04, LOOKUP-05, LOOKUP-06, LOOKUP-07, LOOKUP-09

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [ ] Happy path returns the full advisory dict (`found:true`, `source`, `identifier_used` normalized, gap-only `proposed`, `skipped_present`, `cover`) and the library is **byte-for-byte unchanged** (LOOKUP-01)
- [ ] No `isbn` → `{found:false, reason:"no usable identifier (ISBN)"}` and the fake enricher is **never called** (LOOKUP-02)
- [ ] Unknown id → `BookNotFoundError`; non-int id → `InvalidInputError` — both before any enricher call (LOOKUP-03)
- [ ] `comments` sourced from the work `description` when the book lacks comments (LOOKUP-04)
- [ ] A present target field (incl. pubdate not matching `0101-01-01%`) appears in `skipped_present`, not `proposed` (LOOKUP-05)
- [ ] No cover + record has a cover → `cover.local_path` is an on-disk file whose bytes equal the canned image; book already has a cover → `cover: null` (LOOKUP-06)
- [ ] `fetch_record` returns `None` → `{found:false, identifier_used, reason:"no record at source"}` (LOOKUP-07)
- [ ] Cover download raising → `proposed` still returned with `cover:{url, local_path:null, error}` (LOOKUP-09)
- [ ] ISBN normalization edge (hyphens/spaces/lower `x`) echoed normalized in `identifier_used`; "all fields present + has cover" → `found:true, proposed:{}, skipped_present:[all three], cover:null`
- [ ] Integration tests use `scratch_library` + an injected fake enricher (zero real network), asserting the spec's Independent Test scenarios (a)–(e)
- [ ] Full gate passes: `uv run pytest`
- [ ] Test count: ≥9 integration tests pass (no silent deletions)

**Tests**: integration
**Gate**: full

**Commit**: `feat(library): enrich_from_identifier read-only lookup (ENRICH-01)`

---

### T6: Expose the `enrich_from_identifier` MCP tool

**What**: Add `@mcp.tool() @_map_errors def enrich_from_identifier(book_id: int) -> dict:` returning
`_jsonify(_get_library().enrich_from_identifier(book_id))`, with the host-facing docstring from design
§Components (read-only, proposes, feeds ENRICH-02/COVER-02, clear error when offline). No
`confirmation_token`.
**Where**: `src/calibre_mcp/server.py` (modify)
**Depends on**: T5
**Reuses**: `_map_errors`/`_jsonify`/`_get_library` (`server.py:42/54/102`); mirror an existing read
tool (`search_books`, `server.py:110`).
**Requirement**: LOOKUP-01, LOOKUP-08 (mapping)

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [ ] Tool registered, read-only (no `confirmation_token`), docstring names read-only + apply path
- [ ] E2E: driving the tool over a `scratch_library` (fake enricher injected) returns the `found:true` JSON payload
- [ ] E2E: a `found:false` negative surfaces as normal JSON (not an error)
- [ ] E2E: `EnrichmentSourceError` from the facade maps to a clean `ToolError` (no traceback to host)
- [ ] Full gate passes: `uv run pytest`
- [ ] Test count: ≥3 e2e tests pass (no silent deletions)

**Tests**: e2e
**Gate**: full

**Commit**: `feat(server): expose enrich_from_identifier tool`

---

### T7: Record AD-026 (outbound-network policy) + close out traceability

**What**: Append **AD-026 — first outbound-network policy** to `.specs/STATE.md` `## Decisions`
(HTTP as a fourth I/O kind confined to `openlibrary_client.py`; bounded 10s timeout + ≤1 retry;
all failures → `EnrichmentSourceError → ToolError`; injectable-seam network test-safety rule; prefer
non-rate-limited cover-id URLs). Flip LOOKUP-01..10 status to Verified in `spec.md` traceability, and
update the STATE.md Handoff snapshot. (Take the next free AD number if AD-025/026 already taken by
COVER-02 at closeout.)
**Where**: `.specs/STATE.md`, `.specs/features/identifier-lookup/spec.md`
**Depends on**: T6
**Reuses**: existing AD entries in `.specs/STATE.md` `## Decisions` as the format template.
**Requirement**: LOOKUP-08, LOOKUP-10 (policy record); traceability closeout

**Tools**:

- MCP: NONE
- Skill: NONE

**Done when**:

- [ ] AD-026 (or next free number) recorded in `.specs/STATE.md` `## Decisions` with context/decision/consequences
- [ ] `spec.md` Requirement Traceability rows LOOKUP-01..10 → Verified
- [ ] STATE.md Handoff snapshot updated to reflect ENRICH-01 done
- [ ] Build gate passes: `uv run ruff check src tests && uv run mypy && uv run pytest` (docs-only, but confirm suite still green)

**Tests**: none (docs/closeout)
**Gate**: build

**Commit**: `docs(specs): record AD-026 outbound-network policy; close ENRICH-01 traceability`

---

## Pre-Approval Validation

### Check 1 — Task Granularity

| Task | Scope | Status |
| ---- | ----- | ------ |
| T1: EnrichmentSourceError | 1 class | ✅ Granular |
| T2: client scaffold | 1 dataclass + `__init__`/transport/retry (one module bootstrap) | ✅ Granular |
| T3: `fetch_record` | 1 method | ✅ Granular |
| T4: `download_cover` | 1 method | ✅ Granular |
| T5: `enrich_from_identifier` facade | 1 method + its private helpers (one cohesive deliverable) | ✅ Granular |
| T6: tool wrapper | 1 tool | ✅ Granular |
| T7: AD + traceability | docs closeout | ✅ Granular |

### Check 2 — Diagram-Definition Cross-Check

| Task | Depends On (body) | Diagram Shows | Status |
| ---- | ----------------- | ------------- | ------ |
| T1 | None | (Phase 1 root) | ✅ Match |
| T2 | T1 | T1 → T2 | ✅ Match |
| T3 | T2 | T2 → T3 | ✅ Match |
| T4 | T2 | T2 → T3 → T4 (T4 after T2; ordered same-file) | ✅ Match |
| T5 | T1, T3, T4 | {T1,T3,T4} → T5 | ✅ Match |
| T6 | T5 | T5 → T6 | ✅ Match |
| T7 | T6 | T6 → T7 | ✅ Match |

> T4 depends only on T2 logically; it is placed after T3 in Phase 2 solely because both edit
> `openlibrary_client.py` (serialize edits to one file). No `[P]` claimed, so no parallel-conflict.

### Check 3 — Test Co-location Validation

| Task | Code Layer Created/Modified | Matrix Requires | Task Says | Status |
| ---- | --------------------------- | --------------- | --------- | ------ |
| T1 | `errors.py` (entity/config) | none | none | ✅ OK |
| T2 | `openlibrary_client.py` | unit | unit | ✅ OK |
| T3 | `openlibrary_client.py` | unit | unit | ✅ OK |
| T4 | `openlibrary_client.py` | unit | unit | ✅ OK |
| T5 | `library.py` facade | integration | integration | ✅ OK |
| T6 | `server.py` tool | e2e | e2e | ✅ OK |
| T7 | `.specs/*` docs | none | none | ✅ OK |

All three checks pass — no ❌.

---

## Tools per task (MCPs & Skills)

- **MCP**: none of the tasks need an MCP server — this is pure in-repo Python. (The `calibre` MCP is
  the product being built, not a build tool.)
- **Skills**: `spec-driven` orchestrates every task (Execute flow + Verifier); `python-delivery-stack`
  is worth loading for T2–T4 (stdlib-urllib module design, injectable seam, async/timeout hygiene);
  `commit-conventions` for the per-task commits.

**Question for you before Execute:** does this tool/skill assignment look right, or do you want a
different split (e.g. fold T2 into T3, or make the cover download part of T5)?
