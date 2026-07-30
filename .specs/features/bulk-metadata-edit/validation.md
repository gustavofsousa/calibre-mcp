# Bulk Metadata Edit (BULK-01) Validation

**Date**: 2026-07-20
**Spec**: `.specs/features/bulk-metadata-edit/spec.md`
**Diff range**: `263b03a~1..HEAD`
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status  | Notes                                                                                          |
| ---- | ------- | ------------------------------------------------------------------------------------------------ |
| T1   | ✅ Done | `src/calibre_mcp/bulk_edit.py` + `tests/unit/test_bulk_edit.py` (10 tests)                        |
| T2   | ✅ Done | `CalibreLibrary.update_metadata_bulk` + `_validate_bulk_input`/`_bulk_plan_entry` (18 int. tests) |
| T3   | ✅ Done | `@mcp.tool() update_metadata_bulk` in `server.py` + 6 e2e tests appended to `test_server.py`       |

---

## Spec-Anchored Acceptance Criteria

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| BEDIT-01: plan (no token) returns per-book diff + one token, writes nothing | `status:"plan"`, `diffs[]` with `current→proposed`, `confirmation_token` present, no DB write | `tests/integration/test_library_bulk.py:99-108` — `plan["status"]=="plan"`; `d["diff"]["series"]["proposed"]=="Dune"`; `plan["confirmation_token"]` truthy; `facade.get_book(b1).series is None` | ✅ PASS |
| BEDIT-02: apply (token) backs up once, writes via `set_metadata`, returns backup path | one backup, all books written, `backup` key returned | `tests/integration/test_library_bulk.py:140-147` — `facade.get_book(b1).series == "Dune"`; `len(_snapshots(backup_root)) == 1` | ✅ PASS |
| BEDIT-03: token mismatch refused, writes nothing | `ConfirmationError` raised, no write, no backup | `tests/integration/test_library_bulk.py:157-161` — `pytest.raises(ConfirmationError)`; `facade.get_book(b1).series is None`; `_snapshots(backup_root) == []` | ✅ PASS |
| BEDIT-04: one book fails, rest still apply, honest `applied`/`failed` | `applied_ids=={b1,b2}`, `failed_ids=={999999}`, `len(applied)+len(failed)==len(book_ids)` | `tests/integration/test_library_bulk.py:179-181` — exact set equality + invariant assertion | ✅ PASS |
| BEDIT-05: exactly one backup before first write | one snapshot file for the whole batch | `tests/integration/test_library_bulk.py:147` — `len(_snapshots(backup_root)) == 1` | ✅ PASS |
| BEDIT-06: invalid input rejected pre-write (empty/dup/non-int ids, empty/unknown fields, bad rating, bad `list_mode`, `list_mode` w/o list field) | `InvalidInputError` for every case, before token/backup | `tests/integration/test_library_bulk.py:260-320` — 9 dedicated tests, each `pytest.raises(InvalidInputError)`; `test_invalid_input_rejected_before_any_backup` additionally asserts `_snapshots(backup_root) == []` | ✅ PASS |
| BEDIT-07: applied entries re-read affected fields, not full record | `applied[i]["fields"]` == re-read values for exactly the fields sent | `tests/integration/test_library_bulk.py:142-143` — `by_id[b1]["fields"] == {"series": "Dune"}` | ✅ PASS |
| BEDIT-08 AC1-3: add=union, remove=difference, replace=overwrite; diff shows resolved set | exact list equality per mode | `tests/unit/test_bulk_edit.py:36,50,62` — `apply_list_mode(...) == [...]` exact lists; `tests/integration/test_library_bulk.py:214,230` — plan diff `proposed` asserted exact | ✅ PASS |
| BEDIT-08 AC4: plan diff shows true resolved set (not raw supplied) | `resolve_fields` feeds both diff and write | `tests/unit/test_bulk_edit.py:66-70` (`test_resolve_fields_applies_mode_to_list_field_against_current`) + `tests/integration/test_library_bulk.py:214` (`plan["diffs"][0]["diff"]["tags"]["proposed"] == ["a","b","c"]`) | ✅ PASS |
| BEDIT-09: add of present value / remove of absent value is idempotent no-op, still `applied` | no duplication / no error, book lands in `applied` | `tests/unit/test_bulk_edit.py:42-44` (`test_add_of_only_present_values_is_a_noop`); `tests/integration/test_library_bulk.py:225-237` (`test_remove_mode_ignores_missing_values` — `set(...) == {"b","c"}`, no exception) | ✅ PASS |

**Status**: ✅ All 9 BEDIT ACs covered with exact-outcome assertions — no spec-precision gaps.

---

## Edge Cases (spec.md "Edge Cases" section)

| Edge case | Handled? | `file:line` |
| --- | --- | --- |
| `book_ids` has one id → full plan→confirm path, not an error | ✅ | `tests/integration/test_library_bulk.py:187-200` (`test_single_id_batch_runs_full_plan_confirm_path`) |
| Id absent at plan time → `found:false`, lands in `failed[]` at apply | ✅ | `tests/integration/test_library_bulk.py:112-120` (plan) + `:165-184` (apply, BEDIT-04) |
| `list_mode="remove"` empties a list field → writes `[]` | ✅ | `tests/integration/test_library_bulk.py:241-253` (`test_remove_mode_can_empty_the_list_field` — `applied["applied"][0]["fields"]["tags"] == []`; `facade.get_book(b1).tags == []`) |
| `list_mode` not in `{replace,add,remove}` → rejected pre-write | ✅ | `tests/integration/test_library_bulk.py:299-303` (`test_rejects_invalid_list_mode`) |
| `list_mode` supplied but `fields` has no list field → rejected | ✅ | `tests/integration/test_library_bulk.py:306-311` (`test_rejects_list_mode_without_a_list_field`) |
| Processing order ascending `book_id` | ✅ | `tests/integration/test_library_bulk.py:99-102` (`[d["book_id"] for d in plan["diffs"]] == [b1, b2]` for input `[b2, b1]`) — killed by mutant 3 below, confirming discriminating power |
| bool-as-int `book_ids` rejected (BEDIT-06 sub-case) | ✅ | `tests/integration/test_library_bulk.py:278-282` (`test_rejects_bool_as_book_id`) |
| duplicate `book_ids` rejected | ✅ | `tests/integration/test_library_bulk.py:265-269` (`test_rejects_duplicate_book_ids`) |
| non-integer `book_ids` rejected | ✅ | `tests/integration/test_library_bulk.py:272-275` (`test_rejects_non_integer_book_id`) |

**Status**: ✅ All listed edge cases covered.

---

## Discrimination Sensor

| Mutation | File:line | Description | Killed? |
| --- | --- | --- | --- |
| 1 | `src/calibre_mcp/bulk_edit.py:35-39` | Swapped `add`/`remove` branch bodies in `apply_list_mode` | ✅ Killed — 7/10 unit tests in `test_bulk_edit.py` failed |
| 2 | `src/calibre_mcp/library.py` (apply loop) | Changed `except CalibreMcpError` → `except KeyError` so a vanished-id `BookNotFoundError` propagates uncaught instead of landing in `failed[]` | ✅ Killed — `test_apply_one_vanished_id_reports_failed_others_still_applied` failed (uncaught `BookNotFoundError`) |
| 3 | `src/calibre_mcp/library.py` (`update_metadata_bulk`) | Replaced `ordered_ids = sorted(book_ids)` with `ordered_ids = list(book_ids)` (broke ascending-order guarantee) | ✅ Killed — `test_plan_returns_per_book_diff_and_token_without_writing` failed (`[2,1] != [1,2]`) |

All mutations applied to the working tree individually, tests run, mutant confirmed killed, then `git checkout --` used to restore the exact original content before the next mutation (verified via `git diff --stat` showing no diff after each restore).

**Sensor depth**: lightweight (3 targeted mutations, default tier)
**Result**: 3/3 killed — PASS ✅

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code (no features beyond spec) | ✅ — no per-book field maps, no all-or-nothing rollback, no bulk convert; matches Out-of-Scope table |
| Surgical changes (only touched files required) | ✅ — `bulk_edit.py` (new), `library.py`, `server.py`, plus their test files only |
| No scope creep | ✅ |
| Matches existing patterns | ✅ — reuses `plan_token`/`verify`, `backup_metadata_db`, `_validate_edit_fields`, `_build_diff`, `_map_errors`, `_jsonify` unchanged; new code mirrors `update_metadata`'s shape |
| Spec-anchored outcome check (asserted values match spec) | ✅ — see AC table above, all exact-value assertions |
| Per-layer Coverage Expectation met | ✅ — unit: all `apply_list_mode`/`resolve_fields` branches; integration: all BEDIT-01..09 + every edge case; e2e: plan→apply round trip, partial failure, invalid input → ToolError, docstring contract, stdout cleanliness |
| Every test maps to a spec AC/edge case/Done-when | ✅ — spot-checked against Test Coverage Matrix in tasks.md; no unclaimed tests observed |
| Documented guidelines followed | ✅ — CLAUDE.md test-safety rule (all writes via `scratch_library`), `.specs/STATE.md` AD-001/AD-005 (reads via `SqliteReader`, writes via `CalibredbRunner` only — confirmed via diff, no new subprocess/SQL path) |

One minor observation (not a defect): `_bulk_plan_entry` and `update_metadata_bulk`'s apply loop both call `resolve_fields` independently per book at plan-time and again at apply-time — acceptable since `metadata.db` may have changed between the two calls (BEDIT-04 vanished-id case depends on re-reading at apply time), and the design doc explicitly names this as the single-source-of-truth pattern for both diff and write, not a shared cache. No fix needed.

---

## Gate Check

- **Gate command**: `uv run ruff check . && uv run pytest -q`
- **Result**: ruff — all checks passed; pytest — 189 passed, 0 failed, 0 skipped (232.64s)
- **Test count before feature** (263b03a~1): 155 (189 total − 34 new: 10 unit + 18 integration + 6 e2e)
- **Test count after feature**: 189
- **Delta**: +34 new tests
- **Skipped tests**: none
- **Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status  |
| --- | --- | --- |
| BEDIT-01 | In Design | ✅ Verified |
| BEDIT-02 | In Design | ✅ Verified |
| BEDIT-03 | In Design | ✅ Verified |
| BEDIT-04 | In Design | ✅ Verified |
| BEDIT-05 | In Design | ✅ Verified |
| BEDIT-06 | In Design | ✅ Verified |
| BEDIT-07 | In Design | ✅ Verified |
| BEDIT-08 | In Design | ✅ Verified |
| BEDIT-09 | In Design | ✅ Verified |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 9/9 ACs matched spec-defined outcome (0 spec-precision gaps)
**Sensor**: 3/3 mutations killed
**Gate**: 189 passed, 0 failed

**What works**: Full plan→confirm→apply handshake with one batch token reused from the Verified `confirmation.py`; honest partial-failure (`applied`/`failed` invariant); one backup per batch before any write; `add`/`remove`/`replace` list-mode set algebra isolated as pure, unit-tested functions feeding both the diff and the write; every BEDIT-06 invalid-input branch and every spec-listed edge case has a dedicated test with an exact-value assertion; discrimination sensor confirms the tests genuinely detect regressions in the three highest-risk code paths (list-mode algebra, partial-failure catch scope, ordering guarantee).

**Issues found**: none.

**Next steps**: none — feature ready to merge as-is.
