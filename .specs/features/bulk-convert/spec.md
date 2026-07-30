# Bulk Convert (BULK-02) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md)
**Feature id:** BULK-02
**Requirement prefix:** `BCONV`
**Context:** `.specs/features/bulk-convert/context.md`

## Problem Statement

Converting many books to a target format today means N separate `convert_book` round-trips — the
GUI's "select many → convert to EPUB" has no MCP equivalent. BULK-02 converts N `book_ids` to one
broadcast `target_format` in a single call, reusing the Verified `convert_book` machinery
(`EbookConvertRunner` + `add_format` + backup). Because a conversion can fail per book (corrupt
source, unsupported input), its defining requirement is an **honest partial-failure contract**: one
book failing never voids the batch and never reports a fake "all succeeded".

## Goals

- [ ] Convert N `book_ids` to one `target_format` in a single additive call — no confirmation token
      (AD-016: convert is additive, keeps existing formats), one `metadata.db` backup before the
      batch as the rollback point (AD-011).
- [ ] Honest three-bucket result: `converted[]` (re-read, resulting formats shown) / `skipped[]`
      (benign no-ops — already has the format, or no source file) / `failed[]` (real per-book
      errors). A per-book failure never aborts the batch; `converted + skipped + failed == N` always.
- [ ] Fail fast on batch-level invalid input (bad target format, empty/duplicate/non-int ids, batch
      over the 50-book cap) **before** any backup or conversion.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Per-book distinct target formats | Decision: broadcast one `target_format` to all (context.md). Per-book targets remain achievable by looping single `convert_book`. |
| A confirmation (plan→confirm) gate | AD-016: conversion is additive and non-destructive (keeps existing formats), so it stays single-step like the single `convert_book`/`add_book`. Roadmap states "additive/no-confirm like today". |
| Removing the source format after convert (destructive "replace" convert) | Outside AD-016's additive rule; not requested. |
| Bulk metadata edit (BULK-01), folder import (BULK-03) | Separate Phase-2 features — different primitives (`set_metadata`, `add_book`). |
| Author/tag rename & duplicate merge (ORGN-01/02/03) | Separate Phase-2 features; not built here. |
| Dry-run / preview of what would convert vs. skip | A plan-without-write step; not requested and against BULK-02's no-confirm contract. |
| Parallel conversions | Sequential keeps single-call-site discipline and deterministic ordering; revisit only if latency becomes real friction. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| New tool vs. overloading `convert_book` | New tool `convert_book_bulk` | Keeps the Verified single-book tool contract untouched; clearer host affordance for a batch op (mirrors `update_metadata_bulk`). | n |
| Benign no-op reporting (already-has-format, no source file) | Own `skipped[{book_id, reason}]` bucket — not `failed` | User decision (context.md): a no-op is not an error; honesty principle forbids a fake failure as much as a fake success. | y (context.md) |
| Batch-size bound | Reject `len(book_ids) > 50` as invalid input, before any backup/convert | User decision (context.md): each convert is a subprocess (300 s per-book timeout); a cap prevents an accidental hour-long "convert everything". Reuses `DEFAULT_LIMIT` sensibility. | y (context.md) |
| Vanished id (exists at call, gone mid-batch) | Lands in `failed[]`, not `skipped[]` | An id that disappears mid-run is an anomaly, not a benign no-op — mirrors BULK-01 (BEDIT-04) which puts a vanished id in `failed[]`. | y |
| Duplicate ids in `book_ids` | Rejected as invalid input before any convert | Silent dedup could mask a caller mistake; rejecting keeps the input canonical (mirrors BULK-01). | n |
| Non-integer / `bool` id | Rejected as invalid input before any convert | Type-narrow at the boundary (mirrors BULK-01). | n |
| `target_format` case | Lowercased before the `SUPPORTED_CONVERT_FORMATS` check (as single `convert_book` does) | Uniform with the single tool; `"EPUB"` and `"epub"` are the same target. | y |
| Backup when every book is skipped | Still take exactly one backup before the loop | Consistency with BULK-01's unconditional pre-loop rollback point; a no-op-batch snapshot is harmless under AD-011 rolling retention. | n |
| `converted[]` payload | Re-reads each converted book's resulting **format list** only (not the full record) | Demonstrates success (project principle) while keeping the payload lean for N books. | n |
| Processing order | Ascending `book_id` | Deterministic, reproducible `converted`/`skipped`/`failed` ordering. | n |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Broadcast bulk convert with honest partial-failure ⭐ MVP

**User Story**: As the library owner, I want to convert many books to one target format in a single
call, so that batch format conversion (e.g. "make EPUBs of these 20 books for my reader") stops
requiring the Calibre GUI or N separate `convert_book` calls.

**Why P1**: This is the batch equivalent of a high-frequency GUI action and a Phase-2 phase-gate
item; the partial-failure contract is what makes a multi-book convert trustworthy.

**Acceptance Criteria**:

1. WHEN `convert_book_bulk(book_ids, target_format)` is called with a supported target THEN the
   system SHALL take exactly one `metadata.db` backup **before** the first `add_format` (AD-011),
   convert each book to `target_format` keeping its existing format(s) (additive, AD-016), and
   return `converted[]`, `skipped[]`, `failed[]`, and the `backup` path — with **no** confirmation
   token (single-step, AD-016). *(BCONV-01)*
2. WHEN one book fails to convert (corrupt/unsupported source, `ebook-convert` error or timeout,
   `add_format` error, or an id that vanished mid-batch) THEN the system SHALL still convert the
   remaining books and record that book in `failed: [{book_id, error}]` — never aborting the batch,
   never reporting a fake "all succeeded". *(BCONV-02)*
3. WHEN a book already has `target_format`, or has no source file to convert from THEN the system
   SHALL record it in `skipped: [{book_id, reason}]` and continue — not counted as `converted`, not
   a hard failure. *(BCONV-03)*
4. WHEN a book converts successfully THEN the system SHALL re-read that book and include its
   resulting format list in `converted: [{book_id, formats}]`, so success is demonstrated, not
   asserted. *(BCONV-04)*
5. WHEN the apply completes THEN the invariant `len(converted) + len(skipped) + len(failed) ==
   len(book_ids)` SHALL hold — every book lands in exactly one bucket. *(BCONV-05)*
6. WHEN `target_format` is not in the supported set (epub/azw3/mobi/pdf), OR `book_ids` is empty,
   contains a duplicate, or contains a non-integer, OR `len(book_ids) > 50` THEN the system SHALL
   reject the call as invalid input **before** any backup or conversion. *(BCONV-06)*

**Independent Test**: Bootstrap a scratch library with 3 books that have a convertible source
format; call `convert_book_bulk([...3 ids...], "epub")` and assert all 3 read back an added `EPUB`
(existing format preserved), exactly one backup exists, and `converted` has 3 entries with
`formats`. Then, in a batch where one id already has `EPUB` and one id does not exist, assert the
already-EPUB id lands in `skipped` (reason mentions the format), the missing id lands in `failed`,
and the remaining id still converts.

---

## Edge Cases

- WHEN `book_ids` has a single id THEN the system SHALL still run the full convert path (degenerate
  batch, not an error).
- WHEN every book in the batch is a benign no-op (all already have `target_format`) THEN the system
  SHALL return all ids in `skipped[]`, an empty `converted[]`/`failed[]`, and still report the one
  backup path (no conversion, no `add_format`).
- WHEN a book exists but has zero source formats THEN it SHALL land in `skipped[]` with a
  no-source reason (consistent with the single tool's "no file to convert from").
- WHEN `book_ids` contains a duplicate, a non-integer, or a `bool` THEN the system SHALL reject the
  call as invalid input before any backup (BCONV-06).
- WHEN `len(book_ids)` is exactly 50 THEN the call SHALL be accepted; 51 SHALL be rejected (BCONV-06).
- WHEN `target_format` is given in any case (e.g. `"EPUB"`) THEN it SHALL be lowercased before the
  supported-format check.
- WHEN books are processed THEN the order SHALL be ascending `book_id` for deterministic reporting.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| BCONV-01 | P1: Broadcast bulk convert | Design | In Design |
| BCONV-02 | P1: Broadcast bulk convert | Design | In Design |
| BCONV-03 | P1: Broadcast bulk convert | Design | In Design |
| BCONV-04 | P1: Broadcast bulk convert | Design | In Design |
| BCONV-05 | P1: Broadcast bulk convert | Design | In Design |
| BCONV-06 | P1: Broadcast bulk convert | Design | In Design |

**ID format:** `BCONV-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 6 total, 0 mapped to tasks yet (Tasks phase pending), 0 unmapped.

---

## Success Criteria

- [ ] A batch convert of many books to one target format completes in one call, no Calibre GUI.
- [ ] Every converted book keeps its original format and gains the target format (additive, zero
      destructive overwrites).
- [ ] A batch mixing successes, an already-has-target book, and a failing/missing book yields a
      truthful three-bucket report — never a false "all succeeded", never a benign skip counted as a
      failure.
- [ ] Every batch is preceded by exactly one `metadata.db` backup; invalid input (bad target,
      bad ids, over-cap) never reaches a backup or a conversion.
