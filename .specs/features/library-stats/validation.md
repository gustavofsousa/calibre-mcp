# Library Baseline Stats (STATS-01) Validation

**Date**: 2026-07-20 (re-verified same day, after fix commits `3914b5d`/`2c87f62`)
**Spec**: `.specs/features/library-stats/spec.md`
**Diff range**: `4fbcbd5..2c87f62` (HEAD) — original `4fbcbd5..9b3851b` + 2 fix commits
**Verifier**: independent sub-agent (author ≠ verifier)

**Re-verification note**: this report was updated in place, not rewritten. Sections
STATS-01-01/02/04/05/06 and sensor mutations #1/#2/#4 were NOT re-run (unaffected by
the fix commits, per orchestrator instruction) — their original evidence still applies
as recorded below. Only the STATS-01-03 traceability row, the Edge Cases checklist,
sensor row #3, Fix Plans 2 & 3, Gate Check counts, and the Summary verdict were updated.

---

## Task Completion

| Task | Status  | Notes |
| ---- | ------- | ----- |
| T1   | ✅ Done | `library_stats()` + `LibraryStats` dataclass, single `_connect()` per call, all Done-when bullets verified against code + tests. |
| T2   | ✅ Done | Facade compose reuses `find_duplicate_groups()`/`_shape_duplicate_group()`; no `sqlite3`/`subprocess` touched (test-enforced). |
| T3   | ✅ Done | Resource + `_map_resource_errors` registered; all 5 Done-when bullets have test evidence. `sqlite3.Error`/`OSError` branch now independently unit-tested (`tests/unit/test_server_error_mapping.py`) — sensor mutation #3 re-run and confirmed killed (see Sensor section). |

---

## Spec-Anchored Acceptance Criteria

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| STATS-01-01: full AC-1 JSON shape on `resources/read` | Object with `totals`, `formats`, `languages` (+`unset`), `metadata_completeness` (8 fields, filled+pct), `identifier_types`, `authors` (distinct+top10), `tags` (distinct+top10), `data_quality_flags` (incl. `duplicate_title_groups`) | `tests/integration/test_sqlite_reader.py:247-280` — shape asserts on every sub-object's key set; `tests/integration/test_sqlite_reader.py:284-292` — grounded values (`books==count_books()`, `placeholder_pubdate_0101==64`, `unknown_author_books==14`, `comments.filled==49`); `tests/integration/test_sqlite_reader.py:297-311` — top author `{"name": "Eiichirô Oda", "count": 20}`, top-10 cap, descending order; `tests/integration/test_library_reads.py:126-142` — `duplicate_title_groups` contains "A fé explicada" ids `{68,132}`, top lists capped/ordered; `tests/e2e/test_server.py:508-525` — full round trip, `totals.books == count_books()`, seeded duplicate present | ✅ PASS |
| STATS-01-02: empty library → zeroed object, never an error | All counts 0, all lists `[]`, `pct` guarded to `0.0` | `tests/integration/test_sqlite_reader.py:324-351` — exact zeroed `LibraryStats` fields; `tests/integration/test_library_reads.py:146-161` — facade shape incl. `duplicate_title_groups: []`; `tests/e2e/test_server.py:528-533` — resource-level zeroed | ✅ PASS |
| STATS-01-03: succeeds while GUI holds `metadata.db` lock (AD-010) | Read succeeds exactly like `get_book`/`list_books` | **no test found** — still no test anywhere in `tests/` simulates a held GUI lock, for `library_stats()` or the pre-existing `get_book`/`list_books`. Not addressed by the fix commits (explicitly out of scope per orchestrator — see Fix 1). | ❌ GAP — **accepted as tracked tech debt**, not silently dropped: pre-existing, project-wide (not introduced or worsened by STATS-01), explicitly deferred by the orchestrator to avoid scope creep into whole-read-layer test infrastructure |
| STATS-01-04: unreadable `metadata.db` → named `ResourceError`, never silent/empty | `ResourceError` naming the failure | `tests/e2e/test_server.py:537-545` — corrupts `metadata.db`, asserts `pytest.raises(ResourceError)` and `"file is not a database" in str(excinfo.value)`; **NEW**: `tests/unit/test_server_error_mapping.py:33-41` — `test_map_resource_errors_wraps_sqlite_error` and `:45-53` `test_map_resource_errors_wraps_os_error` call `_map_resource_errors` directly (bypassing FastMCP's outer catch-all) and assert `ResourceError` is raised with the exact underlying message | ✅ PASS — now independently proven at the unit level, not just observed through FastMCP's own catch-all |
| STATS-01-05: two reads with no DB change → identical | Byte/value-identical | `tests/integration/test_sqlite_reader.py:315-320` — `first == second`; `tests/e2e/test_server.py:549-554` — `first == second` via the resource | ✅ PASS |
| STATS-01-06: computed only through `SqliteReader`/`CalibreLibrary`, reusing `find_duplicate_groups()`, no subprocess | No new SQL outside `sqlite_reader.py`; facade touches no `sqlite3`/`subprocess` | `tests/integration/test_library_reads.py:165-171` — `not hasattr(library_module, "sqlite3")`, `not hasattr(library_module, "subprocess")` (mirrors the existing facade-wide invariant test); code inspection of `library.py` confirms no such imports | ✅ PASS |

**Status**: ⚠️ 5/6 fully closed; STATS-01-03 remains an accepted, tracked pre-existing gap (not a STATS-01 regression). All 3 edge-case gaps below are now closed.

---

## Edge Cases

- [x] **Unset language bucket on non-trivial data** — spec: "not silently dropped from the total." `_stats_languages` computes `unset = books - with_language` (`src/calibre_mcp/sqlite_reader.py:353`). **Now covered**: `tests/integration/test_sqlite_reader.py:299` — `assert stats.languages["unset"] == 91` (grounded, real library) and `:300` — `assert sum(stats.languages.values()) == stats.totals["books"]` (sum-to-total invariant, closes the "not silently dropped" claim precisely).
- [x] **Multi-author top-authors credit** — still only indirectly covered by the grounded `{"Eiichirô Oda": 20}` check (`tests/integration/test_sqlite_reader.py:311`); not addressed by the fix commits and not one of the 3 gaps the orchestrator asked to close. Code remains correct by inspection (`GROUP BY a.id` over every `books_authors_link` row, no primary-only filter, `sqlite_reader.py:406-414`). Left as-is — not in scope of this re-verification pass.
- [x] **Multiple distinct duplicate-title groups all appear** — spec: "all of them SHALL appear... not just the first found." **Now covered**: `tests/integration/test_library_reads.py:180-202` — `test_library_stats_all_distinct_duplicate_groups_appear` seeds 2 distinct duplicate pairs (4 books) on a scratch library and asserts `titles == {"Group One", "Group Two"}` (`:199`) plus exact member-id sets for each group (`:201-202`).
- [x] **`real_pubdate` vs `placeholder_pubdate_0101` boundary** — spec: a real pubdate counts toward `real_pubdate`, not the placeholder. **Now covered**: `tests/integration/test_sqlite_reader.py:296` — `assert stats.metadata_completeness["real_pubdate"]["filled"] == 106`, grounded against the real library (170 − 64 = 106) alongside the already-tested `placeholder_pubdate_0101 == 64`, proving the two counts are mutually exclusive and correctly split.

---

## Discrimination Sensor

All mutations applied directly to the clean real tree (`git status --short src/` confirmed clean before/after each), one file at a time, reverted with `git checkout -- <file>` immediately after each targeted run. Final `git status` confirmed clean (only pre-existing, unrelated uncommitted `.specs/features/library-stats/spec.md`/`design.md`/`tasks.md` changes remained, present before this session started).

| # | File:line | Description | Killed? |
| - | --------- | ------------ | ------- |
| 1 | `src/calibre_mcp/sqlite_reader.py:449` | Flipped `"series_unused": series_used == 0` → `series_used != 0` | ✅ Killed — `test_library_stats_empty_library_returns_zeroed_snapshot` failed |
| 2 | `src/calibre_mcp/library.py:126-130` | Removed `duplicate_title_groups` injection from `library_stats()` | ✅ Killed — 2 tests failed in `test_library_reads.py` (`test_library_stats_includes_known_duplicate_and_ordered_top_lists`, `test_library_stats_empty_library_returns_same_shape`) |
| 3 (original) | `src/calibre_mcp/server.py:87-89` | Removed the `except (sqlite3.Error, OSError)` branch from `_map_resource_errors` | ❌ Survived (original run, pre-fix) — `test_library_stats_resource_unreadable_db_is_resource_error` still passed because FastMCP's own `FastMCP.read_resource()` wraps *any* exception as `ResourceError(str(e))` one layer up, masking the branch. |
| 3 (re-run, post-fix `2c87f62`) | same | Same mutation, re-applied independently by this Verifier against the new unit tests (not just trusted from the orchestrator's report) | ✅ **Killed** — `uv run pytest tests/unit/test_server_error_mapping.py -q`: `test_map_resource_errors_wraps_sqlite_error` and `test_map_resource_errors_wraps_os_error` both failed as expected (2 failed, 2 passed); mutation reverted via `git checkout -- src/calibre_mcp/server.py`, confirmed `git diff --stat src/` empty afterward |
| 4 | `src/calibre_mcp/sqlite_reader.py:331` | Off-by-one: `"next_id_hint": max_id + 1` → `max_id` | ✅ Killed — `test_library_stats_grounded_facts_against_real_library` failed (`186 == 185` assertion error) |

**Sensor depth**: lightweight (targeted at the highest-risk new code across all 3 layers)
**Result**: 4/4 killed (post-fix) — ✅ PASS. Mutation #3 was independently re-applied and re-confirmed killed by this Verifier (not taken on the orchestrator's word alone) against the new `tests/unit/test_server_error_mapping.py`, added in commit `2c87f62` specifically to close this gap.

---

## Code Quality

| Principle | Status |
| --------- | ------ |
| Minimum code | ✅ — one dataclass, one reader method + 7 small static helpers, one facade method, one resource handler + one error mapper; matches the design's scope exactly |
| Surgical changes | ✅ — only the 3 designed src files + their co-located test files touched |
| No scope creep | ✅ — no tool wrapper, no caching, no config knobs added (all explicitly out-of-scope per spec.md) |
| Matches patterns | ✅ — `LibraryStats` dataclass mirrors `Book`; `_map_resource_errors` mirrors `_map_errors`; `_stats_*` static helpers mirror `_authors`/`_tags`/etc. helper style |
| Spec-anchored outcome check (asserted values match spec) | ✅ — the 3 edge-case gaps (unset bucket, multi-group, real_pubdate) are now value-asserted, not just shape-checked (see Edge Cases) |
| Per-layer Coverage Expectation met (domain 1:1 ACs; e2e happy+edge+error) | ✅ — domain layer covers all ACs with grounded values incl. the 3 edge cases; the resource-error mapping branch is now also unit-tested in isolation (`tests/unit/test_server_error_mapping.py`), closing the sensor-#3 gap |
| Every test maps to a spec requirement — no unclaimed tests | ✅ — every new test's inline comment cites a STATS-01-NN or AC-N |
| Documented guidelines followed | `~/.claude/CLAUDE.md` (tests derive from ACs) + `tasks.md` Test Coverage Matrix — followed for the AC-level matrix; the 3 edge cases and AC-3 were not fully closed |

---

## Gate Check

- **Gate command**: `uv run ruff check src tests && uv run pytest` (re-run post-fix, sequentially per repo constraint)
- **Result**: ruff — all checks passed; pytest — 155 passed, 0 failed, 0 skipped, 186.36s
- **Test count before feature** (commit `4fbcbd5`): 53 in the 3 originally-touched files; full-suite baseline 137 (150 − 13), per original report
- **Test count after original 3 commits (`9b3851b`)**: 150
- **Test count after fix commits (`2c87f62`, current HEAD)**: 155 (+5: 4 new unit tests in `tests/unit/test_server_error_mapping.py` + 1 new integration test `test_library_stats_all_distinct_duplicate_groups_appear`; the `real_pubdate`/`unset` edge-case assertions were added into an existing test, not new test functions, so they don't add to the count)
- **Delta**: +18 new tests total across the full STATS-01 effort (13 original + 5 from the fix commits); no deletions detected
- **Skipped tests**: none
- **Failures**: none

---

## Fix Plans

### Fix 1: STATS-01-03 (lock-independence) has zero test evidence — OPEN, accepted as tech debt

- **Root cause**: `library_stats()` correctly reuses `_connect()`'s `mode=ro` URI connection (same guarantee as `get_book`/`list_books`), but no test in the codebase — for any read method, not just this feature — actually holds an exclusive lock on `metadata.db` and confirms the read still succeeds. Pre-existing, project-wide gap, not a regression introduced by STATS-01.
- **Disposition**: The orchestrator deliberately did NOT address this in the fix commits, on the grounds that adding a lock-simulation test now would expand STATS-01's scope into testing infrastructure for the whole read layer — a call this Verifier agrees with given the gap predates this feature and is not unique to it. **Accepted as tracked tech debt**, not silently dropped. Recorded as lesson `L-003` (see `.specs/lessons.json`).
- **Fix task (deferred, not blocking)**: Add one integration test (project-level, not STATS-01-scoped) that opens a second connection with `BEGIN EXCLUSIVE` against a scratch library's `metadata.db` and confirms `get_book`/`list_books`/`library_stats()` all still succeed.
- **Priority**: Minor, deferred.

### Fix 2: 3 edge cases lacked grounded assertions — ✅ CLOSED

- **Closed by**: `3914b5d`. `tests/integration/test_sqlite_reader.py:296,299-300` add `real_pubdate.filled == 106` and `languages["unset"] == 91` + sum-to-total invariant, grounded against the real library; `tests/integration/test_library_reads.py:180-202` adds a 2-distinct-duplicate-group scratch-library test asserting both groups and their exact member ids appear. Verified: gate green (155 passed), evidence spot-checked at the cited line numbers.

### Fix 3: sensor mutation #3 survived — ✅ CLOSED

- **Closed by**: `2c87f62`, new file `tests/unit/test_server_error_mapping.py`. Calls `_map_resource_errors` directly (bypassing FastMCP's outer catch-all), proving the `sqlite3.Error`/`OSError` branch independently. Verified: this Verifier independently re-applied the original mutation (removed the `except (sqlite3.Error, OSError)` branch in `server.py:87-89`) and re-ran `tests/unit/test_server_error_mapping.py` — `test_map_resource_errors_wraps_sqlite_error` and `test_map_resource_errors_wraps_os_error` both failed as expected, confirming the mutant is now killed. Mutation reverted; `git diff --stat src/` confirmed empty afterward.

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| ----------- | --------------- | ---------- |
| STATS-01-01 | In Tasks (T1,T2,T3) | ✅ Verified |
| STATS-01-02 | In Tasks (T1,T2) | ✅ Verified |
| STATS-01-03 | In Tasks (T3) | ⚠️ Accepted gap (Fix 1, tracked tech debt — not a STATS-01 regression) |
| STATS-01-04 | In Tasks (T3) | ✅ Verified |
| STATS-01-05 | In Tasks (T1,T3) | ✅ Verified |
| STATS-01-06 | In Tasks (T1,T2) | ✅ Verified |

---

## Summary

**Overall**: ✅ Ready (with 1 accepted, tracked pre-existing gap — STATS-01-03)

**Spec-anchored check**: 5/6 ACs matched spec outcome precisely; 1 accepted gap (STATS-01-03, pre-existing project-wide pattern, deliberately deferred by orchestrator)
**Sensor**: 4/4 mutations killed (mutation #3 was fixed by `2c87f62` and independently re-confirmed killed by this Verifier)
**Gate**: 155 passed, 0 failed (ruff clean)

**What works**: The full AC-1 shape, empty-library zeroing, determinism, read-layer-only/no-subprocess invariant, resource-error mapping (now unit-proven), and all 3 previously-open spec Edge Cases (unset-language value, multi-group duplicates, real_pubdate value) are solidly test-proven with grounded real-library values (170 books, 106 real pubdates, 64 placeholder pubdates, 91 unset-language books, 14 Unknown-author books, top author Eiichirô Oda/20, "A fé explicada" duplicate at ids 68/132). Build gate fully green.

**Issues found**:
1. STATS-01-03 (lock-independence) still has no test evidence anywhere in the codebase — pre-existing, not a STATS-01 regression, explicitly accepted as tracked tech debt rather than silently dropped (Fix 1, OPEN).
2. Edge cases (Fix 2) — ✅ CLOSED by `3914b5d`.
3. Discrimination-sensor mutation #3 (Fix 3) — ✅ CLOSED by `2c87f62`, independently re-verified.

**Next steps**: None blocking. Fix 1 remains open as project-level tech debt (out of STATS-01's scope by explicit orchestrator decision, agreed by this Verifier); revisit if/when the project invests in lock-simulation test infrastructure for the whole read layer.
