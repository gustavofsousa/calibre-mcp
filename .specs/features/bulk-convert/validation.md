# BULK-02 (bulk-convert) — Verifier Report

**Verdict:** ✅ PASS
**Diff / commit range:** `bbb5bf2..1bfb445` (T1 `c054920`, T2 `af071ab`, T3 `1bfb445`)
**Gates:** `uv run mypy src` clean · `uv run ruff check .` clean · `uv run pytest -q` → **211 passed**
**Mode:** Standalone fresh-eyes pass (author == implementer; spec-anchored coverage + discrimination sensor run independently over the committed tree).

---

## Spec-Anchored Coverage Check (evidence-or-zero)

| Requirement / AC | `file:line` + assertion | Spec-defined outcome | Verdict |
| --- | --- | --- | --- |
| BCONV-01 (additive, one backup before batch, no token) | `test_library_bulk_convert.py:107` — `assert len(_snapshots(backup_root)) == 1` + `result["backup"] == str(_snapshots(...)[0])`; read-back `{EPUB, PDF}` | one backup, additive, no token field returned | ✅ |
| BCONV-01 (backup unconditional even all-skipped) | `test_library_bulk_convert.py:174` — `assert len(_snapshots(backup_root)) == 1` with `converted==[] failed==[]` | one backup taken even when nothing converts | ✅ |
| BCONV-02 (best-effort, per-book failure isolated) | `test_library_bulk_convert.py:196` — `{f["book_id"] for f in result["failed"]} == {bogus}` and `{c…} == {good}` + `get_book(good).formats == {EPUB,PDF}` | failing book → failed[], others still convert | ✅ |
| BCONV-02 (vanished id → failed) | `test_library_bulk_convert.py:135` — `{f["book_id"] for f in result["failed"]} == {missing}` | missing id lands in failed[] | ✅ |
| BCONV-03 (already-has-target → skipped) | `test_library_bulk_convert.py:133` — `{s["book_id"] …} == {already_pdf}` + `"PDF" in reason` | benign no-op → skipped[], reason names format | ✅ |
| BCONV-03 (no source → skipped) | `test_library_bulk_convert.py:190` — `"no file to convert from" in result["skipped"][0]["reason"]` | no-source → skipped[], not failed | ✅ |
| BCONV-04 (re-read resulting formats) | `test_library_bulk_convert.py:100` — `set(by_id[id]["formats"]) == {EPUB, PDF}` (from `converted[].formats`) | converted[] carries re-read formats | ✅ |
| BCONV-05 (three-bucket invariant) | `test_library_bulk_convert.py:136` — `len(converted)+len(skipped)+len(failed) == len(book_ids)` | every id in exactly one bucket | ✅ |
| BCONV-06 (bad target rejected pre-write) | `test_library_bulk_convert.py:207` — `raises(InvalidInputError)` + `_snapshots == []` | rejected before any backup | ✅ |
| BCONV-06 (empty / duplicate / non-int / bool ids) | `:219,:228,:238,:245` — four `raises(InvalidInputError)` cases | rejected before backup | ✅ |
| BCONV-06 (over-cap 51 / exactly-50) | `:257` `raises` + `_snapshots == []`; `:268` `_validate_bulk_convert_input(range(1,51),"EPUB") == "epub"` | 51 rejected, 50 accepted + normalized | ✅ |
| T1 shared core — `_classify_convert` 3 outcomes | `test_library_p2.py` — ready→source path, already-has→`"EPUB" in reason`, no-source→`"no file to convert from"` | skip = data, ready = source | ✅ |
| T1 behavior-preserving refactor (CONV-01) | `test_library_p2.py` — 6 convert cases green; bogus-source assertion aligned to AC-5 (`len(_snapshots)==1`, formats unchanged) | single tool contract preserved | ✅ (1 over-specified assertion adjusted, user-approved) |
| T3 tool surface (round-trip / three buckets / ToolError / stdout / docstring) | `test_server.py` — 6 e2e cases | additive round-trip, routing, invalid→ToolError, clean stdout, documented contract | ✅ |

**No unverified criterion.** No spec-precision gaps outstanding (the single-tool backup-timing assertion was resolved to spec AC-5 with user sign-off — see Decision below).

## Discrimination Sensor (behavior-level mutants, scratch only, reverted)

| Mutant | Injected fault | Killing test(s) | Result |
| --- | --- | --- | --- |
| M1 | `_classify_convert`: flip `if not source_files` → `if source_files` | `test_classify_convert_ready_returns_source_path`, `test_classify_convert_no_source_is_skip` | ✅ killed (2 fail) |
| M2 | cap off-by-one `> BULK_CONVERT_MAX` → `>=` | `test_validator_accepts_exactly_50_and_normalizes_target` | ✅ killed |
| M3 | route skip into `failed` instead of `skipped` | `test_all_skipped_batch_…`, `test_no_source_book_is_skipped_not_failed` | ✅ killed |

**3/3 mutants killed.** Tree reverted to `HEAD` after each (`git diff --stat` empty).

## Decision recorded during Execute

**T1 backup-order conflict (user-approved).** The design prescribes the single `convert_book` share `_convert_and_attach` with the backup taken *before* the convert (unifying with the bulk one-backup order), but the pre-existing CONV-01 test asserted "no backup on a failed convert" — stricter than spec AC-5 ("convert failure surfaces stderr, adds nothing"). User chose the design path: adopt backup-first and align that one over-specified assertion to AC-5. A pre-convert `metadata.db` snapshot is harmless under AD-011 rolling retention.
