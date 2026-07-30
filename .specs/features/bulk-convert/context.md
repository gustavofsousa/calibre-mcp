# Bulk Convert (BULK-02) Context

**Gathered:** 2026-07-20
**Spec:** `.specs/features/bulk-convert/spec.md`
**Status:** Ready for design

---

## Feature Boundary

Convert N `book_ids` to one broadcast `target_format` in a single call, reusing the Verified
`convert_book` machinery (`EbookConvertRunner`, `CalibredbRunner.add_format`, `format_files`,
`backup_metadata_db`). Additive and single-step (no plan→confirm token, per AD-016 — like the
single `convert_book` and `add_book`). Does **not** include per-book distinct target formats, a
confirmation gate, folder import (BULK-03), or the ORGN organization features.

---

## Implementation Decisions

### Target-format model

- **Broadcast**: one `target_format` applied to every `book_id` (mirrors BULK-01's broadcast
  `fields`). Per-book distinct targets stay out of scope (achievable by looping single `convert_book`).
- Validated **once, up front** against `SUPPORTED_CONVERT_FORMATS` (epub/azw3/mobi/pdf) — a bad
  target has no valid interpretation for any book, so it is a hard abort before any backup/convert
  (mirrors BULK-01's invalid-field fast-fail).

### No confirmation gate

- Single-step + one backup, exactly like the single `convert_book` (AD-016: conversion is additive,
  keeps existing formats, never overwrites). No `confirmation_token`. This is the roadmap's stated
  contract for BULK-02 ("additive/no-confirm like today").

### Partial-failure contract (roadmap's core requirement for BULK-02)

- **Best-effort per-book.** A per-book conversion error (corrupt source, `ebook-convert` failure,
  vanished id) does **not** abort the batch. Exactly one `metadata.db` backup is taken **before**
  the loop and returned as the rollback point.
- **Three buckets (user decision 2026-07-20):** `converted[]` / `skipped[]` / `failed[]`.
  - `converted[{book_id, formats}]` — re-read after success, resulting format list reported
    (demonstrated, not asserted).
  - `skipped[{book_id, reason}]` — **benign no-ops**: the book already has `target_format`, or has
    no source file to convert from. Not an error; the single-book tool raises `InvalidInputError`
    for these, but in a batch they must not count as failures.
  - `failed[{book_id, error}]` — genuine failures: conversion error / `ebook-convert` timeout /
    vanished id / calibredb `add_format` error.
  - Invariant: `len(converted) + len(skipped) + len(failed) == len(book_ids)`.

### Batch-size bound (user decision 2026-07-20)

- **Cap at 50 books per call.** Each conversion is an `ebook-convert` subprocess (300 s per-book
  timeout in `EbookConvertRunner`); a cap prevents an accidental "convert the whole library" that
  runs for an hour. A batch larger than 50 is rejected as invalid input **before** any backup or
  conversion; the host pages if it needs more. Reuses the `DEFAULT_LIMIT = 50` sensibility.

### Reuse over new primitives

- The convert core (`format_files` source-resolve → `EbookConvertRunner.convert` into a temp dir →
  `CalibredbRunner.add_format`) is **factored out of the existing `convert_book`** into a private
  helper so both the single tool and the bulk tool share one call site. No new subprocess pattern,
  no network (AD-001/AD-005/AD-014 unchanged). This mirrors how BULK-01/ORGN are described in the
  roadmap: compound orchestration on already-Verified primitives.

### Agent's Discretion

- Processing + report order — ascending `book_id` for deterministic `converted`/`skipped`/`failed`.
- Backup timing — one unconditional backup **before** the loop (even if every book ends up skipped),
  for consistency with BULK-01's "one rollback point before the batch" discipline; a no-op-batch
  backup is harmless under AD-011 rolling retention.
- `converted[]` payload — re-read resulting **formats only** (not the full record), lean for N books
  while still demonstrating success.

### Declined / Undiscussed Gray Areas → Assumptions

- Duplicate-id handling, non-integer-id handling, single-id degenerate batch, `target_format`
  case-normalization, and the exact `skipped` vs `failed` classification of a *vanished* id are
  each recorded in the spec's **Assumptions & Open Questions** table with a chosen default and
  rationale.

---

## Specific References

- Reuse `SqliteReader.format_files` / `SqliteReader.get_book`, `EbookConvertRunner.convert`,
  `CalibredbRunner.add_format`, `backup_metadata_db`, and `SUPPORTED_CONVERT_FORMATS` — no new
  subprocess or network surface.
- Honesty contract mirrors BULK-01 (per-item report, never a fake all-succeeded) and the roadmap's
  BULK-02 wording ("if book 5 of 20 fails, the other 19 still succeed and the failure is reported
  per-book").

---

## Deferred Ideas

- **Per-book distinct target formats** — a future enhancement if broadcast-target proves
  insufficient; achievable today by looping single `convert_book`.
- **Dry-run / preview of what would convert vs. skip** — a plan-without-write step; not requested
  and against the roadmap's "no-confirm" contract for BULK-02.
- **Parallel conversions** — sequential keeps the single-call-site discipline and predictable
  ordering; revisit only if batch latency becomes real friction.
- **Removing the source format after convert** (true "replace" convert) — a destructive variant
  outside AD-016's additive rule; not requested.
