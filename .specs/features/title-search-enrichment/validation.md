# Title/Author Search Enrichment (ENRICH-04) Validation

**Date**: 2026-10-01
**Spec**: `.specs/features/title-search-enrichment/spec.md`
**Diff range**: `8a2114e..e9c00f3` (90534ba, 5efb530, 5f9500a, 0073c78, a5d37f0, e45f430, e9c00f3). HEAD `4c798f5` adds no change to the ENRICH-04 surface (`git diff --stat e9c00f3..HEAD -- src <ENRICH-04 tests>` is empty).
**Verifier**: independent sub-agent (author != verifier). All test/mutation runs in a scratch clone (`git clone` + `checkout e9c00f3`) outside the working tree; no real network, no real library.

**Verdict**: FAIL (minor) — every safety-relevant behavior is covered and discriminating; 3 surviving mutants are payload-precision gaps in the `match` block / non-high payload (rounding and exact shape). No production defect found.

---

## Task Completion

| Task | Status | Notes |
| --- | --- | --- |
| T1 matcher | Done | 5efb530 |
| T2 client search | Done | 5f9500a |
| T3 pacing | Done | 0073c78 |
| T4 facade fallback | Done | a5d37f0 |
| T5 batch + bucket | Done | e45f430 |
| T6 tool surface | Done | e9c00f3 |
| T7 docs / AD-032 | Not in range | Uncommitted edits to STATE/ROADMAP/README/BACKLOG/ARCHITECTURE exist in the working tree; not verified here. Spec traceability table still says "Pending". |

---

## Spec-Anchored Acceptance Criteria

| Req | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| TSEARCH-01 search params | title + primary author, limit 5, fields `key,title,author_name,cover_i` | `tests/unit/test_openlibrary_client.py:356-360` `query["title"]==["The Hobbit"]`, `"author" not in query`, `query["limit"]==["5"]`, `query["fields"]==[...]`; `:390` `_query(...)["author"]==["J. R. R. Tolkien"]`; `tests/integration/test_library_enrich.py:453` `search_calls == [("The Hobbit","J. R. R. Tolkien")]` | PASS |
| TSEARCH-01 Unknown author omitted | author omitted when blank/Unknown | `test_library_enrich.py:467` `search_calls == [("The Hobbit", None)]` | PASS |
| TSEARCH-01 title-only retry | one retry without author only if author was sent and none returned | `test_openlibrary_client.py:401-404` `len(spy.calls)==2`, author in 1st / not in 2nd; `:413-414` no retry when author None (`len(spy.calls)==1`) | PASS |
| TSEARCH-01 must-not (ISBN book) | search never queried | `test_library_enrich.py:438` `enricher.search_calls == []` | PASS |
| TSEARCH-02 normalization | accents/case/subtitle cut/punct | `tests/unit/test_title_match.py:34`, `:39-42`, `:57-59` (title_sim 1.0, high) | PASS |
| TSEARCH-02 author token order / multi-author / none | "Bach, James"≡"James Bach"; best across authors; author-less candidate → 0.0 | `test_title_match.py:66`, `:78`, `:86-87` (`author_similarity == 0.0`, `confidence == "medium"`) | PASS |
| TSEARCH-02 thresholds 0.90/0.85/0.60 at boundaries | high iff t>=0.90 ∧ a>=0.85; medium iff t>=0.60 | `test_title_match.py:117-130` parametrized `(0.90,0.85,high)`, `(0.8999,1.0,medium)`, `(1.0,0.8499,medium)`, `(0.60,None,medium)`, `(0.5999,1.0,low)` | PASS |
| TSEARCH-02 must-not (null author → high) | blank/""/"  "/Unknown → `None`, medium | `test_title_match.py:91-98` | PASS |
| TSEARCH-02 rounded to 2 decimals | similarities rounded to 2 dp | only asserted with exact 1.0 values (`test_library_enrich.py:490-505`) | GAP (mutants M10/M20 survive) |
| A6 best-candidate order | rank, then summed sim, then source order | `test_title_match.py:141-145`, `:156-160` | PASS |
| TSEARCH-03 high payload | exact `{book_id, found:true, source, identifier_used:null, match{7 keys}, proposed{comments}, skipped_present, cover}` | `test_library_enrich.py:490-507` exact `result == {...}` + `cover["url"]`, cover bytes; `:509` description fetched once | PASS |
| TSEARCH-03 must-not publisher/pubdate | never proposed, even when missing | same exact-dict assertion (`proposed == {"comments": ...}` on a book lacking publisher/pubdate) | PASS |
| TSEARCH-03 comments gap-only | not proposed when present | `test_library_enrich.py` `test_high_match_never_overwrites_present_comments`: `proposed == {}`, `"comments" in skipped_present`, `cover is None` | PASS |
| TSEARCH-04 non-high | `{book_id, found:false, reason:"no confident match", match}`; no proposal, no cover/description call | `test_library_enrich.py:546-552` `found is False`, `reason == "no confident match"`, `match["confidence"]=="medium"`, `"proposed" not in result`, `description_calls == []`, `download_calls == 0` | PASS with precision gap: payload not asserted by equality (mutant M19 survives); `low` branch not exercised at facade level |
| TSEARCH-05 no result | `{book_id, found:false, reason:"no record at source", match:null}` | `test_library_enrich.py:565-570` exact dict | PASS |
| TSEARCH-06 no usable ISBN/title | `{book_id, found:false, reason:"no usable identifier (ISBN) or title"}`, no network | `test_library_enrich.py:235-241` exact dict + `fetch_calls == 0` + `search_calls == []`; e2e `tests/e2e/test_server.py:1395-1398` | PASS (only the `Unknown` title variant is tested; blank title not seeded) |
| TSEARCH-07 search failure | raises `EnrichmentSourceError` | unit `test_openlibrary_client.py:423`; integration `test_library_enrich.py:583` | PASS |
| TSEARCH-07 description failure non-fatal | `None`, result built without it | unit `test_fetch_work_description_failure_is_none_not_an_error`; integration `test_failed_description_still_returns_the_cover_proposal` (`found is True`, `proposed == {}`, cover url) | PASS |
| TSEARCH-08 read-only + applicable | digest unchanged; `proposed` accepted by `update_metadata` plan→confirm | `test_library_enrich.py:510`, `test_enrichment_batch.py:427` digest equality; e2e `test_server.py:1347-1362` `applied["book"]["comments"] == ...` | PASS |
| TSEARCH-09 selection | ISBN rule unchanged ∪ (no ISBN ∧ usable title ∧ (no comments ∨ no cover)), id order | `tests/integration/test_sqlite_reader_enrich.py:70-71` `ids == [a,b,d]`, `total == 3`; `:165-168` `ids == sorted([no_comments,no_cover])`, `total == 2`, complete/Unknown/isbn-cover-only excluded | PASS |
| TSEARCH-09 bucket + summary | `status:"no_confident_match"`; summary `{proposed,no_new_data,no_record,no_confident_match,error}` | `test_enrichment_batch.py:414-426` exact summary dict incl. `no_confident_match: 1`; e2e `test_server.py:1378-1380` | PASS |
| TSEARCH-09 must-not (non-high proposed) | never | `test_enrichment_batch.py:419` `"proposed" not in by_id[doubtful]` | PASS |
| AD-032 pacing | first request never waits; waits only remainder; retries paced; 1.0 s default for real transport | `test_openlibrary_client.py:473` `slept == []`, `:491` `slept == [0.7]`, `:508`, `:524` `slept == [1.0]`, `test_pacing_defaults_to_one_second_for_the_real_transport` | PASS |

### Edge cases
- [x] accents/case/subtitle still reach high — `test_title_match.py:49-59`
- [x] several catalog authors → best ratio — `test_title_match.py:70-78`
- [x] candidate with no author → 0.0, never high — `test_title_match.py:82-87`
- [~] work without description + book has cover → `found:true`, empty `proposed` (→ `no_new_data`): single-book path covered by `test_high_match_never_overwrites_present_comments` (comments present, cover present → `proposed == {}`), and by `test_failed_description_still_returns_the_cover_proposal` (no description). The exact combination "no description AND book already has a cover → batch `no_new_data`" is not asserted directly.

### Superseded requirements (LOOKUP-02 / ENRICH3-01)
Collected test IDs before (8a2114e) vs after (e9c00f3) over the scoped files: 183 → 229 (+46). Only two IDs disappeared, both renamed-and-revised, not deleted:
- `test_no_isbn_returns_found_false_and_never_calls_enricher` → `test_no_isbn_and_no_usable_title_returns_found_false_without_network` (asserts the TSEARCH-06 reason + adds `search_calls == []`; strengthened).
- `test_selects_only_books_with_isbn_and_a_gap` → `test_selects_isbn_books_with_a_gap` (now `ids == [a,b,d]`; the ISBN-rule negative moved to the new test as `isbn_complete_no_cover not in ids`).
Batch test D-book was given comments + cover so it remains a non-candidate under the revised rule; summaries gained the `no_confident_match: 0` key by exact equality. No weakening beyond the user-decided revision.

---

## Discrimination Sensor (P0-style, safety-relevant external-call path)

Run in scratch clone, each mutant against `tests/unit + test_library_enrich + test_sqlite_reader_enrich + test_enrichment_batch + e2e/test_server` with `-x`. Integration-level kills re-run with `-rf` to confirm the failing test is the intended one (not calibre lock contention).

| # | File | Mutation | Result (killing test) |
| --- | --- | --- | --- |
| M1 | library.py | `!= "high"` → `== "low"` (medium becomes proposal) | KILLED — `test_non_high_match_is_reported_but_never_proposed` |
| M2 | title_match.py | drop `author >= 0.85` from high | KILLED (unit) |
| M3 | library.py | search record carries publisher/pubdate | KILLED — `test_high_match_proposes_description_and_cover_only` |
| M4 | openlibrary_client.py | remove title-only retry | KILLED (unit) |
| M5a | openlibrary_client.py | skip pacing sleep | KILLED (unit) |
| M5b | openlibrary_client.py | sleep full interval instead of remainder | KILLED (unit) |
| M6a | title_match.py | `Unknown` treated as usable | KILLED (unit) |
| M6b | sqlite_reader.py | SQL selects `Unknown` titles | KILLED — `test_isbn_less_books_are_candidates_only_when_search_can_fill_a_gap` |
| M7 | library.py | `no_confident_match` → `no_record` | KILLED — `test_isbn_less_books_are_swept_and_only_high_matches_are_proposed` |
| M8 | title_match.py | title `>=` → `>` 0.90 | KILLED (unit) |
| M9 | title_match.py | medium threshold 0.60 → 0.50 | KILLED (unit) |
| M10 | library.py | `title_similarity` not rounded | **SURVIVED** |
| M11 | sqlite_reader.py | drop `OR has_cover = 0` | KILLED — `test_isbn_less_books_are_candidates_only_when_search_can_fill_a_gap` |
| M12 | openlibrary_client.py | limit 5 → 10 | KILLED (unit) |
| M13 | title_match.py | tie-break `>` → `>=` (last wins) | KILLED (unit) |
| M14 | library.py | send raw `Unknown` author to search | KILLED — `test_search_omits_unknown_author` |
| M15 | title_match.py | subtitle cut removed | KILLED (unit) |
| M16 | title_match.py | author tokens not sorted | KILLED (unit) |
| M17 | openlibrary_client.py | description failure raises | KILLED (unit) |
| M18 | openlibrary_client.py | search parse failure swallowed → `[]` | KILLED (unit) |
| M19 | library.py | non-high payload gains an extra key (`identifier_used`) | **SURVIVED** |
| M20 | library.py | `author_similarity` not rounded | **SURVIVED** |

**Sensor depth**: P0-full manual (20 mutants).
**Result**: 17/20 killed. All safety mutants (a)–(g) from the brief killed; 3 survivors are payload-precision only.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code / no scope creep | OK — pure matcher, two client methods, one facade branch, one SQL OR-branch, one bucket |
| Surgical changes | OK — `_fetch_work_description` refactor reuses the new public method; ISBN path unchanged |
| Matches patterns | OK — pure-module pattern, `_FakeEnricher` seam, injectable `sleep`/`clock` |
| Spec-anchored outcome check | Partial — rounding and TSEARCH-04 exact payload not pinned |
| Per-layer coverage | OK — domain 1:1 to TSEARCH-02; facade/batch/e2e cover happy + edge + error |
| Every test maps to a requirement | OK — each new test cites TSEARCH-xx / A-x / AD-032 |
| Guidelines | `CONTRIBUTING.md` (scratch_library only; no real network via `http_get` seam) — followed |

---

## Gate Check

- **Command** (scratch clone at e9c00f3): `uv run ruff check src tests && uv run mypy && uv run pytest -q -p no:cacheprovider tests/unit tests/integration/test_library_enrich.py tests/integration/test_sqlite_reader_enrich.py tests/integration/test_enrichment_batch.py tests/e2e/test_server.py`
- **ruff**: `All checks passed!` · **mypy**: `Success: no issues found in 18 source files`
- **pytest (scoped)**: `229 passed in 153.07s` — 0 failed, 0 skipped
- **Test count before / after (scoped files)**: 183 / 229 (+46; 2 renamed revisions, 0 deleted)
- **Environment note**: a first run made concurrently with another process using calibredb produced `6 failed, 209 passed, 9 skipped, 5 errors` with skips reading "could not bootstrap scratch library: Another calibre program ... is running". The same failure class appeared on the pre-feature commit 8a2114e during that window (`4 failed, 352 passed, 38 skipped, 1 error`). Re-run in isolation: 229/229 green. This is calibredb's global single-instance lock (concurrent suites on one machine), not an ENRICH-04 defect. The full (unscoped) suite was not re-run in isolation.

---

## Spec-precision gaps

1. TSEARCH-02 "similarities rounded to 2 decimals": no test uses a non-trivial similarity in the `match` block (M10/M20 survive).
2. TSEARCH-04 payload is specified exactly (`{book_id, found, reason, match}`), asserted by field probes, not equality (M19 survives); `low` best match not exercised at facade level.
3. "Usable ISBN": the facade uses `_normalize_isbn` (an un-normalizable ISBN falls back to search), while the SQL uses "non-blank `isbn` identifier". A book with a junk ISBN, complete text fields and no cover is not selected by the batch even though the single-book tool would search for it. Edge case; spec does not define it — flag only.
4. TSEARCH-06 blank title: only the `Unknown` placeholder is tested (blank may not be storable via calibredb).

---

## Fix Plans

### Fix 1 (Minor): pin rounding in the `match` block
- **Where**: `tests/integration/test_library_enrich.py` (or a unit test on `_shape_match`)
- **Task**: a high match with non-1.0 similarities (e.g. book "The Hobbit" vs candidate "The Hobbit!" title / author "J R R Tolkien" vs "J.R.R. Tolkien" tuned to stay high) asserting `match["title_similarity"] == round(x, 2)` and `match["author_similarity"] == round(y, 2)` against values computed from `difflib` independently.
- **Done when**: M10 and M20 are killed.

### Fix 2 (Minor): exact TSEARCH-04 payload + low branch
- **Where**: `tests/integration/test_library_enrich.py::test_non_high_match_is_reported_but_never_proposed` (+ a `low` case)
- **Task**: assert `set(result) == {"book_id","found","reason","match"}` (or full equality incl. the match block) and add a low-confidence candidate case.
- **Done when**: M19 is killed.

---

## Requirement Traceability Update

| Requirement | New status |
| --- | --- |
| TSEARCH-01, 03, 05, 06, 07, 08, 09 | Verified |
| TSEARCH-02 | Verified except 2-dp rounding (Fix 1) |
| TSEARCH-04 | Verified behavior; exact payload not pinned (Fix 2) |

## Summary

**Overall**: FAIL (minor) — the safety core holds: only `high` proposes, author required, publisher/pubdate never proposed, Unknown handled, retry/pacing proven, read-only. Ship blockers: none in behavior. To flip to PASS: Fix 1 + Fix 2 (~20 min), then re-run the sensor for M10/M19/M20.

---

## Round 2 (scoped re-review of fix commit `ffbf2d7`)

**Date**: 2026-10-01 · **Scope**: `git show ffbf2d7` only (tests + spec A9; no `src/` change) · **Scratch**: fresh clone at `ffbf2d7`, outside the working tree; no real network, real library untouched. No background jobs from round 1 were still running when this round started (`pgrep` empty).

### Gap closure

| Round-1 gap | Fix evidence | Result |
| --- | --- | --- |
| 1. Rounding to 2 dp (M10, M20) | `tests/integration/test_library_enrich.py` `test_match_similarities_are_rounded_to_two_decimals`: asserts `match["confidence"] == "high"`, `title_similarity == 0.95`, `author_similarity == 0.92`. Raw ratios recomputed independently with `difflib`: `0.95238…` / `0.92307…` | CLOSED |
| 2. Exact TSEARCH-04 payload + low branch (M19) | `test_non_high_match_is_reported_but_never_proposed` now asserts `result == {book_id, found: False, reason: "no confident match", match: {7 keys, author_similarity: 0.16}}`; new `test_low_match_is_reported_but_never_proposed` asserts the exact low payload (`title_similarity 0.0`, `author_similarity 0.3`). Both also keep `description_calls == []`, `download_calls == 0`. Literals independently confirmed with `difflib` (0.16, 0.0, 0.3) | CLOSED |
| 3. Usable-ISBN rule mismatch | spec assumption A9 records the decision (single book → search fallback; batch keeps the AD-027 ISBN rule). Documentation-only, so nothing to execute. Precision note: A9 says such a book "is swept as an ISBN candidate and folds into `no_record`". That holds only when it also lacks comments/publisher/pubdate. A junk-ISBN book with complete text fields and no cover is not swept at all. Non-blocking wording issue. | CLOSED (decision recorded) |
| 4a. Blank title / usable_value | `tests/unit/test_title_match.py` `test_blank_or_unknown_placeholder_is_not_usable` parametrized `[None, "", "   ", "Unknown", " Unknown "]` → `usable_value(value) is None`; `test_real_value_is_usable` | CLOSED (unit level) |
| 4b. Edge "no description + covered book → no_new_data" | `tests/integration/test_enrichment_batch.py` `test_high_match_without_description_on_a_covered_book_is_no_new_data`: `status == "no_new_data"`, `proposed == {}`, `cover is None`, `summary["no_new_data"] == 1` | CLOSED |

### Sensor re-run (fresh clone `r2` at ffbf2d7, without `-x`, with `-rf`)

| Mutation | Result | Killing test(s) |
| --- | --- | --- |
| M10 `title_similarity` not rounded | KILLED | `test_library_enrich.py::test_match_similarities_are_rounded_to_two_decimals` (1 failed, 237 passed) |
| M19 extra key in non-high payload | KILLED | `test_non_high_match_is_reported_but_never_proposed` + `test_low_match_is_reported_but_never_proposed` (2 failed, 236 passed) |
| M20 `author_similarity` not rounded | KILLED | `test_match_similarities_are_rounded_to_two_decimals` (1 failed, 237 passed) |

In every case only the intended tests failed. There were no bootstrap skips or lock errors. Cumulative: **20/20 killed**.

### Gate (fresh clone at ffbf2d7)

- `uv run ruff check src tests` → `All checks passed!`
- `uv run mypy` → `Success: no issues found in 18 source files`
- `uv run pytest -q -p no:cacheprovider -rfEs tests/unit tests/integration/test_library_enrich.py tests/integration/test_sqlite_reader_enrich.py tests/integration/test_enrichment_batch.py tests/e2e/test_server.py` → **238 passed in 157.90s**, 0 failed, 0 skipped (229 → 238, +9 tests, none removed)

### Round 2 verdict

**PASS** — all four round-1 gaps closed, 20/20 mutants killed, scoped gate green. Remaining non-blocking notes:
- The A9 wording is slightly broader than the SQL behavior (see gap 3 above).
- The new batch test uses `# type: ignore[method-assign]` with no reason or issue, so it doesn't follow AGENTS.md's suppression rule. This is style only.
- T7 (docs/traceability) still isn't in a commit I verified.
