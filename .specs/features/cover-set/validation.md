# Set a Book's Cover From a Local File (COVER-02) — Validation Report

**Verdict: PASS**

Independent Verifier (author ≠ verifier), fresh sub-agent, no context inherited from the
implementer. Commit range verified: `acfe3e6..5eb691e` (T1 facade, T2 tool, docs closeout).

## Per-AC evidence (evidence-or-zero, file:line + assertion)

| Requirement | Evidence | Assertion matches spec-defined outcome? |
| --- | --- | --- |
| SCOVER-01 (plan: current_has_cover, new_cover, token, no write) | `tests/integration/test_library_set_cover.py:136-155` | ✅ Yes — exact plan dict asserted, library untouched, no backup |
| SCOVER-02 (missing path → InvalidInputError, before backup) | `tests/integration/test_library_set_cover.py:189-202` | ✅ Yes — `InvalidInputError`, zero backups, `has_cover` unchanged |
| SCOVER-03 (non-image extension → InvalidInputError, before backup) | `tests/integration/test_library_set_cover.py:208-222` | ✅ Yes — same shape, `.txt` file |
| SCOVER-04 (unknown id → BookNotFoundError, before backup) | `tests/integration/test_library_set_cover.py:227-238` | ✅ Yes — `book_id == 999999`; zero-backup assertion added post-Verifier (was previously implicit only) |
| SCOVER-05 (one backup before write, apply via set_metadata, re-read demonstrates) | `tests/integration/test_library_set_cover.py:162-182` | ✅ Yes — `has_cover is True`, `cover_path` ends `cover.jpg` and is a real file, exactly one snapshot, `backup` matches it |
| SCOVER-06 (token mismatch → refuse, no write) | `tests/integration/test_library_set_cover.py:244-256` | ✅ Yes — `ConfirmationError`, zero backups, `has_cover` unchanged |
| SCOVER-07 (already has cover → replace, not reject) | `tests/integration/test_library_set_cover.py:262-283` | ✅ Yes — plan `current_has_cover is True`; apply overwrites (cover bytes differ, not just a flag) |
| L-001 (backup-before-write order) | `tests/integration/test_library_set_cover.py:289-311` | ✅ Yes — monkeypatch proof: write fails loudly if called before backup fails |
| e2e round trip (SCOVER-01/05 via FastMCP) | `tests/e2e/test_server.py:292-321` | ✅ Yes — tool-surface plan→apply, cross-checked via `read_cover`'s `ImageContent`/`image/jpeg` |
| e2e missing path (SCOVER-02 via FastMCP) | `tests/e2e/test_server.py:325-332` | ✅ Yes — `ToolError` |

## Discrimination sensor

3 behavior-level mutations injected into `src/calibre_mcp/library.py` (scratch edits, reverted,
`git diff` confirmed clean afterward):

1. Flipped `is_file()` guard → 7/9 integration tests failed. **Killed.**
2. Swapped backup-before-write order → `test_set_cover_backup_runs_before_calibredb_write` failed
   with the "ran despite backup failure" assertion. **Killed.**
3. Hardcoded `current_has_cover = False` in the plan branch → replace test failed
   (`assert False is True`). **Killed.**

**Result: 3/3 killed, 0 survived.**

## SPEC_DEVIATION verification

`design.md`'s Risks table assumed a decoded-but-corrupt image would make `calibredb` silently
no-op, the same as a missing path. The author's empirical finding (documented in AD-025 and the
`tests/integration/test_library_set_cover.py` module docstring) is that this is **not** what
happens: a genuine decode failure makes `calibredb` crash with a non-zero exit
(`ValueError: Failed to export image as JPEG with error: Image is empty`, exit 1), which the
runner turns into a propagating `CalibredbError` — a loud failure, not a silent one. Only a
**missing path** (exit 0, no error, no state change) is silent.

**Independently reproduced by the Verifier** against a fresh scratch library with direct
`calibredb` invocations (not via the test suite) — confirmed exactly as claimed.
`test_set_cover_calibredb_decode_failure_propagates_not_a_fake_success` asserts the real
guarantee (`CalibredbError` propagates, `has_cover` stays `False`), which is a stronger and more
accurate replacement for the design doc's now-refuted assumption.

## Gate results (run directly by the Verifier, not the author's claimed numbers)

- `uv run pytest tests/integration/test_library_set_cover.py tests/e2e/test_server.py -k set_cover -v` → 11 passed
- `uv run ruff check src tests` → all checks passed
- `uv run mypy src` → no issues, 16 source files
- Full suite (`uv run pytest`, single clean run) → 329 passed, 0 failed

## Gaps

One minor, non-blocking gap identified and fixed post-report: `test_set_cover_unknown_book_id_raises_not_found`
(SCOVER-04) did not assert zero backups, unlike its SCOVER-02/03/06 siblings. Not a live bug (the
`get_book` precheck is unconditionally the first statement in `set_cover`, before any `Path`/backup
code is reachable) — fixed for evidence consistency (`tests/integration/test_library_set_cover.py:236`).

No other gaps. Implementation matches design 1:1.
