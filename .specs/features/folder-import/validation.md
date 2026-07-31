# Folder Import (BULK-03) Validation

**Date**: 2026-07-30
**Spec**: `.specs/features/folder-import/spec.md`
**Diff range**: `08c1ecf..015fafe` (branch `feat/bulk-metadata-edit`; commits `bab26e1`, `076bc5e`, `9fd7b71`, `015fafe`)
**Verifier**: independent sub-agent (author != verifier)

---

## Task Completion

| Task | Status | Notes |
| ---- | ------ | ----- |
| T1 folder_scan pure module | Done | 9 unit tests |
| T2 extract `_import_one` + refactor `add_book` | Done | +2 integration tests; ADD-01..04 regression green |
| T3 `import_folder` facade | Done | 10 integration tests |
| T4 `import_folder` MCP tool | Done | 4 e2e tests |

---

## Spec-Anchored Acceptance Criteria

| Criterion | Spec-defined outcome | file:line + assertion | Result |
| --- | --- | --- | --- |
| BIMPORT-01 recursion | nested ebook discovered | `tests/unit/test_folder_scan.py:58` — `scan_ebook_files(tmp_path) == [ebook]` (nested/deeper) | PASS |
| BIMPORT-01 case-insensitive | `Book.EPUB` recognized | `test_folder_scan.py:67` — `scan_ebook_files(tmp_path) == [ebook]` | PASS |
| BIMPORT-01 non-ebook ignored | readme.txt absent | `test_folder_scan.py:77` — `== [ebook]` (readme.txt present, not returned) | PASS |
| BIMPORT-01 dotfile excluded | `.hidden.epub` excluded | `test_folder_scan.py:87` — `== [ebook]` | PASS |
| BIMPORT-01 hidden dir pruned | `.git/` subtree skipped | `test_folder_scan.py:99` — `== [ebook]` | PASS |
| BIMPORT-01 no symlink follow | symlinked subtree not scanned | `test_folder_scan.py:113` — `scan_ebook_files(target) == []` | PASS |
| BIMPORT-01 whitelist set | exact 19-ext frozenset | `test_folder_scan.py:25` — `EBOOK_EXTENSIONS == frozenset({...})` | PASS |
| BIMPORT-01 end-to-end | recursion + ignore via facade | `tests/integration/test_library_folder_import.py:188` — `added_paths == {book1, book2}` | PASS |
| BIMPORT-02 missing path pre-backup | reject, no backup | `test_library_folder_import.py:77-80` — `raises(InvalidInputError)`; `_snapshots == []` | PASS |
| BIMPORT-02 file path pre-backup | reject, no backup | `:89-92` — `raises(InvalidInputError)`; `_snapshots == []` | PASS |
| BIMPORT-02 501 over-cap pre-backup | reject, no backup, cap msg | `:121-125` — `raises(InvalidInputError)`; `"500" in msg`; `_snapshots == []` | PASS |
| BIMPORT-02 500 boundary accepted | reaches loop, 1 backup | `:146-151` — `len(duplicate)==500`; `len(_snapshots)==1` | PASS |
| BIMPORT-02 tool surface non-dir | ToolError "directory" | `tests/e2e/test_server.py` `test_import_folder_nonexistent_path_is_tool_error` — `raises(ToolError)`; `"directory" in msg` | PASS |
| BIMPORT-03 one backup, buckets+backup | 1 backup before loop, status | `:164-167` — `status=="imported"`; buckets empty; `len(_snapshots)==1`; `backup==snapshot` | PASS |
| BIMPORT-03 no token, tool returns buckets+backup | happy path buckets + backup | e2e `test_import_folder_happy_path...` — `status=="imported"`; `added` len 1; `backup` truthy (call w/ only `{path}`, no token) | PASS |
| BIMPORT-04 per-file failure isolated | failed bucket, batch continues | `:264-269` — `{f.path}=={bogus}`; `{a.path}=={good}`; `duplicate==[]`; sum==2 | PASS |
| BIMPORT-05 duplicate surfaced, no fake id | duplicate[{path}], no id | `:214-215` — `added==[]`; `duplicate==[{"path": epub}]` | PASS |
| BIMPORT-05 core duplicate branch | `{duplicate:True, book_id:None}` | `tests/integration/test_library_mutations.py` `test_import_one_duplicate_branch...` — `result == {"duplicate": True, "book_id": None}` | PASS |
| BIMPORT-06 added real id + metadata | int book_id + re-read book | `:190-191` — `isinstance(book_id, int)`; `book.id == book_id` | PASS |
| BIMPORT-06 core added branch | real id + book | `test_library_mutations.py` `test_import_one_added_branch...` — `duplicate is False`; `isinstance(book_id,int)`; `book.id==book_id` | PASS |
| BIMPORT-07 bucket-sum invariant | added+dup+failed == candidates | `:194-196`, `:238-240`, `:267-269` — `len(added)+len(duplicate)+len(failed) == 2` | PASS |

**Status**: All 7 ACs covered with spec-anchored assertions. No spec-precision gaps.

---

## Discrimination Sensor

Scratch method: in-place edit of committed-clean source, targeted test run, `git checkout --` restore. Verified tree clean after (`git diff -- src tests` empty).

| # | File:line | Mutation | Test | Killed? |
| - | --------- | -------- | ---- | ------- |
| 1 | `folder_scan.py:52` | `followlinks=False` -> `True` | `test_symlinked_directory_is_not_followed` | Killed |
| 2 | `folder_scan.py:55-56` | removed dotfile file-exclusion | `test_dotfile_is_excluded` | Killed |
| 3 | `library.py:471` | `> FOLDER_IMPORT_MAX` -> `>=` | `test_500_candidates_accepted_takes_one_backup` | Killed |
| 4 | `library.py:438` | `if result.duplicate:` -> `if not result.duplicate:` | `test_import_one_duplicate_branch_never_returns_fake_id` + added-branch | Killed |

**Sensor depth**: lightweight (4 behavior-level mutations on highest-risk new code)
**Result**: 4/4 killed — PASS

---

## Boundary / Lesson Discipline

- **AD-021** (filesystem discovery is its own pure module): `folder_scan.py` imports only `os`, `pathlib` — no `calibredb`/`sqlite3` (the only matches are docstring text). `server.py::import_folder` tool body performs no filesystem walk; it only calls `_get_library().import_folder(path)` and maps the `added` book records. PASS.
- **L-006** (no backup inside a shared extracted core): `_import_one` contains no `backup_metadata_db` call (only a docstring note); `add_book` and `import_folder` each back up before calling it. PASS.

---

## Gate Check

- **ruff**: `uv run ruff check src tests` -> exit 0, "All checks passed!"
- **mypy**: `uv run mypy` -> exit 0, "Success: no issues found in 14 source files"
- **pytest (full, first pass, concurrent)**: `uv run pytest -q` -> 225 passed, 6 skipped, 1 failed, 4 errors (336s). ALL failures/errors were pre-existing calibredb-backed tests (`add_book`, `convert_book`, `update_metadata`) raising `LibraryLockedError` — caused by a concurrently-launched feature-test run colliding with Calibre's single-instance lock. NO folder-import feature test failed.
- **pytest (clean serial re-run of affected + feature files)**: `uv run pytest tests/unit/test_folder_scan.py tests/integration/test_library_folder_import.py tests/integration/test_library_mutations.py tests/e2e/test_server.py -q` -> **90 passed** (159s), exit 0. Confirms the concurrent failures were pure lock contention, not defects.

**New tests added by feature**: 9 unit + 10 integration (folder import) + 2 integration (`_import_one`) + 4 e2e = 25.

---

## Summary

**Overall**: Ready (PASS)

**Spec-anchored check**: 7/7 ACs matched spec outcome; 0 spec-precision gaps
**Sensor**: 4/4 mutations killed
**Gate**: ruff 0, mypy 0, pytest green when not lock-contended (90/90 on the affected+feature subset)

**What works**: recursive whitelist discovery (case-insensitive, dotfile/hidden/symlink safe, sorted), fail-fast batch validation before backup (non-dir, 500/501 boundary, OSError->InvalidInputError), exactly one pre-loop backup, honest three-bucket best-effort import with real ids for adds and surfaced duplicates, bucket-sum invariant, single-step no-token tool surface. AD-021 and L-006 honored.

**Issues found**: none grounded in the implementation. The full-suite failures were environmental (Calibre single-instance lock under concurrent test runs), reproduced-clean on a serial re-run.

**Next steps**: mark BIMPORT-01..07 Verified in spec.md traceability. Note for future runs: do not launch two calibredb-backed pytest processes concurrently (global Calibre lock).
