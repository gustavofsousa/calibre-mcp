# Rename a Tag Across the Library (ORGN-02) Validation

**Date**: 2026-07-31
**Spec**: `.specs/features/tag-rename/spec.md`
**Diff range**: `8527cc4..617e122` (5 feature commits: T1 `7a4f3d3` → T5 `617e122`)
**Verifier**: ⚠️ **self-run inline** (standalone `validate.md` fallback), NOT an independent
sub-agent. The author and verifier are the same context here — a weaker independence guarantee than
ORGN-01's separate-agent verifier. Mitigation: the discrimination sensor (below) is the objective
check that the tests actually kill behavior faults, which does not depend on verifier independence.

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 `resolve_renamed_values` + author alias | ✅ Done | `rename_resolve.py:20`; `author_rename.py` re-exports; 8 unit tests `test_rename_resolve.py` |
| T2 `books_by_tag` | ✅ Done | `sqlite_reader.py:157`; 3 tests `test_sqlite_reader.py` (`Poetry`→`[9,15,17,19]`) |
| T3 `CalibreLibrary.rename_tag` | ✅ Done | `library.py:490`; 9 tests `test_library_tag_rename.py` |
| T4 `rename_tag` tool | ✅ Done | `server.py:258`; 2 e2e tests `test_server.py` |
| T5 traceability closeout | ✅ Done | spec left at `Implementing` (Verifier flips to Verified); STATE note deferred (file already dirty with unrelated work) |

Re-verified against actual code/tests, not the `[ ]` marks. All present and behaving.

---

## Spec-Anchored Acceptance Criteria

### P1: Rename a tag everywhere via one reviewed call

| Criterion (WHEN X THEN Y) | Spec-defined outcome | test + assertion | Result |
| --- | --- | --- | --- |
| TRENAME-01 plan (no token): discover exact-match books, per-book resolved diff, one token, write nothing | plan lists exactly affected books, `proposed` other-tag-safe, token present, nothing written | `test_library_tag_rename.py` `test_plan_lists_affected_books...` — `status=="plan"`, `set(by_id)=={b1,b2}`, `set(by_id[b2]...proposed)=={"new-tag","keep"}`, token truthy, re-reads unchanged | ✅ PASS |
| TRENAME-02 old_tag matches no tag → reject before backup | `InvalidInputError("tag not found")`, no backup | `test_plan_rejects_tag_not_found_before_backup` — raises, `"not found" in msg`, `_snapshots==[]` | ✅ PASS |
| TRENAME-03 blank new_tag or new_tag==old_tag → reject before backup | `InvalidInputError`, no backup | `test_new_tag_blank_or_equal_to_old...` — raises for `""`, `"   "`, `"old-tag"`; `_snapshots==[]` | ✅ PASS |
| TRENAME-04 apply (matching token): one backup before first write, apply via set_metadata, return backup | exactly one backup, resolved sets applied, backup path returned | `test_apply_writes_resolved_tags...` — `status=="renamed"`, resolved tag sets read back, `len(_snapshots)==1`; order asserted separately in `test_backup_failure_aborts_before_any_set_metadata_write` | ✅ PASS |
| TRENAME-05 token mismatch → refuse, write nothing | `ConfirmationError`, nothing written/backed up | `test_apply_token_mismatch_refuses...` — raises `ConfirmationError`, book unchanged, `_snapshots==[]` | ✅ PASS |
| TRENAME-06 one book fails → applied/failed reported, batch continues | per-book failed entry, others applied, invariant holds | `test_apply_one_book_failure...` — `applied_ids=={b1}`, `failed_ids=={b2}`, `len(applied)+len(failed)==2`, b2 unchanged | ✅ PASS |
| TRENAME-08 applied book re-read → real tags in report | applied[] carries re-read tags | `test_apply_writes...` + e2e `test_rename_tag_plan_then_apply_round_trip` — `applied==[{book_id,tags:["new-tag"]}]` (value from re-read) | ✅ PASS |

### P1: Other-tag-safe replacement & merge

| Criterion (WHEN X THEN Y) | Spec-defined outcome | test + assertion | Result |
| --- | --- | --- | --- |
| TRENAME-07 AC1 replace only old, preserve other tags | `["a","old","b"]` → set `{"a","new","b"}` | `test_rename_resolve.py` `test_other_value_preserved...` (`==["a","new","b"]`); end-to-end `test_apply_writes...` (`{"new-tag","keep"}`) | ✅ PASS |
| TRENAME-07 AC2 book carrying both → single new, dedupe | `["old","new"]→["new"]`; `["new","old"]→["new"]` | `test_rename_resolve.py` merge tests; integration `test_merge_onto_existing_tag...` (`b1→{"new"}`, `b2→{"x","new"}`) | ✅ PASS |
| TRENAME-07 AC3 merge onto existing tag still applies | rename applies, consolidates | `test_merge_onto_existing_tag...` — apply succeeds, then re-run raises `InvalidInputError` (old fully consumed) | ✅ PASS |

**Status**: ✅ All 8 TRENAME ACs covered with assertions targeting the spec-defined values.

---

## Edge Cases

- [x] Exactly one book carries old_tag → full plan→confirm path — `test_single_book_batch_runs_full_plan_confirm_path` (`applied==[{book_id,tags:["renamed"]}]`, one backup).
- [x] old_tag matches no tag → reject before backup — `test_plan_rejects_tag_not_found_before_backup` (TRENAME-02).
- [x] Book lists old_tag more than once → single deduped new — `test_rename_resolve.py` `test_duplicate_old_occurrences_collapse_to_single_new` (`["old","old"]→["new"]`).
- [x] Affected set changes between plan and apply → recomputed token mismatch → refuse — mechanism covered by `test_apply_token_mismatch_refuses...` (wrong token → `ConfirmationError`, identical `verify()` path); merge re-run proves set consumption. ⚠️ The literal "book gained/lost old_tag shifts the recomputed token" scenario is covered transitively, not directly (same observation as ORGN-01).
- [x] One book fails → others still apply, per-book failure — `test_apply_one_book_failure...` (TRENAME-06).
- [x] Processing ascending book_id — `test_books_by_tag_finds_every_book_ascending_sorted` (`Poetry`→`[9,15,17,19]`); facade loops that order.
- [x] Tags as a set / Calibre re-reads alphabetically — apply/re-read assertions use set equality (spec TRENAME-08 note); Mutation C proved other-tag preservation is genuinely tested.
- [~] new_tag differs from old_tag only by case (`"scifi"→"SciFi"`) is a valid rename — NO direct test. Correct by construction (`new_tag == old_tag` is exact-equality at `library.py:517`, so a case variant passes validation). ⚠️ Uncovered-by-assertion but low risk (same as ORGN-01).

---

## Discrimination Sensor

Mutations injected in-place, targeted test run, then `git checkout --` restore; final tree verified
clean at HEAD `617e122` (no leftover mutations; `git diff HEAD -- src tests` empty).

| Mutation | File | Description | Killed? |
| --- | --- | --- | --- |
| A | `rename_resolve.py` | Removed dedupe guard (`if replacement not in result`) → always append | ✅ Killed — 3 merge/dedupe unit tests failed (`['new','new'] != ['new']`) |
| B | `library.py` | Disabled the empty-discovery reject (`if False:`) → tag-not-found no longer raises | ✅ Killed — `test_plan_rejects_tag_not_found_before_backup` failed (`DID NOT RAISE`) |
| C | `library.py` | `set_metadata(..., {"tags": resolved})` → `{"tags": [new_tag]}` (overwrite, drop other tags) | ✅ Killed — `test_apply_writes_resolved_tags...` failed (`{'new-tag'} != {'keep','new-tag'}`) |

**Sensor depth**: lightweight (3 behavior-level mutations on the highest-risk new surfaces: shared
resolve algebra, the not-found gate, and the other-tag-safe write).
**Result**: 3/3 killed — PASS ✅

---

## Payload / Conjunction Rule

`applied[]`, `failed[]`, `diffs[]` are asserted on value/set, not just presence:
- `applied == [{"book_id": old_id, "tags": ["new-tag"]}]` (e2e) — full dict equality on the re-read payload (TRENAME-08).
- `set(diffs[...]["diff"]["tags"]["proposed"]) == {"new-tag","keep"}` (facade plan test).
- `failed_ids == {b2}` with invariant `len(applied)+len(failed)==2`.
No call-was-made-only assertions found. Set equality (not positional) is used deliberately for tags.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code / no scope creep | ✅ 3 small new surfaces + 1 pure-fn generalization; no serialization fix needed (AD-022 already correct for tags) |
| Surgical changes, only required files | ✅ `rename_resolve.py`, `author_rename.py`, `sqlite_reader.py`, `library.py`, `server.py` + tests |
| No single-use abstractions | ✅ shared resolver removes duplication rather than adding it (AGENTS.md rule) |
| Matches existing patterns (AD-020/AD-012 siblings) | ✅ structural twin of `rename_author` |
| ORGN-01 untouched behaviorally | ✅ alias re-export; ORGN-01's 7 unit tests still green; author paths in full suite green |
| Spec-anchored outcome check | ✅ asserted values match spec |
| Documented guidelines followed | ✅ `pyproject.toml` markers, `ruff`, `mypy --strict`, scratch_library-only writes (test-safety) |

---

## Gate Check

- **Gate command**: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- **Result**: ruff — All checks passed; mypy — Success, no issues in 16 files; pytest — **280 passed, 0 failed, 0 skipped** in 430s (exit 0)
- **Test count before feature**: 258 (ORGN-01 baseline)
- **Test count after feature**: 280
- **Delta**: +22 (8 unit + 3 reader + 9 facade + 2 e2e) — no silent deletions
- **Skipped/Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous | New |
| --- | --- | --- |
| TRENAME-01..08 | Implementing | ✅ Verified (recommend spec flip) |

---

## Summary

**Overall**: ✅ Ready (with the independence caveat noted at the top)

**Spec-anchored check**: 8/8 ACs matched spec outcome; 2 minor edge-case coverage observations
(case-only rename not directly asserted; literal set-change token mismatch covered transitively) —
neither an AC failure, both inherited verbatim from ORGN-01.
**Sensor**: 3/3 mutations killed.
**Gate**: 280 passed, 0 failed.

**What works**: plan→confirm gate, exact-match tag discovery, other-tag-safe swap + in-book
dedupe/merge, one backup before first write (order-tested), honest applied/failed, set-semantics
re-read. No serialization fix required — tags already join with `,` (AD-022), so ORGN-02 is pure
reuse of the corrected primitive.

**Issues found**: none blocking.
- ⚠️ Process: verifier was self-run, not an independent agent (no-spawn constraint). Recommend a
  fresh-eyes pass if an independent verifier is desired before marking Verified.
- Two low-risk edge-case assertion gaps (above), identical to ORGN-01's accepted gaps.

**Next steps**: flip TRENAME-01..08 to Verified in spec.md (after any desired independent pass);
optionally add a direct case-only-rename test and a stale-set token-mismatch test.

---

## Independent Verifier Confirmation (2026-07-31)

The self-run caveat above was closed: a **separate `verifier` sub-agent** (author ≠ verifier)
independently re-derived coverage with evidence-or-zero and returned **PASS**.

- All 4 tag-rename suites run green against the **real** library (nothing skipped): unit 8, facade
  9, reader 3, e2e 2.
- 8/8 TRENAME ACs covered by tests asserting the spec-defined outcome (set-equality on tag re-reads
  confirmed correct, not a gap).
- Independent discrimination sensor — **4/4 killed**, using targets **disjoint** from this report's
  3: (1) dropped `ORDER BY l.book` in `books_by_tag` → ascending-order test killed it; (2) moved the
  backup after the apply loop → backup-before-write test killed it; (3) removed the `new==old` guard
  → reject test killed it; (4) removed the `verify(...)` token check → token-mismatch test killed it.
  Coverage holds under two independent fault sets (author 3 + verifier 4).
- Non-blocking notes raised (neither an AC failure): case-only-rename edge case correct by
  construction but unasserted; TRENAME-04's returned `backup` path value present but unasserted.
- Working tree confirmed clean of all mutations.

**Combined verdict: ✅ Verified.** TRENAME-01..08 flipped to Verified in spec.md.
