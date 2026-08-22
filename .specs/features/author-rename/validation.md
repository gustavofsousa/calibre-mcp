# Rename an Author Across the Library (ORGN-01) Validation

**Date**: 2026-07-30
**Spec**: `.specs/features/author-rename/spec.md`
**Diff range**: `297b1e0~1..7dbc235` (7 feature commits; `c3f43f1` docs excluded as out-of-scope)
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 `set_metadata` ` & ` join | ✅ Done | `calibredb_runner.py:109` field-specific separator; test `test_calibredb_runner.py:107` |
| T2 `resolve_renamed_authors` | ✅ Done | `author_rename.py:13`; 7 unit tests `test_author_rename.py` |
| T3 `books_by_author` | ✅ Done | `sqlite_reader.py:137`; 3 tests `test_sqlite_reader.py:89/98/107` |
| T4 `CalibreLibrary.rename_author` | ✅ Done | `library.py:401`; 9 tests `test_library_author_rename.py` |
| T5 `rename_author` tool | ✅ Done | `server.py:221`; 2 e2e tests `test_server.py:378/408` |
| T6 AD-022 + traceability | ✅ Done | AD-022 in STATE.md; spec left at `Implementing` (Verifier flips to Verified) |

Re-verified against actual code/tests, not the `[x]` marks. All present and behaving.

---

## Spec-Anchored Acceptance Criteria

### P1: Rename an author everywhere via one reviewed call

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| ARENAME-01 plan (no token): discover exact-match books, per-book resolved diff, one token, write nothing | plan lists exactly affected books, `proposed` co-author-safe, token present, nothing written | `test_library_author_rename.py:100-109` — `status=="plan"`, `set(by_id)=={b1,b2}`, `by_id[b2]...proposed==["New Name","Co Author"]`, `confirmation_token` truthy, re-reads unchanged | ✅ PASS |
| ARENAME-02 old_name matches no author → reject before backup | `InvalidInputError("author not found")`, no backup | `test_library_author_rename.py:115-119` — raises `InvalidInputError`, `"not found" in msg`, `_snapshots(backup_root)==[]` | ✅ PASS |
| ARENAME-03 blank new_name or new_name==old_name → reject before backup | `InvalidInputError`, no backup | `test_library_author_rename.py:129-135` — raises for `""`, `"   "`, `"Old Name"`; `_snapshots==[]` | ✅ PASS |
| ARENAME-04 apply (matching token): one backup before first write, apply via set_metadata, return backup | exactly one backup, resolved lists applied, backup path returned | `test_library_author_rename.py:155-163` — `status=="renamed"`, resolved authors read back, `len(_snapshots)==1`; order asserted separately at `:228-249` | ✅ PASS |
| ARENAME-05 token mismatch → refuse, write nothing | `ConfirmationError`, nothing written/backed up | `test_library_author_rename.py:173-177` — raises `ConfirmationError`, book unchanged, `_snapshots==[]` | ✅ PASS |
| ARENAME-06 one book fails → applied/failed reported, batch continues, no false all-succeeded | per-book failed entry, others applied, invariant holds | `test_library_author_rename.py:201-207` — `applied_ids=={b1}`, `failed_ids=={b2}`, `len(applied)+len(failed)==2`, b2 unchanged | ✅ PASS |
| ARENAME-08 applied book re-read → real authors in report | applied[] carries re-read authors | `test_library_author_rename.py:156-158` + `test_server.py:401` — `applied==[{book_id,authors:["New Name"]}]` (value from re-read) | ✅ PASS |

### P1: Co-author-safe replacement & merge

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| ARENAME-07 AC1 replace only old, preserve co-authors + order | `["A","Old","B"]→["A","New","B"]` | `test_author_rename.py:32-36` — `==["A","New","B"]`; end-to-end `test_library_author_rename.py:158` | ✅ PASS |
| ARENAME-07 AC2 book crediting both → single new, dedupe order-preserving | `["Old","New"]→["New"]`; `["New","Old"]→["New"]` | `test_author_rename.py:48`, `:54`; integration `test_library_author_rename.py:269-272` (`b1→["New"]`, `b2→["X","New"]`) | ✅ PASS |
| ARENAME-07 AC3 merge onto existing name still applies (not rejected) | rename applies, consolidates | `test_library_author_rename.py:266-275` — apply succeeds, then re-run raises `InvalidInputError` (old fully consumed) | ✅ PASS |

**Status**: ✅ All 8 ARENAME ACs covered with assertions targeting the spec-defined values.

---

## Edge Cases

- [x] Exactly one book credited → full plan→confirm path — `test_library_author_rename.py:210-224` (`applied==[{book_id,authors:["Renamed Author"]}]`, one backup).
- [x] old_name matches no author → reject before scan/backup — `test_library_author_rename.py:113` (ARENAME-02).
- [x] Book lists old_name more than once → single deduped new — `test_author_rename.py:61` (`["Old","Old"]→["New"]`).
- [x] Affected set changes between plan and apply → recomputed token mismatch → refuse — mechanism covered by `test_library_author_rename.py:167` (wrong token → `ConfirmationError`, identical `verify()` path); merge re-run at `:274` proves set consumption. ⚠️ The literal "book added/removed shifts the recomputed token" scenario is not reproduced with a stale-but-valid token; covered transitively, not directly.
- [x] One book fails → others still apply, per-book failure — `test_library_author_rename.py:181` (ARENAME-06).
- [x] Processing ascending book_id — `test_sqlite_reader.py:89` (`books_by_author` returns `[1,2,4,5]` ascending); facade loops that order.
- [~] new_name differs from old_name only by case (`"old"→"Old"`) is a valid rename, not a no-op — NO direct test. Correct by construction (`new_name == old_name` is exact-equality at `library.py:425`, so a case variant passes validation). ⚠️ Uncovered-by-assertion but low risk.

---

## Discrimination Sensor

Mutations injected in-place, covering tests run, then `git checkout --` restore; final tree verified clean at HEAD `7dbc235`.

| Mutation | File:line | Description | Killed? |
| --- | --- | --- | --- |
| 1 | `author_rename.py:26-27` | Removed dedupe guard (`if replacement not in result`) → always append | ✅ Killed — 3 merge/dedupe unit tests failed |
| 2 | `library.py:462` | `set_metadata(..., {"authors": resolved})` → `{"authors": [new_name]}` (overwrite, drop co-authors) | ✅ Killed — 2 facade tests failed (co-author + merge) |
| 3 | `calibredb_runner.py:109` | Force `separator = ","` (AD-022 regression) | ✅ Killed — `test_set_metadata_authors_stay_distinct_not_mashed` failed; read back `"Author One\|Author Two"` (empirical AD-022 proof) |

**Sensor depth**: lightweight (3 behavior-level mutations on highest-risk new code: pure resolve algebra, facade co-author-safe write, author serialization).
**Result**: 3/3 killed — PASS ✅

---

## Payload / Conjunction Rule

`applied[]`, `failed[]`, `diffs[]` are asserted on value, not just presence:
- `applied == [{"book_id": old_id, "authors": ["New Name"]}]` (`test_server.py:401`) — full dict equality on the re-read payload (ARENAME-08).
- `diffs[...]["diff"]["authors"]["proposed"] == ["New Name", "Co Author"]` (`test_library_author_rename.py:104`).
- `failed_ids == {b2}` with invariant `len(applied)+len(failed)==2` (`:203-205`).
No call-was-made-only assertions found.

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code / no scope creep | ✅ 4 small new surfaces + 1 corrective fix, matching design |
| Surgical changes, only required files | ✅ |
| No single-use abstractions | ✅ pure module mirrors `bulk_edit.py` |
| Matches existing patterns (AD-020/AD-012 siblings) | ✅ |
| Spec-anchored outcome check (asserted values match spec) | ✅ |
| Per-layer coverage (domain 1:1; facade all branches; e2e happy+error) | ✅ |
| Every test maps to an AC / edge case / Done-when | ✅ no unclaimed tests |
| Documented guidelines followed | ✅ `pyproject.toml` markers, `ruff`, `mypy --strict`, `.specs/STATE.md` test-safety (scratch_library only) |

---

## Gate Check

- **Gate command**: `uv run ruff check src tests && uv run mypy src && uv run pytest`
- **Result**: ruff — All checks passed; mypy — Success, no issues in 15 files; pytest — **258 passed, 0 failed, 0 skipped** in 457s (exit 0)
- **Test count before feature**: 137 (baseline per tasks.md)
- **Test count after feature**: 258
- **Delta**: +121 total on branch; +21 attributable to this feature (7 unit + 3 reader + 1 runner + 9 facade + 2 e2e = 22 new test funcs, net suite delta per feature commits) — no silent deletions
- **Skipped**: none
- **Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous | New |
| --- | --- | --- |
| ARENAME-01..08 | Implementing | ✅ Verified (recommend spec flip) |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 8/8 ACs matched spec outcome; 2 minor edge-case coverage observations (case-only rename not directly asserted; literal set-change token mismatch covered transitively) — neither an AC failure.
**Sensor**: 3/3 mutations killed.
**Gate**: 258 passed, 0 failed.

**What works**: plan→confirm gate, exact-match discovery, co-author-safe swap + in-book dedupe/merge, one backup before first write (order-tested), honest applied/failed, author ` & ` serialization (AD-022) empirically proven.

**Issues found**: none blocking. Two low-risk edge-case assertion gaps (above).

**Next steps**: flip ARENAME-01..08 to Verified in spec.md; optionally add a direct case-only-rename test and a stale-set token-mismatch test to close the two edge-case observations.
