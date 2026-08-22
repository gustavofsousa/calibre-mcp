# Rename/Merge a Series Across the Library (ORGN-04) Validation

**Date**: 2026-07-31
**Spec**: `.specs/features/series-rename/spec.md`
**Diff range**: `863f8bd~1..41c0bf8` (branch `chore/open-source-repositioning`)
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 (`SqliteReader.books_by_series`) | ✅ Done | commit `cacde8b`; 2 integration tests |
| T2 (`CalibreLibrary.rename_series` facade) | ✅ Done | commit `1d0d138`; 9 integration tests |
| T3 (`rename_series` MCP tool) | ✅ Done | commit `320d785`; 2 e2e tests |
| T4 (traceability closeout) | ✅ Done | commit `41c0bf8`; STATE.md + spec statuses |

---

## Spec-Anchored Acceptance Criteria

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| ------------------------- | -------------------- | ----------------------- | ------ |
| SRENAME-01: plan (no token) discovers exact-match books, returns per-book `series` current→proposed with unchanged index + one token, writes nothing | status `plan`; only `Old` books listed (`New` proposed, indices shown); token present; no write | `tests/integration/test_library_series_rename.py:112-123` — `plan["status"]=="plan"`, `set(by_id)=={b1,b2}`, `by_id[b1]["diff"]["series"]["proposed"]=="New"`, `by_id[b1]["series_index"]==2.0`, `by_id[b2]["series_index"]==7.5`, `plan["confirmation_token"]`, `get_book(b3).series=="Other"` | ✅ PASS |
| SRENAME-02: `old_series` matches no book → reject before any backup | `InvalidInputError` "series not found"; zero snapshots | `tests/integration/test_library_series_rename.py:129-133` — `pytest.raises(InvalidInputError)`, `"not found" in msg`, `_snapshots(backup_root)==[]`; e2e `tests/e2e/test_server.py:534-541` → `ToolError`, "not found" | ✅ PASS |
| SRENAME-03: blank `new_series` or `new_series == old_series` → reject before backup | `InvalidInputError`; zero snapshots | `tests/integration/test_library_series_rename.py:144-150` — raises on `""`, `"   "`, `"Old"`; `_snapshots(backup_root)==[]` | ✅ PASS |
| SRENAME-04: apply with matching token → one `metadata.db` backup before first write, set via `set_metadata` | status `renamed`; exactly one snapshot | `tests/integration/test_library_series_rename.py:173,183` — `applied["status"]=="renamed"`, `len(_snapshots(backup_root))==1`; order guard `:250-271` | ✅ PASS |
| SRENAME-05: token mismatch → refuse, write nothing | `ConfirmationError`; series unchanged; zero snapshots | `tests/integration/test_library_series_rename.py:193-197` — `pytest.raises(ConfirmationError)`, `get_book(b1).series=="Old"`, `_snapshots==[]` | ✅ PASS |
| SRENAME-06: one book fails → `failed[]`, others applied, batch not aborted | applied={b1}, failed={b2}, sum==2 | `tests/integration/test_library_series_rename.py:223-227` — `applied_ids=={b1}`, `failed_ids=={b2}`, `len(applied)+len(failed)==2`, `get_book(b2).series=="Old"` | ✅ PASS |
| SRENAME-07 (index preserved): book at index X → after rename series=`New`, index=X (exact) | index unchanged at exact `2.0`/`7.5` | `tests/integration/test_library_series_rename.py:175-181` — `by_id[b2]=={"book_id":b2,"series":"New","series_index":7.5}`, `get_book(b2).series_index==7.5`; e2e `tests/e2e/test_server.py:521,527` — `series_index==7.5` | ✅ PASS |
| SRENAME-07 (merge-onto-existing): `new_series` already exists → merge allowed, each keeps own index, no renumber | b1→New/3.0, existing b2 untouched New/1.0; re-run rejected | `tests/integration/test_library_series_rename.py:291-298` — `by_id[b1]=={...3.0}`, `get_book(b2).series_index==1.0`, re-run `pytest.raises(InvalidInputError)` | ✅ PASS |
| SRENAME-08: applied book re-read → real `series` + `series_index` in report | exact re-read dicts | `tests/integration/test_library_series_rename.py:175-176`, `:242-244` — applied entries equal exact `{book_id,series,series_index}` dicts | ✅ PASS |

**Status**: ✅ All 8 ACs covered with spec-anchored, exact-value assertions. SRENAME-07's index assertion targets the exact literal (`7.5`/`2.0`/`3.0`), not merely "series changed".

---

## Discrimination Sensor

| Mutation | File:line | Description | Killed? |
| -------- | --------- | ----------- | ------- |
| 1 | `src/calibre_mcp/library.py:666` | Added `series_index: 1.0` to the write payload (the exact index-clobber regression the design guards against) | ✅ Killed — `test_apply_writes_new_series_backs_up_once_and_preserves_index` failed (`series_index 1.0 != 2.0`) |
| 2 | `src/calibre_mcp/sqlite_reader.py` | Reversed discovery sort `ORDER BY l.book` → `... DESC` | ✅ Killed — `test_books_by_series_finds_every_book_ascending_sorted` failed (`[2,1] != [1,2]`) |
| 3 | `src/calibre_mcp/library.py:676` | Swapped failure bucket `failed.append` → `applied.append` | ✅ Killed — `test_apply_one_book_failure_reports_failed_others_still_renamed` failed (`{1,2} != {1}`) |

**Sensor depth**: lightweight (3 targeted behavior-level mutations on the highest-risk new code).
**Result**: 3/3 killed — PASS ✅. All mutations run in scratch state; working tree restored via `git checkout` (verified `git status` clean).

---

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum code (no features beyond asked) | ✅ |
| Surgical changes (only 3 src files: reader, facade, server) | ✅ |
| No scope creep / no single-use abstraction | ✅ (no resolver added — correct for single-valued field) |
| Matches sibling patterns (`rename_tag`/`rename_author`) | ✅ |
| Spec-anchored outcome check (asserted values match spec) | ✅ |
| Per-layer Coverage Expectation (reader integration; facade 1:1 ACs; e2e happy+error) | ✅ |
| Every test maps to a spec requirement — no unclaimed tests | ✅ (13 tests → SRENAME-01..08 + listed edge cases + L-001) |
| Documented guidelines followed | ✅ ruff + `mypy --strict` clean; pytest markers per `pyproject.toml` |

---

## Edge Cases

- [x] Exactly one book in `old_series` runs full plan→confirm path — `test_single_book_batch_runs_full_plan_confirm_path:230`.
- [x] `old_series` matches no book → rejected before backup (not empty success) — `test_plan_rejects_series_not_found_before_backup:127`.
- [x] Fractional/large index (`7.5`) survives the rename — `test_apply_writes...preserves_index:181`.
- [x] Affected set changes between plan and apply → token mismatch refused — mechanism covered by `test_apply_token_mismatch_refuses_and_writes_nothing:186` (verify() over the recomputed `{old,new,book_ids}` payload). Note: an explicitly-mutated-set scenario is not seeded; the guard is the same `verify()` path exercised with a non-matching token.
- [x] One book fails → remaining applied, per-book failure reported — `test_apply_one_book_failure...:200`.
- [x] Ascending `book_id` processing order — reader returns sorted ids (`test_books_by_series_finds_every_book_ascending_sorted`); facade iterates the sorted list.
- [~] `new_series` differs from `old_series` only by case → valid rename (not a no-op). Correct by construction (Python `!=` is case-sensitive; SQLite `s.name = ?` default BINARY collation), but NOT covered by a dedicated assertion. Minor coverage gap — does not map to any numbered SRENAME requirement and does not block Verified.

---

## Gate Check

- **Gate command**: `unset VIRTUAL_ENV && uv run ruff check src tests && uv run mypy src && uv run pytest`
- **Result**: ruff `All checks passed!`; mypy `Success: no issues found in 16 source files`; pytest `307 passed in 472.64s`.
- **Test count before feature**: 294 (307 − 13 new)
- **Test count after feature**: 307
- **Delta**: +13 (2 reader + 9 facade + 2 e2e)
- **Skipped tests**: 0
- **Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| ----------- | --------------- | ---------- |
| SRENAME-01 | Implementing | ✅ Verified |
| SRENAME-02 | Implementing | ✅ Verified |
| SRENAME-03 | Implementing | ✅ Verified |
| SRENAME-04 | Implementing | ✅ Verified |
| SRENAME-05 | Implementing | ✅ Verified |
| SRENAME-06 | Implementing | ✅ Verified |
| SRENAME-07 | Implementing | ✅ Verified |
| SRENAME-08 | Implementing | ✅ Verified |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 8/8 ACs matched spec outcome (0 spec-precision gaps on numbered requirements)
**Sensor**: 3/3 mutations killed
**Gate**: 307 passed, 0 failed, 0 skipped

**What works**: Plan→confirm gate with one deterministic batch token; exact-match discovery; series-not-found and blank/no-op rejection before any backup; one `metadata.db` backup before the loop (order-guarded); best-effort per-book apply with honest `applied`/`failed`; and — the feature's raison d'être — `series_index` preservation, proven against exact fractional values (`7.5`) end-to-end through the FastMCP tool surface. The index-clobber regression is empirically caught by the sensor.

**Issues found**: One minor, non-blocking coverage gap — the "case-only difference is a valid rename" edge case is correct by construction but lacks a dedicated test assertion.

**Next steps**: None required for PASS. Optionally add a one-line test asserting a case-only rename (`"old"`→`"Old"`) applies rather than being treated as a no-op, to close the last listed edge case.
