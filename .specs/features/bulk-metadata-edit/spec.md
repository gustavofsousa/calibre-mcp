# Bulk Metadata Edit (BULK-01) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md)
**Feature id:** BULK-01
**Requirement prefix:** `BEDIT`
**Context:** `.specs/features/bulk-metadata-edit/context.md`

## Problem Statement

Editing metadata across many books today means N separate `update_metadata` round-trips (N plans,
N confirmations) — the single most common Calibre-GUI action (select many, apply one change) has no
MCP equivalent. BULK-01 lets the host apply one set of field changes to N books in a single
plan→confirm handshake, reusing the Verified `update_metadata`/backup/token machinery — no new
subprocess pattern, no network. It is the foundation the Phase-2 organization features (ORGN-01
author-rename, ORGN-02 tag-rename) are built on.

## Goals

- [ ] Apply one broadcast set of fields to N `book_ids` in a single call, gated by one batch-wide
      plan→confirm token (AD-012 holds for every book: the plan shows a per-book current→proposed
      diff before any write).
- [ ] Honest partial-failure: a per-book failure never voids the batch and never reports a fake
      "all succeeded" — `applied[]` / `failed[]` reported per book, one `metadata.db` backup before
      the batch as the rollback point.
- [ ] List fields (tags, authors) support `add` / `remove` / `replace` modes so "add tag to N
      books" preserves each book's existing values instead of overwriting them.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Per-book distinct field maps | Decision: broadcast same fields to all (context.md). Per-book edits remain achievable by looping the existing single-book `update_metadata`. |
| All-or-nothing transactional rollback / auto-restore of the backup | Decision: best-effort partial-failure (context.md). `calibredb set_metadata` is per-book with no cross-book transaction; auto-restore is a mechanism the project does not have and did not choose. |
| Bulk convert (BULK-02), folder import (BULK-03) | Separate Phase-2 features — different primitives (`convert_book`, `add_book`). |
| Author/tag rename & duplicate merge (ORGN-01/02/03) | Separate Phase-2 features that *consume* BULK-01 as their apply step; not built here. |
| Search-and-replace field edits (GUI bulk S&R) | Not requested; a distinct capability beyond broadcast field-setting. |
| Cover changes in bulk | Phase 3 (COVER-02). |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| New tool vs. overloading `update_metadata` | New tool `update_metadata_bulk` | Keeps the Verified single-book tool contract untouched; clearer host affordance for a batch op. | n |
| List-mode granularity | One batch-level `list_mode` param (`replace` default / `add` / `remove`) applied to every list field present in `fields` (tags, authors) | KISS — one op = one intent; per-field modes add plan/token surface without a stated need. | y (context.md) |
| `list_mode` on `authors` | Supported uniformly as a list field, though `tags` is the common use | Uniform rule is simpler than special-casing; author-set edits are a valid list operation. | n |
| Duplicate ids in `book_ids` | Rejected as invalid input before any write | Silent dedup could mask a caller mistake; rejecting is safer and keeps the token input canonical. | n |
| Non-existent `book_id` | Not a hard abort — surfaced in the plan and lands in `failed[]` at apply | Best-effort contract (context.md): one bad id must not sink the batch. | y (context.md) |
| Invalid *field name / value* (e.g. unknown field, rating out of 0–10, bad `list_mode`) | Hard abort of the whole plan before any write/backup | Fields are broadcast identically to all books — a bad field has no valid interpretation for any book; fail fast, no token issued. | y |
| Applied report payload | Re-reads each applied book's *affected* fields (not the full record) | Demonstrates success rather than asserting it (project principle), while keeping the payload lean for N books. | n |
| Processing order | Ascending `book_id` | Deterministic, reproducible `applied[]`/`failed[]` ordering. | n |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Broadcast bulk edit via single-token plan→confirm ⭐ MVP

**User Story**: As the library owner, I want to apply one set of field changes to many books in a
single reviewed call, so that routine multi-book edits (set series, publisher, rating, retag) stop
requiring the Calibre GUI or N separate confirmations.

**Why P1**: This is the highest-frequency GUI action and the Phase-2 phase-gate's core; every ORGN
feature depends on it.

**Acceptance Criteria**:

1. WHEN `update_metadata_bulk(book_ids, fields)` is called **without** a token THEN the system SHALL
   return a plan containing a per-book `current → proposed` diff for every existing id **and** a
   single deterministic `confirmation_token`, and SHALL write nothing. *(BEDIT-01)*
2. WHEN the apply call passes the token that matches the exact `(sorted book_ids, fields, list_mode)`
   THEN the system SHALL take exactly one `metadata.db` backup **before** the first write (AD-011),
   apply the fields to each book via `calibredb set_metadata`, and return the backup path. *(BEDIT-02, BEDIT-05)*
3. WHEN the apply call passes a token that does not match the recomputed batch token THEN the system
   SHALL refuse with a clear error and write nothing (reuse `confirmation.verify`). *(BEDIT-03)*
4. WHEN one book fails to apply (calibredb error, or an id that no longer exists) THEN the system
   SHALL still apply the remaining books and return `applied: [ids]` and `failed: [{book_id, error}]`
   — never aborting the batch, never reporting a fake "all succeeded". *(BEDIT-04)*
5. WHEN the batch applies successfully for a book THEN the system SHALL re-read that book's affected
   fields and include the resulting values in the report, so success is demonstrated, not asserted. *(BEDIT-07)*
6. WHEN `book_ids` is empty, contains a duplicate, or contains a non-integer, OR `fields` is empty,
   names an unknown field, or carries an out-of-range value (e.g. rating outside 0–10) THEN the
   system SHALL reject the call as invalid input **before** any backup or write. *(BEDIT-06)*

**Independent Test**: Bootstrap a scratch library with 3 books; plan a `{series: "X"}` edit over all
3, get a token + 3-book diff with no write; apply with the token and assert all 3 books read back
`series = X` and exactly one backup exists. Then force one id to fail (unknown id in the list) and
assert the other two still applied and the failed id is reported.

---

### P1: List-field add / remove / replace modes ⭐ MVP

**User Story**: As the library owner, I want to *add* a tag to many books (or *remove* one) without
wiping their other tags, so bulk tagging behaves like the GUI's bulk-tag action instead of a
destructive overwrite.

**Why P1**: Broadcast-*replace* of a list field is a footgun ("add scifi" would erase every book's
other tags); add/remove is what makes broadcasting list fields actually usable. User confirmed it is
in BULK-01 scope, not deferred.

**Acceptance Criteria**:

1. WHEN `list_mode = "add"` THEN for each book the system SHALL set the field to the **union** of the
   book's current values and the supplied values (existing values preserved). *(BEDIT-08)*
2. WHEN `list_mode = "remove"` THEN for each book the system SHALL set the field to the book's current
   values **minus** the supplied values (values not present are ignored). *(BEDIT-08)*
3. WHEN `list_mode = "replace"` (default, or omitted) THEN for each book the system SHALL overwrite
   the field with exactly the supplied values (today's `set_metadata` semantics). *(BEDIT-08)*
4. WHEN a plan is produced under any `list_mode` THEN the per-book diff SHALL show the **true
   resulting set** for that book (post-union/difference), not the raw supplied list — so the review
   reflects what will actually be written. *(BEDIT-08)*
5. WHEN `add` is applied for a value a book already has, or `remove` for a value it lacks THEN the
   result for that book SHALL be a no-op that still reports as `applied` (idempotent). *(BEDIT-09)*

**Independent Test**: Scratch library, book with tags `[a, b]`. Apply `add {tags:[b, c]}` → book reads
`[a, b, c]` (b not duplicated). Apply `remove {tags:[a, z]}` → book reads `[b, c]` (z absent, no error).

---

## Edge Cases

- WHEN `book_ids` has one id THEN the system SHALL still run the full plan→confirm path (degenerate
  batch, not an error).
- WHEN an id is absent at plan time THEN the plan SHALL list it as not-found (no diff) and it SHALL
  land in `failed[]` at apply — consistent with BEDIT-04, not a hard abort.
- WHEN `list_mode = "remove"` empties a book's list field THEN the system SHALL write the empty set
  (allowed; the diff shows `[…] → []`).
- WHEN `list_mode` is any value other than `replace`/`add`/`remove` THEN the system SHALL reject it as
  invalid input before any write (BEDIT-06).
- WHEN `list_mode` is supplied but `fields` contains no list field THEN the system SHALL reject it as
  invalid input (a `list_mode` with nothing to apply it to is a caller error).
- WHEN books are processed THEN the order SHALL be ascending `book_id` for deterministic reporting.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| BEDIT-01 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-02 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-03 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-04 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-05 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-06 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-07 | P1: Broadcast bulk edit | Design | In Design |
| BEDIT-08 | P1: List-field modes | Design | In Design |
| BEDIT-09 | P1: List-field modes | Design | In Design |

**ID format:** `BEDIT-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 9 total, 0 mapped to tasks yet (Tasks phase pending), 0 unmapped.

---

## Success Criteria

- [ ] A batch retag / re-series / re-publisher of many books completes in one plan + one apply, no
      Calibre GUI.
- [ ] `list_mode = "add"` on N books preserves every book's existing list values (zero destructive
      overwrites).
- [ ] A forced per-book failure yields a truthful `failed[]` entry and does not block the other
      books — never a false "all succeeded".
- [ ] Every applied batch is preceded by exactly one `metadata.db` backup; invalid input never
      reaches a backup or write.
