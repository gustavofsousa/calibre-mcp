# Rename/Merge a Series Across the Library (ORGN-04) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md), follow-on gap
**Feature id:** ORGN-04
**Requirement prefix:** `SRENAME`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md.
ORGN-04 is the **series-scoped** sibling of ORGN-01 (`author-rename`, Verified) and ORGN-02
(`tag-rename`, Verified). The shared gray areas (exact matching, not-found rejection, merge-on-rename,
no cap, plan→confirm batch) were resolved with the user for ORGN-01/02 and carry over by precedent.
**What does not carry over:** series is a *single-valued* field (a book has at most one series plus a
`series_index`), so ORGN-04 reuses the sibling **workflow pattern**, not the list resolver
(`resolve_renamed_values` is for multi-valued fields) — and it introduces one field-specific
requirement the siblings do not have: `series_index` preservation.

## Problem Statement

Fixing a series name today means editing every book in it one at a time — the GUI's series rename
(Tag Browser → Series → right-click → Rename) has no MCP equivalent, and a naive per-book
`update_metadata` risks resetting each book's `series_index`. ORGN-04 renames one series across every
book in it in a single reviewed call: it discovers every book whose series is `old_series`, and for
each sets the series to `new_series` **while preserving that book's `series_index`**, behind the
plan→confirm gate.

Unlike ORGN-01 (which had to fix `set_metadata`'s author serialization) ORGN-04 needs **no**
prerequisite fix: `series` is a scalar string field set via `--field series:<name>`; there is no
list-separator concern (AD-022 was about joining multi-valued fields), and setting only the series
name leaves `series_index` untouched (empirically verified against `calibredb`, 2026-07-31 — a book
at `Old #7.5` becomes `New #7.5`).

## Goals

- [ ] Rename one series across the whole library in a single plan→confirm call: discover every book
      whose series is `old_series` (exact match) and set each to `new_series`, **preserving each
      book's `series_index`** — never a reset to `1.0`, never touching a book in a different series.
- [ ] Gate the change behind AD-012/AD-020: one batch-wide `confirmation_token` over the discovered
      set, a plan showing each affected book's `series: current → proposed` (with its index), and
      exactly one `metadata.db` backup before the first write (AD-011). Rename mutates existing
      metadata across N books, so it is reviewed before it writes — not additive.
- [ ] Honest partial-failure (AD-020): a per-book failure never voids the batch and never reports a
      fake "all succeeded" — `applied[]` / `failed[]` reported per book.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Case-insensitive / fuzzy `old_series` matching | Mirrors ORGN-01/02: match is **exact**. Calibre keys each series as a distinct entity; fuzzy matching risks renaming a series you did not mean to. Fix a spelling variant by typing the exact current string as `old_series`. |
| **Renumbering / reindexing** `series_index` (e.g. resolving index collisions after a merge) | ORGN-04 *preserves* each book's existing index verbatim. When `old_series` merges into an existing `new_series`, two books may end up sharing an index — Calibre permits duplicate indices, and renumbering a series is a distinct curation task (belongs to `update_metadata`/a future reindex tool), not requested here. |
| **Changing** a book's `series_index` at all | That is `update_metadata`'s job (EDIT field set). A rename only changes the series *name*. |
| **Deleting** a series (rename-to-nothing) | ORGN-04 only *replaces* `old_series` with a non-blank `new_series`; removing a book from its series entirely is a distinct capability, not requested. |
| A dedicated series-**merge** tool (many series → one) | Merge happens here only as a *consequence* of renaming onto an existing series name (Assumptions); a first-class N-series merge is a separate capability, not requested. |
| Author rename (ORGN-01), tag rename (ORGN-02), duplicate-group merge (ORGN-03) | All Verified / separate features — same AD-020 pattern, different discovery/apply target. |
| Reusing `resolve_renamed_values` (the list resolver) | `series` is single-valued: the proposed value is simply `new_series`, with no in-book dedupe/merge to compute. Applying a list-merge helper here would be degenerate; ORGN-04 reuses the sibling *workflow*, not that helper. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear. Rows marked
"y (precedent)" inherit an ORGN-01/02 decision already confirmed with the user; series-specific rows
are marked "y".

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| `old_series` → existing series already named `new_series` (merge) | **Allowed** — books consolidate onto `new_series`; each keeps its own `series_index` | ORGN-01/02 precedent: renaming onto an existing name is usually the intent (fixing a variant). Recoverable via the one backup; idempotent (re-running is a no-op). | y (precedent) |
| Index collision after a merge (two books at the same index in `new_series`) | **Left as-is** — not renumbered | Calibre permits duplicate `series_index` values; renumbering is a separate curation task (Out of Scope). Preserving each index verbatim is the least-surprising, reversible choice. | y |
| `old_series` matches **no** book | **Reject** as invalid input ("series not found") at plan time, before any backup | ORGN-01/02 precedent: a rename of a non-existent series is almost always a typo; a silent zero-change success would mislead. | y (precedent) |
| Series matching | **Exact** string match (case-sensitive) | Keeps the operation to the series the user named; a fuzzy/case-insensitive match could rename unintentionally. | y (precedent) |
| Single-valued field handling | Proposed value is simply `new_series`; **no list resolve, no in-book dedupe** | A book has at most one series (`books_series_link`, one row); there is no multi-value set to merge within a book. This is the core divergence from ORGN-01/02. | y |
| `series_index` on rename | **Preserved** — the apply sets **only** the `series` field; the index is never included in the write | Empirically verified: `calibredb set_metadata <id> --field series:"New"` leaves `series_index` unchanged. Writing the index too would risk clobbering it. | y |
| Reused apply mechanism | The **AD-020 best-effort pattern** (validate → one backup → `sorted` best-effort loop → `applied`/`failed`) + the AD-012 plan→confirm token — over the lower primitives (`set_metadata`, `backup`, `plan_token`/`verify`, reader), **not** `update_metadata_bulk` | Rename needs a per-book operation keyed off discovery; batch identity bound in the token via the sentinel id + `{old_series, new_series, book_ids}` payload (AD-020). | y (precedent) |
| No prerequisite serialization fix | **None needed** | `series` is a scalar string set via `--field series:<name>`; AD-022's list-join concern does not apply. | y |
| Batch size cap | **No cap** | Like ORGN-01/02: the affected set is *discovered*, not user-supplied; a correct rename must cover **all** of a series' books. | y (precedent) |
| `new_series` validation | Reject empty/blank `new_series`, and reject `new_series == old_series` (a no-op rename), before any backup | No valid interpretation; fail fast. | y (precedent) |
| Processing order | Ascending `book_id` over the discovered set | Deterministic `applied[]`/`failed[]` ordering (AD-020 `sorted` discipline). | y (precedent) |
| Backup when the rename applies | Exactly one `metadata.db` backup before the first write (never per book) | AD-011/AD-020 single rollback point for the whole batch. | y (precedent) |
| `applied[]` payload | Re-read each applied book's resulting `series` **and** `series_index` | Demonstrates success (including index preservation) rather than asserting it. | y |
| Orphaned `old_series` entity after the last book leaves it | Left to Calibre (prunes unused series on DB touch); not explicitly deleted | Mirrors ORGN-01/02 (AD-001: writes via `calibredb`, not SQL). | y (precedent) |
| A book that vanishes between plan and apply | Not a hard abort — lands in `failed[]` at apply (best-effort); also guarded by the token (changed set → mismatch → refuse) | AD-020. | y (precedent) |
| Where series-by-name discovery lives | New read-layer method `SqliteReader.books_by_series(name)` | Reads stay in the read layer (AD-001/AD-017); exact-match query on the `series`/`books_series_link` join, mirroring `books_by_author`/`books_by_tag`. | y |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Rename a series everywhere via one reviewed call ⭐ MVP

**User Story**: As the library owner, I want to point at one series and rename it across every book
in it in a single reviewed call, so that fixing a misspelled or variant series name (e.g. merging
`Foundation Saga` into `Foundation`) stops requiring the Calibre GUI or one `update_metadata` per
book.

**Why P1**: This is the Tag-Browser "rename series" action — a Phase-2 organization item — and the
plan→confirm gate is what makes a multi-book metadata overwrite trustworthy.

**Acceptance Criteria**:

1. WHEN `rename_series(old_series, new_series)` is called **without** a token THEN the system SHALL
   discover every book whose series is `old_series` (exact match), return a plan listing each
   affected book's `series: current → proposed` (proposed = `new_series`, with the book's unchanged
   `series_index` shown) **and** a single deterministic `confirmation_token` over the discovered set,
   and SHALL write nothing. *(SRENAME-01)*
2. WHEN `old_series` matches no book in the library THEN the system SHALL reject the call as invalid
   input ("series not found") at plan time, **before** any backup or write. *(SRENAME-02)*
3. WHEN `new_series` is empty/blank, OR `new_series == old_series` THEN the system SHALL reject the
   call as invalid input **before** any backup or write. *(SRENAME-03)*
4. WHEN the apply call passes the token that matches the exact
   `(old_series, new_series, sorted discovered book_ids)` THEN the system SHALL take exactly one
   `metadata.db` backup **before** the first write (AD-011), set each affected book's series to
   `new_series` via `calibredb set_metadata` (series field only), and return the backup path.
   *(SRENAME-04)*
5. WHEN the apply call passes a token that does not match the recomputed batch token (e.g. the
   affected set changed since the plan) THEN the system SHALL refuse with a clear error and write
   nothing (reuse `confirmation.verify`). *(SRENAME-05)*
6. WHEN one book fails to apply (`calibredb` error, or an id that no longer exists) THEN the system
   SHALL still apply the remaining books and return `applied: [{book_id, series, series_index}]` and
   `failed: [{book_id, error}]` — never aborting the batch, never reporting a fake "all succeeded".
   *(SRENAME-06)*
7. WHEN a book applies successfully THEN the system SHALL re-read that book's `series` and
   `series_index` and include them in the report, so success is demonstrated, not asserted.
   *(SRENAME-08)*

**Independent Test**: Bootstrap a scratch library with 3 books — one with series `Old` at index
`2.0`, one with series `Old` at index `7.5`, and one with series `Other` at index `1.0`. Plan
`rename_series("Old", "New")`: assert the plan lists exactly the first two books with `proposed`
series `New` (indices `2.0`/`7.5` shown unchanged, third book untouched), a token is returned, and
nothing is written. Apply with the token: assert both books read back series `New` **with their
original indices `2.0`/`7.5`**, the third is unchanged, exactly one backup exists, and `applied` has
2 entries / `failed` is empty. Then plan a rename of a non-existent series and assert it is rejected
before any backup.

---

### P1: Index-preserving rename & merge-onto-existing ⭐ MVP

**User Story**: As the library owner, I want renaming a series to change **only** the series name on
each book — keeping each book's position (`series_index`) intact — and to consolidate onto an
existing series when I rename to one, so that a rename behaves like the GUI's rename instead of
scrambling reading order.

**Why P1**: Index preservation is what separates a correct series rename from a destructive one that
resets every book to `1.0`; merge-onto-existing is the confirmed intent when consolidating variant
series names. Without this the feature is unsafe to ship.

**Acceptance Criteria**:

1. WHEN a book in `old_series` has `series_index = X` THEN after the rename that book SHALL have
   series `new_series` and `series_index = X` (unchanged) — the write includes the series field only,
   never the index. *(SRENAME-07)*
2. WHEN `new_series` already exists as a separate series in the library THEN the rename SHALL still
   apply (books consolidate onto `new_series`, each keeping its own index) — a merge is allowed, not
   rejected; index collisions are left as-is (not renumbered). *(SRENAME-07)*

**Independent Test**: Scratch library, one book series `Old` index `3.0` and one already in series
`New` at index `1.0`. Rename `Old → New`: assert the first book reads back series `New` index `3.0`
(index preserved, consolidated into the existing series), the second book unchanged at `New`/`1.0`.
Re-run the same rename and assert it is now rejected as "series not found" (no book is in `Old`
anymore) — proving the rename fully consumed the old series.

---

## Edge Cases

- WHEN exactly one book is in `old_series` THEN the system SHALL still run the full plan→confirm path
  (degenerate batch, not an error).
- WHEN `old_series` matches no book THEN the system SHALL reject before any backup (SRENAME-02) — not
  return an empty success.
- WHEN a book in `old_series` has a fractional/large index (e.g. `7.5`, `12.0`) THEN that exact index
  SHALL survive the rename (SRENAME-07).
- WHEN the affected set changes between plan and apply (a book gained/lost the series) THEN the
  recomputed token SHALL mismatch and the apply SHALL be refused (SRENAME-05) — the user re-plans.
- WHEN one book fails to apply THEN the remaining books SHALL still apply and the failure SHALL be
  reported per book (SRENAME-06) — never a false "all renamed".
- WHEN books are processed THEN the order SHALL be ascending `book_id` for deterministic reporting.
- WHEN `new_series` differs from `old_series` only by case THEN it SHALL be a valid rename (not a
  no-op), since the two are distinct series entities.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| SRENAME-01 | P1: Rename via one reviewed call | Implementing | Implementing |
| SRENAME-02 | P1: Rename via one reviewed call | Implementing | Implementing |
| SRENAME-03 | P1: Rename via one reviewed call | Implementing | Implementing |
| SRENAME-04 | P1: Rename via one reviewed call | Implementing | Implementing |
| SRENAME-05 | P1: Rename via one reviewed call | Implementing | Implementing |
| SRENAME-06 | P1: Rename via one reviewed call | Implementing | Implementing |
| SRENAME-07 | P1: Index-preserving rename & merge | Implementing | Implementing |
| SRENAME-08 | P1: Rename via one reviewed call | Implementing | Implementing |

**ID format:** `SRENAME-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 8 total, 8 mapped to tasks (T1..T3), 8 Implementing — awaiting independent Verifier
PASS to flip to Verified. Design at `.specs/features/series-rename/design.md`.

---

## Success Criteria

How we know the feature is successful:

- [ ] A misspelled/variant series name is fixed across every book in one plan + one apply, no GUI.
- [ ] Every book keeps its `series_index` — reading order is never scrambled by the rename.
- [ ] Renaming onto an existing series consolidates (merges) cleanly; index collisions are left
      as-is, not silently renumbered.
- [ ] A rename of a non-existent series is rejected before any backup; `new_series` empty or equal to
      `old_series` is rejected too.
- [ ] A forced per-book failure yields a truthful `failed[]` entry and does not block the other books
      — never a false "all renamed".
- [ ] Every applied rename is preceded by exactly one `metadata.db` backup, and is provably the
      reviewed operation (token over `old_series`/`new_series`/discovered ids).
</content>
</invoke>
