# Title/Author Search Enrichment Tasks (ENRICH-04)

## Execution Protocol (MANDATORY -- do not skip)

Implement these tasks with the `spec-driven` skill: activate it by name and follow its Execute flow
and Critical Rules. If the skill cannot be activated, STOP and tell the user.

**Design**: `.specs/features/title-search-enrichment/design.md`
**Status**: In Progress

---

## Test Coverage Matrix

> Generated from codebase + guidelines. Guidelines found: `CONTRIBUTING.md` (invariants: write tests
> only on `scratch_library`, tests never touch the real network — `http_get` seam), `pyproject.toml`
> (markers unit/integration/e2e, `-rs`), `.github/workflows/ci.yml` (ruff + mypy + pytest).

| Code Layer | Required Test Type | Coverage Expectation | Location Pattern | Run Command |
| --- | --- | --- | --- | --- |
| Pure domain (`title_match.py`) | unit | 1:1 to TSEARCH-02 + every listed edge case + threshold boundaries | `tests/unit/test_title_match.py` | `uv run pytest -q tests/unit` |
| HTTP client (`openlibrary_client.py`) | unit (fake `http_get`) | search params, retry, parse error, description best-effort, pacing | `tests/unit/test_openlibrary_client.py` | `uv run pytest -q tests/unit` |
| Reader SQL (`sqlite_reader.py`) | integration | selection rule incl. negatives | `tests/integration/test_sqlite_reader_enrich.py` | `uv run pytest -q tests/integration` |
| Facade (`library.py`) | integration (fake enricher) | TSEARCH-01,03..09 happy + edge + error, digest unchanged | `tests/integration/test_library_enrich.py`, `test_enrichment_batch.py` | `uv run pytest -q tests/integration` |
| Tool surface (`server.py`) | e2e | tool payload + apply through `update_metadata` | `tests/e2e/test_server.py` | `uv run pytest -q tests/e2e` |

## Parallelism Assessment

| Test Type | Parallel-Safe? | Isolation Model | Evidence |
| --- | --- | --- | --- |
| unit | Yes | pure / fakes | `tests/unit/*` use no shared state |
| integration / e2e | Yes (but run sequentially here) | per-test `scratch_library` in `tmp_path` | `tests/conftest.py::scratch_library` |

## Gate Check Commands

| Gate Level | When to Use | Command |
| --- | --- | --- |
| Quick | unit-only tasks | `uv run pytest -q tests/unit` |
| Full | integration/e2e tasks | `uv run pytest -q` |
| Build | phase end / docs | `uv run ruff check src tests && uv run mypy && uv run pytest -q` |

---

## Execution Plan

```
Phase 1 (Foundation):  T1 [P]   T2 ──→ T3
Phase 2 (Facade):      T1, T3 ──→ T4 ──→ T5
Phase 3 (Surface):     T5 ──→ T6 ──→ T7
```

3 phases → executed inline (no sub-agent offer).

## Task Breakdown

### T1: Pure title/author matcher [P]
**What**: `title_match.py` with `normalize_title`, `score`, `pick_best`, `MatchScore`.
**Context**: Nothing exists yet. Done = a pure, stdlib-only module that implements TSEARCH-02 exactly
(normalization, ratios, thresholds high ≥0.90/≥0.85, medium ≥0.60, Unknown/blank author → never
high, best = rank then summed similarity then source order). Needs `SearchCandidate`, so it defines
the import against `openlibrary_client` (T2 adds the dataclass; T1 adds it first if absent).
**Where**: `src/calibre_mcp/title_match.py`, `src/calibre_mcp/openlibrary_client.py` (dataclass only), `tests/unit/test_title_match.py`
**Depends on**: None · **Requirement**: TSEARCH-02
**Done when**: unit tests for accents, subtitle cut, case, token-order author, multi-author best,
author-less candidate → 0.0, Unknown author → medium cap, both threshold boundaries, tie-break; quick gate passes.
**Tests**: unit · **Gate**: quick · **Commit**: `feat(enrich): add deterministic title/author matcher (ENRICH-04)`

### T2: Client search + work description
**What**: `OpenLibraryClient.search_works` and public `fetch_work_description`.
**Context**: Client has the ISBN path only. Done = search builds the documented URL (title, optional
author, `limit=5`, `fields=key,title,author_name,cover_i`), retries once title-only when an
author-query returns nothing, maps `cover_i` to the id cover URL, raises `EnrichmentSourceError` on a
non-object body; `fetch_work_description` returns the flattened description or `None` on any failure.
The existing edition→work hop reuses it.
**Where**: `src/calibre_mcp/openlibrary_client.py`, `tests/unit/test_openlibrary_client.py`
**Depends on**: None · **Requirement**: TSEARCH-01, TSEARCH-07
**Done when**: unit tests through fake `http_get` for URL params, retry, no-retry when no author,
parse error, description best-effort; existing client tests still pass; quick gate passes.
**Tests**: unit · **Gate**: quick · **Commit**: `feat(enrich): search Open Library works by title/author`

### T3: Request pacing
**What**: ≥ `min_interval` (1.0 s) between consecutive requests of one client; injectable `sleep`/`clock`.
**Context**: Open Library documents 1 req/s for unidentified clients; `_fetch` has no pacing. Done = the
first request never waits; a request issued sooner than the interval sleeps exactly the remainder;
retries are paced too.
**Where**: `src/calibre_mcp/openlibrary_client.py`, `tests/unit/test_openlibrary_client.py`
**Depends on**: T2 · **Requirement**: design Risk #1 (AD-032)
**Done when**: unit tests with a fake clock assert sleep amounts; quick gate passes.
**Tests**: unit · **Gate**: quick · **Commit**: `fix(enrich): pace Open Library requests to 1 per second`

### T4: Facade search fallback
**What**: `enrich_from_identifier` → `_enrich_by_search` when no usable ISBN.
**Context**: Facade has the ISBN path. Done = TSEARCH-01/03/04/05/06/07/08 outcomes exactly as the spec
payloads; LOOKUP-02 test revised to TSEARCH-06 (blank title) + a new no-ISBN-with-title test.
**Where**: `src/calibre_mcp/library.py`, `tests/integration/test_library_enrich.py`
**Depends on**: T1, T3 · **Requirement**: TSEARCH-01, 03–08
**Done when**: integration tests per AC incl. digest unchanged and zero cover/description calls for
non-high; full gate passes.
**Tests**: integration · **Gate**: full · **Commit**: `feat(enrich): fall back to title/author search without an ISBN (ENRICH-04)`

### T5: Batch selection + bucket
**What**: extended `enrichable_candidates` + `no_confident_match` bucket.
**Context**: After T4, single-book search works. Done = TSEARCH-09: ISBN-less titled books missing
comments or cover are candidates; summary has the new bucket; ENRICH3-01 tests revised.
**Where**: `src/calibre_mcp/sqlite_reader.py`, `src/calibre_mcp/library.py`, `tests/integration/test_sqlite_reader_enrich.py`, `tests/integration/test_enrichment_batch.py`
**Depends on**: T4 · **Requirement**: TSEARCH-09
**Done when**: integration tests for selection (+ negatives) and buckets; full gate passes.
**Tests**: integration · **Gate**: full · **Commit**: `feat(enrich): sweep ISBN-less books in enrich_missing (ENRICH-04)`

### T6: Tool surface
**What**: docstrings of `enrich_from_identifier` / `enrich_missing` + e2e tests.
**Context**: Behavior done in T4/T5. Done = the host-facing docstrings state the fallback, the `match`
block, high-only proposals, pacing; e2e covers the payload and applying `proposed` via `update_metadata`.
**Where**: `src/calibre_mcp/server.py`, `tests/e2e/test_server.py`
**Depends on**: T5 · **Requirement**: TSEARCH-03, 08, 09
**Done when**: e2e tests pass; build gate passes.
**Tests**: e2e · **Gate**: build · **Commit**: `feat(server): document search fallback on the enrich tools`

### T7: Docs + decision record
**What**: AD-032, ROADMAP v0.4, README, BACKLOG, spec traceability.
**Where**: `.specs/STATE.md`, `ROADMAP.md`, `README.md`, `BACKLOG.md`, `.specs/features/*/spec.md`
**Depends on**: T6 · **Tests**: none · **Gate**: build · **Commit**: `docs: record ENRICH-04/STATS-02 and the v0.4 gate result`

---

## Validation

**Granularity:** T1 one module · T2 two client methods (cohesive) · T3 one concern · T4 one facade
branch · T5 one query + one bucket (cohesive) · T6 one surface · T7 docs → ✅ all.

| Task | Depends On (body) | Diagram Shows | Status |
| --- | --- | --- | --- |
| T1 | None | none | ✅ |
| T2 | None | none | ✅ |
| T3 | T2 | T2 → T3 | ✅ |
| T4 | T1, T3 | T1, T3 → T4 | ✅ |
| T5 | T4 | T4 → T5 | ✅ |
| T6 | T5 | T5 → T6 | ✅ |
| T7 | T6 | T6 → T7 | ✅ |

| Task | Code Layer | Matrix Requires | Task Says | Status |
| --- | --- | --- | --- | --- |
| T1 | pure domain | unit | unit | ✅ |
| T2 | HTTP client | unit | unit | ✅ |
| T3 | HTTP client | unit | unit | ✅ |
| T4 | facade | integration | integration | ✅ |
| T5 | reader + facade | integration | integration | ✅ |
| T6 | tool surface | e2e | e2e | ✅ |
| T7 | docs | none | none | ✅ |

**Tools:** no MCP needed (tests use fakes; no real network). Skills: `spec-driven` (+ `tdd` inner loop).
