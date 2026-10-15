# Cover Coverage (STATS-02) Validation

**Date**: 2026-10-01
**Spec**: `.specs/features/cover-coverage/spec.md`
**Diff range**: `8a2114e^..8a2114e` (feat(stats): report cover coverage and uncovered ids)
**Verifier**: independent sub-agent (author != verifier). All test and mutation runs were done in a scratch copy of the repo checked out at `8a2114e`, with its own rebuilt `.venv`. The real working tree and the real Calibre library were not touched, and no network calls were made.

**Verdict**: FAIL. 1 surviving mutant breaks a spec-defined value (the cap of 50).

---

## Task Completion

No `tasks.md` exists for this feature (Quick Capture spec). The commit diff is the only task surface: `sqlite_reader.py` (+15), `server.py` (docstring only), plus 3 test files.

---

## Spec-Anchored Acceptance Criteria

| AC | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| COVCOV-01 | `metadata_completeness.cover == {"filled": <has_cover=1 count>, "pct": round(100*filled/books, 1)}` | `tests/integration/test_sqlite_reader.py:586`: `stats.metadata_completeness["cover"] == {"filled": 1, "pct": 33.3}` (1 covered of 3 books, so the rounding is exercised) | PASS |
| COVCOV-02 (order + content) | `data_quality.missing_cover_ids` = uncovered ids, ascending | `tests/integration/test_sqlite_reader.py:587`: `== sorted([uncovered_a, uncovered_b])`; `:585`: `covered not in ...` | PASS |
| COVCOV-02 (cap = 50) | at most **50** ids. Spec Verification says: "cap asserted with 51+ uncovered books" | `tests/integration/test_sqlite_reader.py:602`: `== sorted(ids)[:2]`, but only after `monkeypatch.setattr(..., "MISSING_COVER_IDS_CAP", 2)` (`:597`). Nothing asserts that the value is 50 | GAP: the test asserts that a cap exists, not the spec value 50 (mutant M4 survives) |
| COVCOV-03 | empty library: `cover == {"filled": 0, "pct": 0.0}` and `missing_cover_ids == []`, no error | `tests/integration/test_sqlite_reader.py:566`: `metadata_completeness["cover"] == {"filled": 0, "pct": 0.0}`; `:564`: `"missing_cover_ids": []`; `tests/integration/test_library_reads.py:173`: `"missing_cover_ids": []` via the facade | PASS |
| COVCOV-04 | `calibre://library/stats` payload carries both keys | `tests/e2e/test_server.py:1226`: `stats["metadata_completeness"]["cover"] == {"filled": 1, "pct": 50.0}`; `:1227`: `stats["data_quality_flags"]["missing_cover_ids"] == [uncovered]` (read through FastMCP `read_resource`) | PASS |

**Spec-precision note (minor)**: the spec names the key `data_quality.missing_cover_ids`. That matches the reader's `LibraryStats.data_quality`. The resource and facade payload rename that object to `data_quality_flags` (STATS-01 convention). Tests assert the real names. The spec wording should say `data_quality_flags` for the resource.

**Status**: 4/4 ACs have evidence. 1 AC sub-clause (cap value 50) is not asserted against the spec value.

---

## Discrimination Sensor

Tests run per mutant: the 3 STATS-02 tests, the 2 empty-library integration tests, and the empty plus cover e2e tests.

| # | File:line | Mutation | Killed? |
| --- | --- | --- | --- |
| M1 | `src/calibre_mcp/sqlite_reader.py:521` | completeness `has_cover = 1` -> `has_cover = 0` | Killed (`test_sqlite_reader.py:586`, `:603`). The e2e test survives because its 1/1 split is symmetric |
| M2 | `src/calibre_mcp/sqlite_reader.py:585` | missing-ids `has_cover = 0` -> `has_cover = 1` | Killed (integration x2 + e2e) |
| M3 | `src/calibre_mcp/sqlite_reader.py:585` | `ORDER BY id` -> `ORDER BY id DESC` | Killed (`:587`, `:602`) |
| M4 | `src/calibre_mcp/sqlite_reader.py:20` | `MISSING_COVER_IDS_CAP = 50` -> `500` | **Survived**. Every test passes |
| M5 | `src/calibre_mcp/sqlite_reader.py:585` | LIMIT neutralised (`LIMIT -1`) | Killed (`:602`) |

**Sensor depth**: lightweight (5 mutations).
**Result**: 4/5 killed. FAIL because of M4.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code / surgical (one SQL count, one bounded SELECT, one named constant) | PASS |
| No scope creep (no disk check, matches Out of Scope) | PASS |
| Matches patterns (same `filled/pct` helper as STATS-01, pure SQL) | PASS |
| Spec-anchored outcome check | GAP: cap value not asserted |
| Every test maps to an AC (01/02/03/04) | PASS |

---

## Edge Cases

- [x] Empty library: zeroed, no error (COVCOV-03, see above)
- [ ] Exactly 50 vs 51 uncovered books: not exercised at the spec value

---

## Gate Check

- **Commands (scratch copy @ 8a2114e)**: `uv run ruff check src tests` -> `All checks passed!` (exit 0). `uv run mypy` -> `Success: no issues found in 17 source files` (exit 0). `uv run pytest -q -p no:cacheprovider tests/integration/test_sqlite_reader.py tests/integration/test_library_reads.py tests/e2e/test_server.py -k stats`
- **Result**: 17 selected, **11 passed, 0 failed, 6 skipped**
- **Skipped**: 6 tests are opt-in real-library tests (`CALIBRE_MCP_TEST_REAL_LIBRARY is unset`). Skipping them is correct under the "never touch the real library" rule. One of them is `test_library_stats_returns_every_ac1_sub_object`, which carries the new `"cover"` / `"missing_cover_ids"` key-set assertions (`test_sqlite_reader.py:468`, `:479`), so those two assertions did not run.
- **Environmental flake (not a product failure)**: a concurrent verifier was running the full suite in another scratch copy. Its `calibredb` calls hold Calibre's global single-instance lock, so bulk runs intermittently showed `LibraryLockedError` / "Another calibre program ... is running" failures and skips. The figures above come from running each test node on its own, retrying only on that lock signature (throwaway script `scratchpad/retry_run.py`). No test failed for a reason other than the lock.

---

## Fix Plans

### Fix 1: assert the spec cap value (COVCOV-02)

- **Root cause**: `test_library_stats_missing_cover_ids_are_capped` monkeypatches the cap to 2, so it proves that a cap exists but not that the cap is 50. The spec explicitly asks for 51+ uncovered books.
- **Fix task**: add `assert sqlite_reader_module.MISSING_COVER_IDS_CAP == 50` (cheapest). Alternatively, seed 51 uncovered rows (e.g. a direct SQLite insert into the scratch `books` table, or a loop of `calibredb add --empty`) and assert `len(missing_cover_ids) == 50` and `== sorted(ids)[:50]`.
- **Verify**: re-run mutant M4 (`50 -> 500`) and confirm it is killed.
- **Priority**: Minor (behavior is correct today; only the guard is missing).

---

## Requirement Traceability Update

| Requirement | Previous | New |
| --- | --- | --- |
| COVCOV-01 | Implementing | Verified |
| COVCOV-02 | Implementing | Needs Fix (cap value unguarded) |
| COVCOV-03 | Implementing | Verified |
| COVCOV-04 | Implementing | Verified |

**Success criterion** (real library reports 192/194 and lists 2 ids): UNVERIFIABLE by this verifier, because reading the real library was forbidden. The commit message claims `[53, 184]`, but that is not evidence.

---

## Summary

**Overall**: FAIL. Small fix.
**Spec-anchored check**: 4/4 ACs evidenced; 1 sub-clause (cap = 50) not asserted at the spec value.
**Sensor**: 4/5 killed (M4 cap 50->500 survived).
**Gate**: ruff 0, mypy 0, pytest 11 passed / 0 failed / 6 skipped (real-library opt-in).
**Next step**: Fix 1, then re-run M4.

---

## Round 2: re-review of fix commit `4c798f5` (scoped to that diff)

**Diff range**: `8a2114e..4c798f5`
**Setup**: a fresh scratch copy, checked out at `4c798f5`, with its own rebuilt `.venv`. The import path was confirmed to be the copy's `src/`. The real tree and the real library were not touched.

### Gap 1: cap value 50 (COVCOV-02). CLOSED

- `tests/integration/test_sqlite_reader.py:598` now asserts `sqlite_reader_module.MISSING_COVER_IDS_CAP == 50` before the monkeypatch. The capping behavior is still exercised at 2 (`:602`-ish, `== sorted(ids)[:2]`).
- I re-ran mutant M4 in the copy: `sed 's/MISSING_COVER_IDS_CAP = 50/... = 500/'`, then `uv run pytest ... ::test_library_stats_missing_cover_ids_are_capped`. Output: `E assert 500 == 50` / `tests/integration/test_sqlite_reader.py:598: AssertionError` / `1 failed in 0.47s`. **Killed by the pin assertion.** The failure is not a lock error: it fires before any calibredb call. The mutation was reverted and `git status` is clean.
- Together, the two assertions show that the constant is 50 and that the query honours the constant: M5 (LIMIT neutralised) is killed by the lowered-cap assertion, and that part of the test is unchanged.
- Spec Verification wording was revised to "cap value pinned + behavior exercised with a lowered cap". I accept this as equivalent evidence for "at most 50".

### Gap 2: real-library success criterion. ACCEPTED AS ORCHESTRATOR EVIDENCE (not independently re-run)

The orchestrator reports an in-session `SqliteReader` read: `cover {filled: 192, pct: 99.0}`, `missing_cover_ids [53, 184]`. This is recorded in spec.md Success Criteria. The numbers are internally consistent: 192/194 = 98.97 -> 99.0. Per the rules for this run, this verifier did not read the real library.

### Spec-precision note: key names. CLOSED

COVCOV-02 now names the key per layer: reader `data_quality`, resource `data_quality_flags`. This matches the assertions at `test_sqlite_reader.py:587` and `tests/e2e/test_server.py:1227`.

### Gate (round 2)

- `uv run ruff check src tests`: `All checks passed!` (exit 0)
- `uv run mypy`: `Success: no issues found in 18 source files` (exit 0)
- pytest `-k stats` over the 3 files: 17 selected, **11 passed, 0 failed, 6 skipped**. The 6 skips are real-library opt-in tests (`CALIBRE_MCP_TEST_REAL_LIBRARY is unset`). Tests were run one node at a time, retrying only on Calibre's global-lock signature, because the ENRICH-04 verifier was still contending for the lock (up to 8 attempts for one node). No test failed for any other reason.

### Sensor (cumulative)

5/5 mutants killed (M1-M3, M5 from round 1; M4 now killed).

### Traceability

COVCOV-01..04: all Verified.

**Round 2 verdict**: PASS
