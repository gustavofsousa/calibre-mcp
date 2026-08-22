# Folder Import (BULK-03) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md)
**Feature id:** BULK-03
**Requirement prefix:** `BIMPORT`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md
(all gray areas resolved with the user at Specify time, 2026-07-30).

## Problem Statement

Adding a batch of new ebooks today means N separate `add_book` calls, one path at a time — the
GUI's "Add books from directories, including sub-directories" has no MCP equivalent. BULK-03 points
at a single directory, discovers every ebook file inside it (recursively), and imports them in one
additive call, reusing the Verified `add_book` machinery (`calibredb add` + duplicate detection +
backup). Because a folder is *discovered* (the host does not know its contents until scanned) and
any single file can fail or already exist, its defining requirement is an **honest partial-outcome
contract**: one file failing never voids the batch, a duplicate is surfaced not hidden, and success
is demonstrated with real book ids — never a fake "all imported".

## Goals

- [ ] Import every ebook file under a directory (recursive) in a single additive call — no
      confirmation token (AD-016: import is additive like `add_book`), one `metadata.db` backup
      before the batch as the rollback point (AD-011).
- [ ] Honest three-bucket result: `added[]` (new `book_id` + metadata) / `duplicate[]` (already in
      the library, surfaced never re-added) / `failed[]` (real per-file `calibredb` error). A
      per-file failure never aborts the batch; `added + duplicate + failed == <ebook candidates>`.
- [ ] Fail fast on batch-level invalid input (path not an existing directory, more than 500 ebook
      candidates) **before** any backup or import.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Reporting/auditing non-ebook files | User decision (2026-07-30): "whatever isn't [an ebook] just doesn't get imported, that's it." Non-ebook files are silently ignored — no `skipped` bucket, no audit list. |
| A scan→confirm (plan) preview step | User decision: import is direct/single-step, consistent with AD-016 and `add_book`. Safe because it is additive, backed up, and duplicate-surfacing (recoverable via `remove_book`). |
| A confirmation (plan→confirm) token | AD-016: additive/non-destructive imports stay single-step like `add_book`/`convert_book_bulk`. |
| Top-level-only scan / a `recursive` flag | User decision: scan is always recursive (folder + all subfolders). A single fixed behavior keeps the tool contract simple; matches the GUI's "include sub-directories". |
| Auto-conversion or metadata enrichment on import | Import only adds the file as-is; conversion (BULK-02) and enrichment (Phase 3) are separate features. |
| Moving/deleting the source files after import | Import is a copy-in via `calibredb add`; the source folder is left untouched. |
| Bulk metadata edit (BULK-01), bulk convert (BULK-02), author/tag rename & merge (ORGN-01/02/03) | Separate Phase-2 features — different primitives. |
| Parallel imports | Sequential keeps single-call-site discipline and deterministic ordering; revisit only if latency becomes real friction. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Scan depth | Recursive — folder and all subfolders | User decision (2026-07-30). Books often sit in per-title subfolders (e.g. extracted archives); matches the GUI's "include sub-directories". | y |
| Import flow | Direct, single-step, no token | User decision (2026-07-30). Additive + one backup + duplicates surfaced ⇒ safe and recoverable; consistent with `add_book`/`convert_book_bulk` (AD-016). | y |
| Batch-size bound | Reject when **ebook-candidate** count `> 500`, before any backup/import | User decision (2026-07-30). Guards against pointing at a huge tree (e.g. `/home`) while still allowing a large first import. Counts candidates (whitelist matches), not every file, so a folder of 490 ebooks + 1000 cover images is not rejected. | y |
| Non-ebook files (not in whitelist) | Silently ignored — never counted, never in any bucket | User decision (2026-07-30): "o que não for, só não importa e pronto." No audit/`skipped` bucket; keeps the report to real import outcomes only. | y |
| What counts as an ebook (whitelist) | Case-insensitive extension whitelist of unambiguous ebook formats: `epub, mobi, azw, azw3, azw4, kfx, fb2, fbz, pdf, djvu, cbz, cbr, cbc, lit, lrf, pdb, prc, snb, tcr` | Curated to unambiguous ebook containers. Ambiguous document formats (`txt, html, htmlz, rtf, doc, docx, odt`) and metadata files (`opf`) are **excluded** — they are usually folder noise (readme.txt, index.html), matching the user's "notes.txt = don't import" mental model. Exact list finalizable at Design; the *principle* (unambiguous ebooks only) is fixed. | y (principle) |
| Hidden files / dotfiles | Excluded from the scan entirely | `.DS_Store`, `.git`, etc. are not user content; excluding them keeps the candidate set clean and avoids noise in `failed[]`. | n |
| Symlinks | Not followed | Avoids escaping the target tree and symlink loops; a folder import should stay within the folder it was pointed at. | n |
| Duplicate outcome | Surfaced in `duplicate[]` (never re-added, never a fake id) — mirrors ADD-03 | An already-in-library file is not a failure and not a fresh add; honesty forbids a fake id as much as a fake failure. Re-running the same import is therefore safe (idempotent-ish: duplicates just re-report). | y |
| Per-file failure | Lands in `failed[{path, error}]`, batch continues | Mirrors ADD-04 N-wide and the AD-020 best-effort loop; one bad file never voids the batch and never yields a false "all imported". | y |
| Backup when zero ebook candidates | Still take exactly one backup before the loop | Consistency with BULK-01/BULK-02's unconditional pre-loop rollback point; a no-op snapshot is harmless under AD-011 rolling retention. | n |
| Empty folder / zero ebook candidates | Valid result — all three buckets empty (not an error) | A folder with nothing importable is "nothing to do", not a failure; the honest report is empty buckets + the backup path. | y |
| Path validation | Reject when the path is missing or is a file (not a directory) **before** any scan/backup | Mirrors ADD-02's "reject before subprocess/backup"; a non-directory has no valid interpretation for a folder import. | y |
| Unreadable directory (permission error) | Surface as an error to the host (mapped from the OS error), not a silent empty result | An unreadable target is an anomaly the host must see, not a false "nothing found". | n |
| Processing order | Ascending sorted candidate path (string sort) | Deterministic, reproducible `added`/`duplicate`/`failed` ordering (mirrors AD-020's `sorted` discipline, path-keyed here since there are no ids yet). | n |
| `added[]` payload | New `book_id` + the parsed book record (as `add_book` returns) | Demonstrates success with a real id and metadata (project principle), consistent with the single `add_book`. | y |
| Where folder scanning lives (architecture) | **Deferred to Design** — a dedicated scan module/helper, keeping the `library.py` facade orchestrating and the tool layer free of direct filesystem walking | Filesystem-walk is a new I/O kind not covered by the existing sqlite/subprocess invariant; needs an explicit boundary decision (candidate new AD) at Design, not Specify. | n (Design) |

**Open questions:** none — all resolved or logged above. One item (scan-module boundary) is
explicitly deferred to Design as a flagged architecture decision, not left silent.

---

## User Stories

### P1: Import a folder of ebooks with honest partial outcomes ⭐ MVP

**User Story**: As the library owner, I want to point at a folder and import every ebook inside it
(including subfolders) in one call, so that seeding or growing the library from a downloads folder
stops requiring the Calibre GUI or one `add_book` call per file.

**Why P1**: This is the batch equivalent of the GUI's most common bulk-add action and a Phase-2
phase-gate item ("import a folder of new books never requires opening the GUI"); the honest
partial-outcome contract is what makes a multi-file import trustworthy.

**Acceptance Criteria**:

1. WHEN `import_folder(path)` is called with an existing directory THEN the system SHALL discover
   every ebook-candidate file under it **recursively** (folder + all subfolders), matching the
   case-insensitive ebook-extension whitelist, excluding hidden/dotfiles and not following symlinks;
   files not matching the whitelist SHALL be silently ignored (not imported, not reported).
   *(BIMPORT-01)*
2. WHEN the target path is missing or is not a directory (e.g. a file), OR the number of
   ebook-candidate files exceeds 500 THEN the system SHALL reject the call as invalid input
   **before** any backup or import. *(BIMPORT-02)*
3. WHEN input is valid THEN the system SHALL take exactly one `metadata.db` backup **before** the
   first import (AD-011), import each candidate via the existing `calibredb add` path, and return
   `added[]`, `duplicate[]`, `failed[]`, and the `backup` path — with **no** confirmation token
   (single-step, AD-016). *(BIMPORT-03)*
4. WHEN one file fails to import (`calibredb add` error) THEN the system SHALL still import the
   remaining files and record that file in `failed: [{path, error}]` — never aborting the batch,
   never reporting a fake "all imported". *(BIMPORT-04)*
5. WHEN a candidate file is already in the library THEN the system SHALL record it in
   `duplicate: [{path}]` — surfaced, never re-added, never given a fake id (mirrors ADD-03) — and
   continue. *(BIMPORT-05)*
6. WHEN a candidate file imports successfully THEN the system SHALL record it in
   `added: [{path, book_id, book}]` with its **real** new id and parsed metadata, so success is
   demonstrated, not asserted. *(BIMPORT-06)*
7. WHEN the batch completes THEN the invariant `len(added) + len(duplicate) + len(failed) ==
   <number of ebook candidates discovered>` SHALL hold — every candidate lands in exactly one
   bucket. *(BIMPORT-07)*

**Independent Test**: Bootstrap a scratch library and a scratch source tree containing 3 ebook
files across a subfolder plus a non-ebook file (e.g. `readme.txt`) and a dotfile. Call
`import_folder(<tree>)` and assert: all 3 ebooks read back as new `added` entries with real
`book_id`s (the subfolder one included, proving recursion), the `readme.txt`/dotfile are absent
from every bucket (proving silent ignore), exactly one backup exists, and
`len(added)+len(duplicate)+len(failed) == 3`. Then re-run the same import and assert the 3 now land
in `duplicate[]` (surfaced, not re-added), and `added[]` is empty.

---

## Edge Cases

- WHEN the folder contains exactly one ebook file THEN the system SHALL still run the full import
  path (degenerate batch, not an error).
- WHEN the folder exists but has zero ebook candidates (empty, or only non-ebook/hidden files) THEN
  the system SHALL return empty `added`/`duplicate`/`failed`, still report the one backup path, and
  SHALL NOT error.
- WHEN an ebook file exists in a nested subfolder THEN it SHALL be discovered (recursion), and
  processing order SHALL be ascending sorted path for deterministic reporting.
- WHEN the ebook-candidate count is exactly 500 THEN the call SHALL be accepted; 501 SHALL be
  rejected as invalid input before any backup (BIMPORT-02).
- WHEN the path is missing or points at a file THEN the system SHALL reject it as invalid input
  before any scan or backup (BIMPORT-02).
- WHEN the same file is present twice under different subfolders (same content) THEN the first
  imports (`added`) and the second is surfaced as `duplicate` — never a second fake add.
- WHEN a whitelist match differs only in extension case (e.g. `Book.EPUB`) THEN it SHALL still be
  recognized as an ebook candidate (case-insensitive).

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| BIMPORT-01 | P1: Import a folder | Implementing | Verified |
| BIMPORT-02 | P1: Import a folder | Implementing | Verified |
| BIMPORT-03 | P1: Import a folder | Implementing | Verified |
| BIMPORT-04 | P1: Import a folder | Implementing | Verified |
| BIMPORT-05 | P1: Import a folder | Implementing | Verified |
| BIMPORT-06 | P1: Import a folder | Implementing | Verified |
| BIMPORT-07 | P1: Import a folder | Implementing | Verified |

**ID format:** `BIMPORT-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 7 total, 7 mapped to tasks, 7 Verified.

---

## Success Criteria

How we know the feature is successful:

- [ ] Pointing at a folder imports every ebook under it (recursively) in one call, no Calibre GUI.
- [ ] Non-ebook files are silently ignored; the report contains only real import outcomes.
- [ ] A folder mixing new books, an already-in-library book, and a failing file yields a truthful
      three-bucket report — never a false "all imported", never a fake id for a duplicate.
- [ ] Every batch is preceded by exactly one `metadata.db` backup; invalid input (non-directory,
      over the 500 cap) never reaches a backup or an import.
- [ ] Re-running the same import is safe: previously-added files come back as `duplicate`, not
      duplicated records.
