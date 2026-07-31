# Rename an Author Across the Library (ORGN-01) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md)
**Feature id:** ORGN-01
**Requirement prefix:** `ARENAME`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md
(the two genuine gray areas — merge-on-rename and author-not-found — resolved with the user at
Specify time, 2026-07-30).

## Problem Statement

Fixing an author's name today means editing every book credited to them one at a time — the GUI's
"rename author" (Tag Browser → right-click → Rename) has no MCP equivalent. Worse, a naive bulk edit
of the `authors` field would **overwrite** each book's whole author list, erasing co-authors.
ORGN-01 renames one author everywhere in a single reviewed call: it discovers every book credited to
`old_name`, computes each book's new author list (swapping only `old_name` for `new_name`, keeping
every co-author), and applies the change best-effort behind the plan→confirm gate — the honest,
co-author-safe rename the GUI does, N-wide.

## Goals

- [ ] Rename one author across the whole library in a single plan→confirm call: discover every book
      credited to `old_name` (exact match), and for each replace only `old_name` with `new_name`,
      **preserving every co-author and their order** — never an overwrite of the author list.
- [ ] Gate the change behind AD-012/AD-020: one batch-wide `confirmation_token` over the discovered
      set, a plan showing each affected book's `authors: current → proposed`, and exactly one
      `metadata.db` backup before the first write (AD-011). Rename mutates existing metadata across
      N books, so it is not additive — it is reviewed before it writes.
- [ ] Honest partial-failure (AD-020): a per-book failure never voids the batch and never reports a
      fake "all succeeded" — `applied[]` / `failed[]` reported per book.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Case-insensitive / fuzzy `old_name` matching | User-adjacent decision: match is **exact** (Calibre stores each author as a distinct entity; case-insensitive matching risks renaming an author you did not mean to, and silently merging two you meant to keep apart). Fixing a case/spelling variant is done by typing the exact current string as `old_name`. |
| A dedicated author-**merge** tool (many authors → one) | Merge happens here only as a *consequence* of renaming onto an existing name (Assumptions); a first-class N-author merge is a separate capability, not requested. |
| Splitting one author into several | The inverse operation; not requested, different semantics. |
| Editing the `authors` table entity directly (author sort name, author link/URL) | ORGN-01 changes each book's **credit** via `calibredb set_metadata`; it does not edit author-entity fields. `author_sort` is left for Calibre to recompute from the new name. |
| Tag rename (ORGN-02), duplicate-group merge (ORGN-03) | Separate Phase-2 features — same AD-020 pattern, different discovery/apply target (tags are a flat set; a group merge deletes book records). Built next, not here. |
| Per-book distinct edits / arbitrary bulk field broadcast (BULK-01) | BULK-01 broadcasts one identical `fields` map to all books; a rename needs a **per-book distinct** author list, so it consumes the lower primitives + the AD-020 pattern, not `update_metadata_bulk`. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| `old_name` → existing author already named `new_name` (merge) | **Allowed** — books consolidate onto `new_name`; a book credited to both collapses to a single `new_name` | User decision (2026-07-30): a rename onto an existing name is usually the intent (fixing a variant spelling). Recoverable via the one backup; idempotent (re-running is a no-op). | y |
| `old_name` matches **no** author | **Reject** as invalid input with a clear "author not found", at plan time, before any backup | User decision (2026-07-30): a rename of a non-existent author is almost always a typo; a silent zero-change success would mislead. | y |
| Name matching | **Exact** string match (case-sensitive), matching how Calibre keys author entities | Exact keeps the operation to the author the user named; a fuzzy/case-insensitive match could rename or merge authors unintentionally. | y (implied by Out-of-Scope decision) |
| Reused apply mechanism | The **AD-020 best-effort pattern** (validate → one backup → `sorted` best-effort loop → `applied`/`failed`) + the AD-012 plan→confirm token — over the lower primitives (`set_metadata`, `backup`, `plan_token`/`verify`, reader), **not** `update_metadata_bulk` | Rename needs a per-book *distinct* resolved author list; BULK-01 broadcasts identical fields (its own Out-of-Scope). The batch identity is bound in the token via a sentinel id + `{old_name, new_name, book_ids}` payload (AD-020). | y |
| Co-author handling | Replace **only** `old_name` with `new_name` in-place; preserve every other author and the list order | A book by `[old_name, co_author]` must become `[new_name, co_author]`, never `[new_name]`. Overwriting the whole author list is the exact footgun this feature exists to avoid. | y |
| `new_name` already present as a co-author on a book (in-book dedupe) | The resulting list contains `new_name` **once** (order-preserving dedupe) | `[old_name, new_name]` → `[new_name]`; a book cannot list the same author twice. Same merge principle applied within one book. | y |
| Batch size cap | **No cap** | Unlike folder-import/bulk-convert (subprocess-heavy), the affected set is *discovered*, not user-supplied, and a correct rename must cover **all** of an author's books — a cap would make it silently partial and wrong. Mirrors BULK-01 (no size cap). | y |
| `new_name` validation | Reject empty/blank `new_name`, and reject `new_name == old_name` (a no-op rename) as invalid input before any backup | An empty author or a rename to the same name has no valid interpretation; fail fast. | y |
| Processing order | Ascending `book_id` over the discovered set | Deterministic, reproducible `applied[]`/`failed[]` ordering (AD-020 `sorted` discipline). | y |
| Backup when the rename applies | Exactly one `metadata.db` backup before the first write (never per book) | AD-011/AD-020 single rollback point for the whole batch. | y |
| `applied[]` payload | Re-read each applied book's resulting `authors` list | Demonstrates success rather than asserting it (project principle), consistent with BULK-01's affected-fields re-read. | y |
| A book that vanishes between plan and apply | Not a hard abort — lands in `failed[]` at apply (best-effort) | AD-020: one bad/absent id never sinks the batch. Also protected by the token: if the affected set changed since the plan, the recomputed token mismatches and the apply is refused (re-plan). | y |
| Where author-by-name discovery lives | New read-layer method `SqliteReader.books_by_author(name)` | Reads stay in the read layer (AD-001/AD-017); mirrors `format_files`' reader-layer discipline. Exact-match query on the `authors`/`books_authors_link` join. | y (Design confirms shape) |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Rename an author everywhere via one reviewed call ⭐ MVP

**User Story**: As the library owner, I want to point at one author name and rename it across every
book credited to them in a single reviewed call, so that fixing a misspelled or variant author name
stops requiring the Calibre GUI or one `update_metadata` per book.

**Why P1**: This is the Tag-Browser "rename author" action — a Phase-2 phase-gate item ("fix an
author's name everywhere never requires opening the GUI") — and the plan→confirm gate is what makes
a multi-book metadata overwrite trustworthy.

**Acceptance Criteria**:

1. WHEN `rename_author(old_name, new_name)` is called **without** a token THEN the system SHALL
   discover every book credited to `old_name` (exact match), return a plan listing each affected
   book's `authors: current → proposed` (the per-book *resolved* list — `old_name` replaced by
   `new_name`, co-authors and order preserved, in-book dedupe applied) **and** a single deterministic
   `confirmation_token` over the discovered set, and SHALL write nothing. *(ARENAME-01)*
2. WHEN `old_name` matches no author in the library THEN the system SHALL reject the call as invalid
   input ("author not found") at plan time, **before** any backup or write. *(ARENAME-02)*
3. WHEN `new_name` is empty/blank, OR `new_name == old_name` THEN the system SHALL reject the call as
   invalid input **before** any backup or write. *(ARENAME-03)*
4. WHEN the apply call passes the token that matches the exact
   `(old_name, new_name, sorted discovered book_ids)` THEN the system SHALL take exactly one
   `metadata.db` backup **before** the first write (AD-011), apply each affected book's resolved
   author list via `calibredb set_metadata`, and return the backup path. *(ARENAME-04)*
5. WHEN the apply call passes a token that does not match the recomputed batch token (e.g. the
   affected set changed since the plan) THEN the system SHALL refuse with a clear error and write
   nothing (reuse `confirmation.verify`). *(ARENAME-05)*
6. WHEN one book fails to apply (`calibredb` error, or an id that no longer exists) THEN the system
   SHALL still apply the remaining books and return `applied: [{book_id, authors}]` and
   `failed: [{book_id, error}]` — never aborting the batch, never reporting a fake "all succeeded".
   *(ARENAME-06)*
7. WHEN a book applies successfully THEN the system SHALL re-read that book's `authors` and include
   the resulting list in the report, so success is demonstrated, not asserted. *(ARENAME-08)*

**Independent Test**: Bootstrap a scratch library with 3 books — one credited to `["Old Name"]`, one
to `["Old Name", "Co Author"]`, and one to `["Someone Else"]`. Plan `rename_author("Old Name",
"New Name")`: assert the plan lists exactly the first two books with `proposed` `["New Name"]` and
`["New Name", "Co Author"]` respectively (co-author preserved, third book untouched), a token is
returned, and nothing is written. Apply with the token: assert both books read back the new author
lists, the third is unchanged, exactly one backup exists, and `applied` has 2 entries / `failed` is
empty. Then plan a rename of a non-existent author and assert it is rejected before any backup.

---

### P1: Co-author-safe replacement & merge ⭐ MVP

**User Story**: As the library owner, I want renaming an author to change **only** that author on each
book — keeping co-authors intact — and to consolidate onto an existing name when I rename to one, so
that a rename behaves like the GUI's rename (and de-dupes variants) instead of a destructive overwrite.

**Why P1**: Co-author preservation is what separates a correct rename from a data-losing bulk
overwrite; merge-onto-existing is the confirmed intent when consolidating variant spellings. Without
this the feature is unsafe to ship.

**Acceptance Criteria**:

1. WHEN a book is credited to `old_name` alongside one or more co-authors THEN the resulting author
   list SHALL replace **only** `old_name` with `new_name`, preserving every co-author and the
   original order (e.g. `["A", "Old", "B"]` → `["A", "New", "B"]`). *(ARENAME-07)*
2. WHEN a book is credited to **both** `old_name` and `new_name` THEN the resulting list SHALL contain
   `new_name` exactly once, in `old_name`'s former position, with the pre-existing `new_name`
   occurrence removed (order-preserving in-book dedupe) — e.g. `["Old", "New"]` → `["New"]`. *(ARENAME-07)*
3. WHEN `new_name` already exists as a separate author in the library THEN the rename SHALL still
   apply (books consolidate onto `new_name`) — a merge is allowed, not rejected. *(ARENAME-07)*

**Independent Test**: Scratch library, one book credited to `["Old", "New"]` (both already present)
and one to `["X", "Old"]`. Rename `Old → New`: assert the first book reads back `["New"]` (single,
deduped) and the second `["X", "New"]` (order preserved). Re-run the same rename and assert it is now
rejected as "author not found" (no book is credited to `Old` anymore) — proving the rename fully
consumed the old name.

---

## Edge Cases

- WHEN exactly one book is credited to `old_name` THEN the system SHALL still run the full
  plan→confirm path (degenerate batch, not an error).
- WHEN `old_name` matches no author THEN the system SHALL reject before any scan-of-books/backup
  (ARENAME-02) — not return an empty success.
- WHEN a book lists `old_name` more than once (a data anomaly) THEN every occurrence SHALL be replaced
  by a single `new_name`, deduped.
- WHEN the affected set changes between plan and apply (a book added/removed for that author) THEN the
  recomputed token SHALL mismatch and the apply SHALL be refused (ARENAME-05) — the user re-plans.
- WHEN one book fails to apply THEN the remaining books SHALL still apply and the failure SHALL be
  reported per book (ARENAME-06) — never a false "all renamed".
- WHEN books are processed THEN the order SHALL be ascending `book_id` for deterministic reporting.
- WHEN `new_name` differs from `old_name` only by case (e.g. `"old"` → `"Old"`) THEN it SHALL be a
  valid rename (not treated as a no-op), since the two are distinct author entities.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| ARENAME-01 | P1: Rename via one reviewed call | Implementing | Implementing |
| ARENAME-02 | P1: Rename via one reviewed call | Implementing | Implementing |
| ARENAME-03 | P1: Rename via one reviewed call | Implementing | Implementing |
| ARENAME-04 | P1: Rename via one reviewed call | Implementing | Implementing |
| ARENAME-05 | P1: Rename via one reviewed call | Implementing | Implementing |
| ARENAME-06 | P1: Rename via one reviewed call | Implementing | Implementing |
| ARENAME-07 | P1: Co-author-safe replacement & merge | Implementing | Implementing |
| ARENAME-08 | P1: Rename via one reviewed call | Implementing | Implementing |

**ID format:** `ARENAME-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 8 total, 8 mapped to tasks (T1..T5), 0 Verified — independent Verifier run pending.

---

## Success Criteria

How we know the feature is successful:

- [ ] A misspelled/variant author name is fixed across every book in one plan + one apply, no Calibre GUI.
- [ ] Renaming never erases a co-author: every book keeps all its other authors, in order.
- [ ] Renaming onto an existing name consolidates (merges) cleanly, deduping within any book credited
      to both — never a doubled author.
- [ ] A rename of a non-existent author is rejected before any backup; `new_name` empty or equal to
      `old_name` is rejected too.
- [ ] A forced per-book failure yields a truthful `failed[]` entry and does not block the other books
      — never a false "all renamed".
- [ ] Every applied rename is preceded by exactly one `metadata.db` backup, and is provably the
      reviewed operation (token over `old_name`/`new_name`/discovered ids).
