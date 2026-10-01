# ENRICH-03 (Batch Enrichment Review Mode) — Validation

**Verdict:** PASS
**Verifier role:** independent (author ≠ verifier)
**Diff range:** `e22fbc4..HEAD` (3 commits: 0cec3d6 T1 reader, 1e56ddd T2 facade, 6b77862 T3 server)
**Date:** 2026-08-07

## Gate results

| Gate | Command | Result |
| --- | --- | --- |
| Full suite | `.venv/bin/python -m pytest -q` | **386 passed** in 521s, exit 0 |
| Types | `.venv/bin/mypy src/calibre_mcp` | Success: no issues in 17 source files, exit 0 |
| Lint | `.venv/bin/ruff check src tests` | All checks passed, exit 0 |

Note: task brief expected 383 passed (+17 over a 366 baseline); observed is **386 passed**
(no failures, no regressions). The delta is *more* passing tests than forecast, not fewer — the
gate ("all pass, no regression") holds. The +3 vs. forecast is a spec-precision note on the
tasks estimate, not a defect.

## Per-AC evidence

| Req | Outcome required | Test (file:line) + asserted value | Status |
| --- | --- | --- | --- |
| ENRICH3-01 | Select isbn ∧ gap, id-ordered; loop enrich_from_identifier; results+summary; write nothing | `test_sqlite_reader_enrich.py:63` `ids == [a, b]`, `total == 2`; `test_enrichment_batch.py:135-153` `candidate_count==3`, C/D excluded, `_db_digest == before` | PASS |
| ENRICH3-02 | proposed item carries verbatim ENRICH-01 payload + status | `test_enrichment_batch.py:141-148` `by_id[a]["proposed"]=={comments,publisher,pubdate}`, `cover["local_path"]`, `by_id[b]["skipped_present"]==["comments","pubdate"]` | PASS |
| ENRICH3-03 | found+empty→no_new_data; no record→no_record | `test_enrichment_batch.py:227-231` `no_new_data`/`no_record`, `summary=={...no_new_data:1,no_record:1}` | PASS |
| ENRICH3-04 | source error→status:error, sweep continues | `test_enrichment_batch.py:149-152` `by_id[e]=={status:error, reason:...}` while A,B still returned; e2e `test_server.py:1375-1379` `_call` does NOT raise, `summary["error"]==1` | PASS |
| ENRICH3-05 | report candidate_count/processed/limit/offset | `test_enrichment_batch.py:177-180` `candidate_count==2`, `processed==1`, `limit==1` | PASS |
| ENRICH3-06 | empty / offset-past-end → empty, zeroed summary, not error | `test_enrichment_batch.py:197-203` `processed==0`, `results==[]`, zeroed summary, `fetch_calls==0`; reader `test_sqlite_reader_enrich.py:112-113` `(1, [])` | PASS |
| ENRICH3-07 | default cap 25 when no limit | `test_enrichment_batch.py:275-276` `limit==ENRICH_BATCH_DEFAULT==25` and `seen_limits==[25]` (spy on reader arg) | PASS |
| ENRICH3-08 | bad bound → InvalidInputError before selection/network | `test_enrichment_batch.py:304-307` parametrized {0,-1,1000,offset:-1,True} raise, `fetch_calls==0`, `selection_calls==[]`; e2e `test_server.py:1385` ToolError on limit:0 | PASS |
| ENRICH3-09 | sequential, one lookup per candidate, id order | `test_enrichment_batch.py:330-332` `fetch_calls==3`, `received_isbns==isbns` (id order) | PASS |

**Edge cases:** placeholder-pubdate-alone candidate (`test_sqlite_reader_enrich.py:79`);
deterministic id-order paging (`test_sqlite_reader_enrich.py:98-100`); bool rejected as non-int
(`limit: True` param, `test_enrichment_batch.py:282`); cap-ceiling boundary rejection (`limit:1000`).
Spec-anchored coverage: **9/9** requirements.

## Discrimination sensor (mutation testing)

Each mutation applied to product code in a scratch edit, covering test run, then `git checkout --`
restore. Ran isolated (not concurrent with the full suite — concurrent calibredb access causes
seed contention and false signals).

| # | Mutation | Covering test | Result |
| --- | --- | --- | --- |
| 1 | Drop ISBN `EXISTS` guard in `enrichable_candidates` | `test_selects_only_books_with_isbn_and_a_gap` | **KILLED** (fail @ line 63) |
| 2 | `except EnrichmentSourceError` → `raise` (abort batch) | `test_sweep_returns_proposals_isolates_errors_and_writes_nothing` | **KILLED** (EnrichmentSourceError propagated) |
| 3 | `ENRICH_BATCH_DEFAULT = 25` → `26` | `test_default_cap_is_applied_to_selection` | **KILLED** (fail @ line 275) |
| 4 | `_classify_enrichment` → always `"proposed"` | `test_no_new_data_and_no_record_statuses` | **KILLED** (fail @ line 227) |

**Sensor: 4/4 killed.** Tests are behavior-discriminating on the highest-risk new code.
Tree confirmed clean after restores (`git status` shows only untracked `.specs/.../`).

## Code quality

Surgical, matches existing patterns: reader query mirrors `books_by_*` id-discovery + `list_books`
limit/offset; facade reuses `enrich_from_identifier` verbatim and the existing `isinstance(x,bool)`
non-int discipline; server tool is a thin `_map_errors`+`_jsonify` sibling of `enrich_from_identifier`.
No new outbound site, no write path, no scope creep. mypy + ruff clean.

## Verdict

**PASS** — 9/9 requirements spec-anchored to passing assertions; gates green (386 passed, mypy,
ruff); 4/4 mutants killed; read-only/no-write property asserted via byte-digest.
