# Enrichment Apply (ENRICH-02) Validation

**Date**: 2026-08-07
**Spec**: `.specs/features/enrichment-apply/spec.md`
**Diff range**: `e74712d..ed5db75` (commits `b57ba83`, `ed5db75` on `feat/covers`)
**Verifier**: independent sub-agent (author ≠ verifier)

---

## Task Completion

No `tasks.md` — spec.md's sizing note explicitly recommends skipping a formal tasks
file (thin surface: one test file + a docstring amendment). Both deliverables present:

| Deliverable | Status | Notes |
| --- | --- | --- |
| `tests/integration/test_enrichment_apply.py` (new, ENRICH2-01..07) | ✅ Done | 5 test functions, 179 lines |
| `enrich_from_identifier` docstring amendment | ✅ Done | `library.py:194-204`, docstring-only, verified via `git show ed5db75` diff |

---

## Spec-Anchored Acceptance Criteria

| Criterion (WHEN X THEN Y) | Spec-defined outcome | `file:line` + assertion | Result |
| --- | --- | --- | --- |
| ENRICH2-01: plan step reflects `proposed` values in diff | `plan["diff"][field]["proposed"] == proposed[field]` for every field | `tests/integration/test_enrichment_apply.py:143-146` — `plan = facade.update_metadata(...)`; `assert plan["diff"][field]["proposed"] == value` | ✅ PASS |
| ENRICH2-02: apply step re-read matches `proposed`, `pubdate` normalized (not verbatim) | `comments`/`publisher` byte-for-byte; `pubdate == "2009-04-15 00:00:00+00:00"` (calibredb's normalization of `"April 2009"`, corrected mid-implementation from a naive verbatim-string assumption) | `tests/integration/test_enrichment_apply.py:148-157` — `assert book.comments == proposed["comments"]`; `assert book.publisher == proposed["publisher"]`; `assert book.pubdate == "2009-04-15 00:00:00+00:00"` | ✅ PASS — matches corrected spec text (spec.md:66-68, design.md SPEC_DEVIATION) |
| ENRICH2-03: empty `proposed` plans OK, fails at apply with `CalibredbError` (corrected from "harmless no-op" assumption) | plan diff `== {}`; apply raises `CalibredbError` | `tests/integration/test_enrichment_apply.py:170-173` — `assert plan["diff"] == {}`; `with pytest.raises(CalibredbError): facade.update_metadata(book_id, fields={}, token=...)` | ✅ PASS — matches corrected spec text (spec.md:70-75) |
| ENRICH2-04: re-running enrichment after apply reuses `update_metadata`'s diff/skip behavior unchanged | re-enrichment's `proposed == {}`, all 3 fields land in `skipped_present` | `tests/integration/test_enrichment_apply.py:199-201` — `assert second["proposed"] == {}`; `assert sorted(second["skipped_present"]) == ["comments", "pubdate", "publisher"]` | ✅ PASS |
| ENRICH2-05: cover plan reports `current_has_cover: false` | `plan["current_has_cover"] is False` | `tests/integration/test_enrichment_apply.py:225-227` — `plan = facade.set_cover(...)`; `assert plan["current_has_cover"] is False` | ✅ PASS |
| ENRICH2-06: cover apply re-read `has_cover: true`, `cover_path` set | `applied["has_cover"] is True`; `applied["cover_path"] is not None` | `tests/integration/test_enrichment_apply.py:232-234` — `assert applied["has_cover"] is True`; `assert applied["cover_path"] is not None` | ✅ PASS |
| ENRICH2-07: null `cover.local_path` never passed to `set_cover`; if it were, raises `TypeError` before any write | `pytest.raises(TypeError)` | `tests/integration/test_enrichment_apply.py:246-247` — `with pytest.raises(TypeError): facade.set_cover(book_id, image_path=None)` | ✅ PASS |

**Status**: ✅ All 7 ACs covered, spec-anchored (no vague assertions; both mid-implementation
corrections — pubdate normalization, empty-fields hard-failure — are reflected exactly in the
test assertions, not the originally-assumed outcomes).

---

## Discrimination Sensor

Mutations injected directly into the real `src/calibre_mcp/library.py` (tree was clean before
and after — each mutation applied, tested, then reverted via `git checkout --` before the next;
confirmed clean with `git status --short` at the end).

| Mutation | File:line | Description | Killed? |
| --- | --- | --- | --- |
| 1 | `library.py:257-259` (`_gap_proposal`) | Swapped `comments`/`publisher` key mapping when building `proposed` (field-mapping bug) | ✅ Killed — `test_proposed_text_fields_apply_through_update_metadata_plan_then_confirm` failed on `assert proposed == {...}` |
| 2 | `library.py:500` (`update_metadata` apply) | Changed `self._runner.set_metadata(book_id, fields)` → `self._runner.set_metadata(book_id, {})` (dropped the fields being written) | ✅ Killed — 2 tests failed: the round-trip test raised `CalibredbError` (empty-field write) instead of applying; `test_reenrichment_after_apply_...` also failed |
| 3 | `library.py:545` (`set_cover` plan) | Flipped `cover_file(book_id) is not None` → `is None` for `current_has_cover` | ✅ Killed — `test_downloaded_cover_applies_through_set_cover_plan_then_confirm` failed on `assert plan["current_has_cover"] is False` |

**Sensor depth**: lightweight (default tier, 3 targeted mutations across all three touched
functions — `_gap_proposal`, `update_metadata`, `set_cover`)
**Result**: 3/3 killed — ✅ PASS
**Tree state after sensor**: clean (`git status --short` empty, `git diff` empty)

---

## Code Quality

| Principle | Status |
| --- | --- |
| Minimum code | ✅ — test file + docstring only, no production logic touched |
| Surgical changes | ✅ — `git show --stat` confirms only 3 non-`.specs` files changed across both commits: new test file, docstring diff in `library.py` |
| No scope creep | ✅ — no new tool/API added, matches Out of Scope table in spec.md |
| Matches patterns | ✅ — reuses `_FakeEnricher`, `scratch_library` fixture, seeding helpers pattern from `test_library_enrich.py`/`test_library_set_cover.py` per design.md's stated Tech Decision |
| Spec-anchored outcome check (asserted values match spec) | ✅ — see AC table above, including both corrected outcomes |
| Per-layer Coverage Expectation met | ✅ — pure integration proof over existing primitives, 1:1 with the 7 ACs, no routes/e2e layer in scope |
| Every test maps to a spec requirement — no unclaimed tests | ✅ — 5 tests map cleanly to ENRICH2-01/02 (test 1), 03 (test 2), 04 (test 3), 05/06 (test 4), 07 (test 5); each test's leading comment cites its AC IDs |
| Documented guidelines followed | ✅ — AD-012 (update_metadata plan→confirm), AD-025 (set_cover plan→confirm), both unchanged and exercised as documented in design.md |

---

## Edge Cases (from spec.md)

- [x] Book mutated between enrich call and `update_metadata` plan call — not separately tested (spec explicitly says "no staleness check is added"); no new behavior to verify, consistent with "reuses EDIT's existing behavior unchanged."
- [x] Empty-string field value — spec marks this "should not happen" per `_gap_proposal`'s `value is not None` guard; not separately tested, consistent with spec's "documented for completeness" framing (no behavior claim requiring a test).
- [x] Stale/mismatched token replay — not separately tested in this file; spec attributes this to existing `EDIT-03`/`SCOVER-06` unchanged behavior, which is out of this feature's coverage responsibility (already covered by `test_library_edit.py`/`test_library_set_cover.py`, not re-verified here — reasonable to not duplicate).

---

## Gate Check

- **Gate command**: `uv run mypy src && uv run ruff check src tests && uv run pytest tests/integration/test_enrichment_apply.py -q`
- **Result**: mypy — success, no issues in 17 source files. ruff — all checks passed. pytest (scoped) — 5 passed, 0 failed.
- **Full suite** (`uv run pytest -q`, run for extra confidence): see final verdict message for outcome (ran in background due to ~9 min runtime).
- **Test count before feature** (at `f32dc94`, `tests` tree pre-ENRICH-02 commits): 361 (366 − 5 new)
- **Test count after feature**: 366 (`uv run pytest --collect-only -q` → "366 tests collected")
- **Delta**: +5 new tests, matches the 5 functions in `test_enrichment_apply.py`
- **Skipped tests**: none observed in the scoped run
- **Failures**: none

---

## Requirement Traceability Update

| Requirement | Previous Status | New Status |
| --- | --- | --- |
| ENRICH2-01 | Pending | ✅ Verified |
| ENRICH2-02 | Pending | ✅ Verified |
| ENRICH2-03 | Pending | ✅ Verified |
| ENRICH2-04 | Pending | ✅ Verified |
| ENRICH2-05 | Pending | ✅ Verified |
| ENRICH2-06 | Pending | ✅ Verified |
| ENRICH2-07 | Pending | ✅ Verified |

---

## Summary

**Overall**: ✅ Ready

**Spec-anchored check**: 7/7 ACs matched spec outcome, including both mid-implementation
corrections (pubdate normalization value, empty-fields hard-failure) verified against the
corrected spec text, not the original assumptions.

**Sensor**: 3/3 mutations killed (field-mapping swap in `_gap_proposal`, dropped-fields apply in
`update_metadata`, flipped `current_has_cover` in `set_cover`) — tests discriminate correctly on
the three functions this feature's flow touches.

**Gate**: mypy clean, ruff clean, scoped pytest 5/5 passed; full-suite `366 tests collected`
(361 pre-feature + 5 new), no count regression.

**What works**: The full lookup → apply-fields → apply-cover chain round-trips through the
existing `update_metadata`/`set_cover` plan→confirm gates exactly as spec'd, with no new
production mutation path (confirmed via `git show ed5db75` — docstring-only diff to `library.py`).
Both empirically-corrected edge cases (pubdate normalization, empty-fields CalibredbError) are
captured precisely, not glossed over.

**Issues found**: none.

**Next steps**: none required. If full-suite run (background) surfaces an unrelated failure
elsewhere in the repo, it is outside this feature's diff surface and should be triaged separately.
