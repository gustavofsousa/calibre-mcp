# Identifier-Based Metadata Lookup (ENRICH-01) — Validation Report

**Date**: 2026-07-31
**Spec**: `.specs/features/identifier-lookup/spec.md` (requirements LOOKUP-01..10)
**Diff range**: `ff81271..f32dc94` (8 commits — 7 feature + fix iteration 1)
**Verifier**: independent sub-agent (author ≠ verifier) — fresh eyes, no context inherited

**Verdict: PASS (full — all 10 requirements Verified after fix iteration 1)**

Fix iteration 1 (commit `f32dc94`, test-only, no product-code change) closed both gaps the initial
pass flagged. All LOOKUP-01..10 are now covered, spec-anchored, and discriminating: every injected
mutant — including the two previously-open ones — is killed.

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 EnrichmentSourceError | ✅ Done | `errors.py:103` `EnrichmentSourceError(CalibreMcpError)`; importable |
| T2 OpenLibraryClient scaffold (seam, retry, error map) | ✅ Done | unit tests green (incl. real `_urllib_get` UA/error-wrap) |
| T3 fetch_record (Books API + work follow-up) | ✅ Done | happy/object-form/no-follow-up/not-found/parse-error/non-fatal covered |
| T4 download_cover (surviving temp file) | ✅ Done | bytes-on-disk, survives, prefix, failure, custom dest_dir |
| T5 facade enrich_from_identifier | ✅ Done | integration tests green (incl. lower-case-x normalization edge) |
| T6 tool surface + closeout | ✅ Done | 3 e2e tests green; AD-026 recorded |

---

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| LOOKUP-01 has ISBN + record → advisory proposal, no write | full result dict + metadata.db byte-for-byte unchanged | `tests/integration/test_library_enrich.py:159-172` — exact `result == {...found:true, source:"openlibrary", identifier_used, proposed{comments,publisher,pubdate}, skipped_present:[], cover:null}` AND `_db_digest == before`; e2e `tests/e2e/test_server.py:1304-1312` | ✅ PASS |
| LOOKUP-02 no ISBN → found:false, NO network | `{book_id, found:false, reason:"no usable identifier (ISBN)"}`, enricher never called | `tests/integration/test_library_enrich.py:188-193` — exact dict + `fetch_calls == 0`; e2e `:1325-1329` | ✅ PASS |
| LOOKUP-03 unknown/non-int id → error before network | `BookNotFoundError` / `InvalidInputError`, pre-network | `tests/integration/test_library_enrich.py:204-206` — `raises(BookNotFoundError)` + `fetch_calls == 0`; `:212-213` — `raises(InvalidInputError)` | ✅ PASS |
| LOOKUP-04 description via work follow-up; `{value}` flattened | comments = work description; object-form → string | client `tests/unit/test_openlibrary_client.py:126-133`, `:137-151` (object form), `:185-199` (non-fatal); facade `tests/integration/test_library_enrich.py:164-168` | ✅ PASS |
| LOOKUP-05 propose only missing; present → skipped_present; pubdate placeholder = missing | present skipped; `0101-01-01%` counts missing | `tests/integration/test_library_enrich.py:232-233` — `proposed == {}`, `skipped_present == ["comments","publisher","pubdate"]`; placeholder-as-missing via happy path `:159-172` | ✅ PASS |
| LOOKUP-06 no cover → download id-URL to temp, local_path; has cover → null | downloaded local file w/ canned bytes; else null + no download | `tests/integration/test_library_enrich.py:251-253`, `:272-273` (`download_calls == 0`); client `tests/unit/test_openlibrary_client.py:221-229` | ✅ PASS |
| LOOKUP-07 ISBN but no source record → found:false, not error | `{found:false, identifier_used, reason:"no record at source"}` | `tests/integration/test_library_enrich.py:287-292`; client `tests/unit/test_openlibrary_client.py:170-173` | ✅ PASS |
| LOOKUP-08 transport/HTTP/parse → EnrichmentSourceError, no partial | `EnrichmentSourceError`; not swallowed; maps to ToolError | client seam `tests/unit/test_openlibrary_client.py:48-56`, `:177-181`; **real `_urllib_get`** URLError `:293-305` and HTTPError-with-"503" `:308-322`; facade `tests/integration/test_library_enrich.py:304-305`; e2e `tests/e2e/test_server.py:1340-1343` | ✅ PASS |
| LOOKUP-09 cover download failure non-fatal | metadata proposed intact, `cover:{url, local_path:null, error}` | `tests/integration/test_library_enrich.py:322-329`; client `tests/unit/test_openlibrary_client.py:233-240` | ✅ PASS |
| LOOKUP-10 bounded timeout + ≤1 retry + descriptive User-Agent | ≤1 retry; configured timeout to transport; **default 10.0s + `_DEFAULT_UA` header** | retry: `tests/unit/test_openlibrary_client.py:38-45`, `:70-77`, `:48-56`; timeout passthrough: `:60-66`. **Fix iter 1 — User-Agent + default timeout now asserted via the real `_urllib_get`:** `tests/unit/test_openlibrary_client.py:268-289` — `captured["ua"] == _DEFAULT_UA` and `captured["timeout"] == 10.0` (monkeypatched `urlopen`, no injected seam) | ✅ PASS |

**Status**: ✅ All 10 ACs fully covered and spec-anchored.

---

## Discrimination Sensor

Behavior-level faults injected in scratch state (sed edit → run → `git checkout --` restore); tracked
tree confirmed clean after each.

**Initial pass (7-commit range):**

| # | File:line | Mutation | Layer | Killed? |
| --- | --- | --- | --- | --- |
| 1 | `openlibrary_client.py:99` | retry bound `range(self._retries + 1)` → `+ 2` | client | ✅ Killed (2 unit) |
| 2 | `library.py:268` | `_field_missing` pubdate placeholder → always `return False` | facade | ✅ Killed (2 integration) |
| 3 | `library.py:283` | `_propose_cover` guard `is not None` → `is None` | facade | ✅ Killed (4 integration) |
| 4 | `library.py:234` | `_normalize_isbn` drop `.upper()` | facade | ❌ SURVIVED → Fix 1 |

**Fix iteration 1 re-mutation (both previously-open gaps):**

| # | File:line | Mutation | Layer | Killed? |
| --- | --- | --- | --- | --- |
| 4′ | `library.py:234` | `_normalize_isbn` drop `.upper()` (re-test) | facade | ✅ **KILLED** — `test_isbn_with_hyphens_and_lowercase_x_is_normalized_end_to_end` failed at `tests/integration/test_library_enrich.py:158` (`received_isbn` "080442957x" ≠ "080442957X") |
| 5 | `openlibrary_client.py:81` | `_urllib_get` `User-Agent` header → `"WRONG-UA"` | client | ✅ **KILLED** — `test_urllib_get_sets_user_agent_and_default_timeout` failed at `tests/unit/test_openlibrary_client.py:288` |

**Sensor depth**: lightweight (6 mutations total across client + facade layers).
**Result**: 6/6 killed, 0 survived. The previously-surviving `_normalize_isbn` mutant is now KILLED.

---

## Code Quality

| Principle | Status |
| --- | --- |
| No features beyond spec | ✅ read-only, no write path added |
| Surgical / only required files touched | ✅ fix iter 1 is test-only (no product-code change) |
| Matches existing patterns (AD-014/021 sibling-module discipline) | ✅ mirrors calibredb_runner/folder_scan |
| Spec-anchored outcome check (asserted values match spec) | ✅ all 10 ACs |
| Every test maps to a spec AC / edge case | ✅ no unclaimed tests |
| Documented guidelines followed | none project-specific — strong defaults applied |

---

## Gate Check

- **Gate command**: `uv run pytest -q`
- **Initial pass**: 357 passed
- **Fix iteration 1**: **361 passed** in 478.99s (0:07:58); 0 failed, 0 skipped (+4 tests: 3 unit `_urllib_get` UA/URLError/HTTPError + 1 integration lower-case-x normalization)
- **Working tree**: tracked files clean (`git diff --stat` empty) after all mutations reverted

---

## Requirement Traceability Update

| Requirement | Previous | New |
| --- | --- | --- |
| LOOKUP-01..09 | Verified | ✅ Verified |
| LOOKUP-10 | ⚠️ Verified (partial — User-Agent unasserted) | ✅ **Verified** (fix iter 1: UA + default timeout asserted) |

---

## Summary

**Overall**: ✅ Ready — full PASS after fix iteration 1.
**Spec-anchored check**: 10/10 fully matched spec outcome.
**Sensor**: 6/6 mutations killed (both previously-open gaps now closed).
**Gate**: 361 passed, 0 failed.

**What works**: The complete read-only lookup contract — gap-only proposal, description via work
follow-up + `{value}` flattening, no-ISBN / no-record negatives without spurious errors, cover
download to a surviving temp file, non-fatal cover failure, `EnrichmentSourceError` propagation and
ToolError mapping, bounded retry (≤1), timeout pass-through, the real `_urllib_get` User-Agent +
default 10.0s timeout + URLError/HTTPError wrapping, and end-to-end ISBN normalization (strip +
upper-case) — all demonstrated and discriminating.

**Issues**: none open.

**Next steps**: mark ENRICH-01 done; ENRICH-02 (apply `proposed` via `update_metadata`) and COVER-02
(consume the cover `local_path`) are the downstream features.
