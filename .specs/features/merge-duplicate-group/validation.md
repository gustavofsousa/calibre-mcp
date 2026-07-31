# Merge a Duplicate Group (ORGN-03) Validation

**Date**: 2026-07-31
**Spec**: `.specs/features/merge-duplicate-group/spec.md`
**Diff range**: `5365d59..135c39b` (4 feature commits: T1 `8677f3a` → T4 `135c39b`)
**Verifier**: ⚠️ **self-run inline** (standalone `validate.md` fallback), NOT an independent
sub-agent — same caveat as ORGN-02's first pass. Recommend an independent `verifier` sub-agent pass
before treating TRENAME-style `Verified` status as final (as was done for ORGN-02).

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 `plan_loser_formats` | ✅ Done | `library.py:84`; 4 unit tests `test_merge_duplicate_group.py` |
| T2 `CalibreLibrary.merge_duplicate_group` | ✅ Done | `library.py:594`; 8 integration tests `test_library_merge_duplicate_group.py` |
| T3 `merge_duplicate_group` tool | ✅ Done | `server.py:359`; 2 e2e tests `test_server.py` |
| T4 traceability closeout | ✅ Done | spec left at `Implementing`; full gate green (294 passed) |

Re-verified against actual code/tests, not the `[ ]` marks. All present and behaving.

---

## Spec-Anchored Acceptance Criteria

### P1: Merge a duplicate group in one reviewed call

| Criterion (WHEN X THEN Y) | Spec-defined outcome | test + assertion | Result |
| --- | --- | --- | --- |
| MERGE-01 plan (no token): per-loser format split, one token, write nothing | plan lists `formats_to_add`/`formats_already_present` per loser, token present, nothing written | `test_plan_lists_per_loser_format_split_without_writing` — `entry["formats_to_add"]==["PDF"]`, `formats_already_present==["EPUB"]`, token truthy, loser still present, survivor formats unchanged | ✅ PASS |
| MERGE-02 survivor or loser id not found → reject before backup | `BookNotFoundError`, no backup | `test_plan_rejects_unknown_survivor_or_loser_before_backup` — raises for both cases, `_snapshots==[]` | ✅ PASS |
| MERGE-03 empty/self/duplicate `loser_ids` → reject before backup | `InvalidInputError`, no backup | `test_plan_rejects_invalid_loser_ids_before_backup` — raises for all 3 cases, `_snapshots==[]` | ✅ PASS |
| MERGE-04 apply (matching token): one backup before first mutation, attach then recoverable-remove, return backup | exactly one backup, formats unioned, losers removed | `test_apply_unions_formats_backs_up_once_and_removes_losers` — `status=="merged"`, `survivor_formats=={"EPUB","PDF"}`, `len(_snapshots)==1`; order asserted separately in `test_backup_failure_aborts_before_any_mutation` | ✅ PASS |
| MERGE-05 token mismatch → refuse, write nothing | `ConfirmationError`, nothing written/backed up | `test_apply_token_mismatch_refuses_and_writes_nothing` — raises, loser still present, `_snapshots==[]` | ✅ PASS |
| MERGE-06 attach fails → loser NOT removed, `failed[]`, batch continues | per-loser failed entry, other loser still merges, invariant holds | `test_apply_attach_failure_keeps_loser_others_still_merge` — `merged_ids=={loser_ok}`, `failed_ids=={loser_bad}`, `len+len==2`, `loser_bad` still present | ✅ PASS |
| MERGE-07 format already on survivor not duplicated, reported | overlap not attached, reported as already-present | `test_plan_lists_per_loser_format_split_without_writing` (`formats_already_present==["EPUB"]`) + `test_apply_unions_formats_backs_up_once_and_removes_losers` (`formats_added==["PDF"]` only, EPUB not re-added) | ✅ PASS |
| MERGE-08 re-read survivor formats; loser trash location returned | union in `survivor_formats`, `trash_location` present and real | `test_apply_unions_formats_backs_up_once_and_removes_losers` — `trash_dir.is_dir() and any(trash_dir.iterdir())` | ✅ PASS |

**Status**: ✅ All 8 MERGE ACs covered with assertions targeting the spec-defined values.

---

## Edge Cases

- [x] Single-loser batch → full plan→confirm path — `test_single_loser_batch_runs_full_plan_confirm_path` (merged, backup taken once).
- [x] A loser with no formats → nothing attached, still removed — NOT directly tested (both seeded losers in this suite have ≥1 format). ⚠️ Coverage gap: no test seeds a zero-format loser.
- [x] All of a loser's formats already on the survivor → nothing attached, still removed — implicitly covered by `formats_already_present` assertions, but no test asserts the *removal* outcome for an all-overlap loser specifically. ⚠️ Minor coverage gap.
- [x] One loser fails, another succeeds → per-loser outcome — `test_apply_attach_failure_keeps_loser_others_still_merge` (MERGE-06).
- [x] Group changes between plan and apply → token mismatch → refuse — mechanism covered by `test_apply_token_mismatch_refuses_and_writes_nothing` (wrong token → same `verify()` path); the literal "loser set changed" scenario is covered transitively, not directly (same pattern as ORGN-01/02's accepted gap).
- [x] Ascending `loser_id` processing order — implicit in the two-loser test (`loser_ok < loser_bad`, `loser_ok` processed and merged); no test asserts order for a 3+ loser batch.

---

## Discrimination Sensor

Mutations injected in-place, targeted test run, then `git checkout --` restore; final tree verified
clean (`git status --short` / `git diff HEAD -- src tests` empty — only pre-existing unrelated dirty
files remain).

| Mutation | File | Description | Killed? |
| --- | --- | --- | --- |
| A | `library.py` | On attach failure, remove the loser anyway (broke MERGE-06's data-safety ordering) | ✅ Killed — `test_apply_attach_failure_keeps_loser_others_still_merge` failed (`facade.get_book(loser_bad)` raised `BookNotFoundError` — the loser was wrongly gone) |
| B | `library.py` | Disabled the `survivor_id in loser_ids` guard (`if False:`) | ✅ Killed — `test_plan_rejects_invalid_loser_ids_before_backup` failed (`DID NOT RAISE`) |
| C | `library.py` | Removed the `if fmt not in survivor_formats:` conflict check — always attach every format regardless of overlap | ✅ Killed — `test_apply_unions_formats_backs_up_once_and_removes_losers` failed (`survivor_formats` diverged from the expected `{"EPUB","PDF"}` union — corrupted the merge) |

**Sensor depth**: lightweight (3 behavior-level mutations on the highest-risk new surfaces: the
attach-before-delete data-safety invariant, the self-referential-loser guard, and the
format-conflict/survivor-wins rule).
**Result**: 3/3 killed — PASS ✅

---

## Payload / Conjunction Rule

`merged[]`, `failed[]`, `losers[]` (plan) are asserted on value, not just presence:
- `result["merged"] == [{"loser_id": ..., "formats_added": ["PDF"], "trash_location": ...}]` — full dict equality (MERGE-08).
- `set(result["survivor_formats"]) == {"EPUB", "PDF"}` — the proven union, not just non-empty.
- `merged_ids == {loser_ok}` / `failed_ids == {loser_bad}` with invariant `len+len==2`.
No call-was-made-only assertions found.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code / no scope creep | ✅ 1 pure helper + 1 facade method + 1 tool; no new mutation primitive (reuses `add_format`, `trash_book_files`, `remove`, all Verified) |
| Surgical changes, only required files | ✅ `library.py`, `server.py` + tests |
| No single-use abstractions | ✅ `plan_loser_formats` mirrors the existing small-pure-helper style |
| Matches existing patterns (AD-020/AD-012, REM-01..05's recoverable-delete) | ✅ structural reuse, not a new pattern |
| Data-safety invariant (attach-before-delete) explicit and tested | ✅ Mutation A proves it's load-bearing |
| Spec-anchored outcome check | ✅ asserted values match spec |
| Documented guidelines followed | ✅ `pyproject.toml` markers, `ruff`, `mypy --strict`, scratch_library-only writes (test-safety) |

---

## Gate Check

- **Gate command**: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- **Result**: ruff — All checks passed; mypy — Success, no issues in 16 files; pytest — **294 passed, 0 failed, 0 skipped** in 448s (exit 0)
- **Test count before feature**: 280 (ORGN-02 baseline)
- **Test count after feature**: 294
- **Delta**: +14 (4 unit + 8 integration + 2 e2e) — no silent deletions
- **Skipped/Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous | New |
| --- | --- | --- |
| MERGE-01..08 | Implementing | Recommend independent Verifier pass before flipping to Verified |

---

## Summary

**Overall**: ✅ Ready for independent verification (self-check clean; not yet independently confirmed)

**Spec-anchored check**: 8/8 ACs matched spec outcome; 3 minor edge-case coverage observations
(zero-format loser not directly tested; all-overlap loser removal outcome not directly tested;
literal stale-token-after-group-change scenario covered transitively) — none is an AC failure.
**Sensor**: 3/3 mutations killed, targeting the data-safety ordering, the self-reference guard, and
the format-conflict rule — the three riskiest new invariants in this feature.
**Gate**: 294 passed, 0 failed.

**What works**: plan→confirm gate, caller-chosen survivor, formats-only scope (survivor metadata
untouched), attach-before-delete data safety (a loser is never deleted while one of its formats is
unconfirmed on the survivor — proven by Mutation A), survivor-wins on format conflict (Mutation C),
recoverable per-loser delete (trash + recycle bin), one batch backup, honest merged/failed. No new
mutation primitive — pure orchestration over three already-Verified primitives.

**Issues found**: none blocking.
- ⚠️ Process: verifier was self-run, not an independent agent. Same recommendation as ORGN-02:
  dispatch an independent `verifier` sub-agent before treating this as final.
- Three low-risk edge-case assertion gaps (above) — could add a zero-format-loser test and an
  all-overlap-loser-still-removed test to close them.

**Next steps**: dispatch an independent Verifier; on PASS, flip MERGE-01..08 to Verified in spec.md.
