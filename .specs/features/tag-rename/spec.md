# Rename a Tag Across the Library (ORGN-02) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md)
**Feature id:** ORGN-02
**Requirement prefix:** `TRENAME`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md.
ORGN-02 is the tag-scoped sibling of ORGN-01 (`author-rename`, Verified 2026-07-30); every genuine
gray area (merge-on-rename, tag-not-found, exact matching, no cap) was already resolved with the
user for ORGN-01 and carries over here by precedent — nothing new is left silently unclear.

## Problem Statement

Fixing a tag today means editing every book carrying it one at a time — the GUI's "rename tag"
(Tag Browser → right-click → Rename) has no MCP equivalent. Worse, a naive bulk edit of the `tags`
field would **overwrite** each book's whole tag set, erasing its other tags. ORGN-02 renames one tag
everywhere in a single reviewed call: it discovers every book carrying `old_tag`, computes each
book's new tag list (swapping only `old_tag` for `new_tag`, keeping every other tag), and applies
the change best-effort behind the plan→confirm gate — the honest, other-tag-safe rename the GUI
does, N-wide.

It rides the **already-corrected** shared write primitive: unlike ORGN-01 (which had to fix
`set_metadata`'s author serialization from `,` to ` & `), tags are already serialized with `,`
(AD-022), so ORGN-02 needs **no** prerequisite fix — it is pure reuse.

## Goals

- [ ] Rename one tag across the whole library in a single plan→confirm call: discover every book
      carrying `old_tag` (exact match), and for each replace only `old_tag` with `new_tag`,
      **preserving every other tag** — never an overwrite of the tag set.
- [ ] Gate the change behind AD-012/AD-020: one batch-wide `confirmation_token` over the discovered
      set, a plan showing each affected book's `tags: current → proposed`, and exactly one
      `metadata.db` backup before the first write (AD-011). Rename mutates existing metadata across
      N books, so it is not additive — it is reviewed before it writes.
- [ ] Honest partial-failure (AD-020): a per-book failure never voids the batch and never reports a
      fake "all succeeded" — `applied[]` / `failed[]` reported per book.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Case-insensitive / fuzzy `old_tag` matching | Mirrors ORGN-01: match is **exact** (Calibre keys each tag as a distinct entity; case-insensitive matching risks renaming a tag you did not mean to, and silently merging two you meant to keep apart). Fixing a case/spelling variant is done by typing the exact current string as `old_tag`. |
| **Deleting** a tag (rename-to-nothing) | ORGN-02 only *replaces* `old_tag` with a non-blank `new_tag`; a book carrying `old_tag` always ends with `new_tag`. Removing a tag entirely is a distinct capability, not requested. |
| A dedicated tag-**merge** tool (many tags → one) | Merge happens here only as a *consequence* of renaming onto an existing tag (Assumptions); a first-class N-tag merge is a separate capability, not requested. |
| Author rename (ORGN-01), duplicate-group merge (ORGN-03) | ORGN-01 is Verified; ORGN-03 is a separate Phase-2 feature — same AD-020 pattern, different discovery/apply target (a group merge deletes book records). |
| Renaming other flat-set fields (`languages`, custom columns) | Same shape, not requested. If picked up later it reuses the same generalized resolver ORGN-02 establishes. |
| Per-book distinct edits / arbitrary bulk field broadcast (BULK-01) | BULK-01 broadcasts one identical `fields` map to all books; a rename needs a **per-book distinct** tag list, so it consumes the lower primitives + the AD-020 pattern, not `update_metadata_bulk`. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear. Every row inherits an
ORGN-01 decision confirmed with the user on 2026-07-30; "Confirmed?" = y (by precedent) unless noted.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| `old_tag` → existing tag already named `new_tag` (merge) | **Allowed** — books consolidate onto `new_tag`; a book carrying both collapses to a single `new_tag` | ORGN-01 precedent: a rename onto an existing name is usually the intent (fixing a variant like `sci-fi`→`Science Fiction`). Recoverable via the one backup; idempotent (re-running is a no-op). | y (precedent) |
| `old_tag` matches **no** tag | **Reject** as invalid input with a clear "tag not found", at plan time, before any backup | ORGN-01 precedent: a rename of a non-existent tag is almost always a typo; a silent zero-change success would mislead. | y (precedent) |
| Tag matching | **Exact** string match (case-sensitive), matching how the tag join keys entities | Exact keeps the operation to the tag the user named; a fuzzy/case-insensitive match could rename or merge tags unintentionally. A case variant is fixed by typing the exact current string. | y (precedent) |
| Reused apply mechanism | The **AD-020 best-effort pattern** (validate → one backup → `sorted` best-effort loop → `applied`/`failed`) + the AD-012 plan→confirm token — over the lower primitives (`set_metadata`, `backup`, `plan_token`/`verify`, reader), **not** `update_metadata_bulk` | Rename needs a per-book *distinct* resolved tag list; BULK-01 broadcasts identical fields (its own Out-of-Scope). Batch identity bound in the token via the sentinel id + `{old_tag, new_tag, book_ids}` payload (AD-020). | y (precedent) |
| Other-tag handling | Replace **only** `old_tag` with `new_tag` in-place; preserve every other tag | A book tagged `[old_tag, other]` must become `[new_tag, other]`, never `[new_tag]`. Overwriting the whole tag set is the exact footgun this feature exists to avoid. | y |
| `new_tag` already present on a book (in-book dedupe) | The resulting list contains `new_tag` **once** (order-preserving dedupe) | `[old_tag, new_tag]` → `[new_tag]`; a book cannot carry the same tag twice. Same merge principle applied within one book. | y |
| No prerequisite serialization fix | **None needed** | AD-022 already joins `tags` with `,` (the fix ORGN-01 made for `authors`→` & ` does not touch tags). ORGN-02 is pure reuse of the corrected primitive. | y |
| Resolve-list logic | **Reuse the identical pure rule** ORGN-01 established (replace old→new, order-preserving dedupe/merge) — generalized to a shared value-rename resolver, not cloned | The rule is byte-for-byte the same set operation as authors; a shared business rule is centralized, not duplicated (AGENTS.md). Design decides the exact module shape. | y |
| Batch size cap | **No cap** | Like ORGN-01/BULK-01: the affected set is *discovered*, not user-supplied, and a correct rename must cover **all** of a tag's books — a cap would make it silently partial and wrong. | y |
| `new_tag` validation | Reject empty/blank `new_tag`, and reject `new_tag == old_tag` (a no-op rename) as invalid input before any backup | An empty tag or a rename to the same tag has no valid interpretation; fail fast. | y |
| Processing order | Ascending `book_id` over the discovered set | Deterministic, reproducible `applied[]`/`failed[]` ordering (AD-020 `sorted` discipline). | y |
| Backup when the rename applies | Exactly one `metadata.db` backup before the first write (never per book) | AD-011/AD-020 single rollback point for the whole batch. | y |
| `applied[]` payload | Re-read each applied book's resulting `tags` list | Demonstrates success rather than asserting it (project principle), consistent with ORGN-01/BULK-01. Note: Calibre re-reads tags alphabetically (`ORDER BY t.name`), so the re-read reflects the stored *set*, not the plan's positional order — set equality is what is asserted. | y |
| Orphaned `old_tag` entity after the last book loses it | Left to Calibre (it prunes unused tags on DB touch); not explicitly deleted | Mirrors ORGN-01's stance on orphaned author entities — the operation changes each book's *tags*, not the tag table directly (AD-001: writes via `calibredb`, not SQL). | y |
| A book that vanishes between plan and apply | Not a hard abort — lands in `failed[]` at apply (best-effort) | AD-020: one bad/absent id never sinks the batch. Also protected by the token: if the affected set changed since the plan, the recomputed token mismatches and the apply is refused (re-plan). | y |
| Where tag-by-name discovery lives | New read-layer method `SqliteReader.books_by_tag(name)` | Reads stay in the read layer (AD-001/AD-017); exact-match query on the `tags`/`books_tags_link` join, mirroring `books_by_author`. | y |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Rename a tag everywhere via one reviewed call ⭐ MVP

**User Story**: As the library owner, I want to point at one tag and rename it across every book
carrying it in a single reviewed call, so that fixing a misspelled or variant tag (e.g. merging
`sci-fi` into `Science Fiction`) stops requiring the Calibre GUI or one `update_metadata` per book.

**Why P1**: This is the Tag-Browser "rename tag" action — a Phase-2 phase-gate item ("retag a batch
… never requires opening the Calibre GUI") — and the plan→confirm gate is what makes a multi-book
metadata overwrite trustworthy.

**Acceptance Criteria**:

1. WHEN `rename_tag(old_tag, new_tag)` is called **without** a token THEN the system SHALL discover
   every book carrying `old_tag` (exact match), return a plan listing each affected book's
   `tags: current → proposed` (the per-book *resolved* list — `old_tag` replaced by `new_tag`, other
   tags preserved, in-book dedupe applied) **and** a single deterministic `confirmation_token` over
   the discovered set, and SHALL write nothing. *(TRENAME-01)*
2. WHEN `old_tag` matches no tag in the library THEN the system SHALL reject the call as invalid
   input ("tag not found") at plan time, **before** any backup or write. *(TRENAME-02)*
3. WHEN `new_tag` is empty/blank, OR `new_tag == old_tag` THEN the system SHALL reject the call as
   invalid input **before** any backup or write. *(TRENAME-03)*
4. WHEN the apply call passes the token that matches the exact
   `(old_tag, new_tag, sorted discovered book_ids)` THEN the system SHALL take exactly one
   `metadata.db` backup **before** the first write (AD-011), apply each affected book's resolved tag
   list via `calibredb set_metadata`, and return the backup path. *(TRENAME-04)*
5. WHEN the apply call passes a token that does not match the recomputed batch token (e.g. the
   affected set changed since the plan) THEN the system SHALL refuse with a clear error and write
   nothing (reuse `confirmation.verify`). *(TRENAME-05)*
6. WHEN one book fails to apply (`calibredb` error, or an id that no longer exists) THEN the system
   SHALL still apply the remaining books and return `applied: [{book_id, tags}]` and
   `failed: [{book_id, error}]` — never aborting the batch, never reporting a fake "all succeeded".
   *(TRENAME-06)*
7. WHEN a book applies successfully THEN the system SHALL re-read that book's `tags` and include the
   resulting list in the report, so success is demonstrated, not asserted. *(TRENAME-08)*

**Independent Test**: Bootstrap a scratch library with 3 books — one tagged `["old-tag"]`, one
`["old-tag", "keep"]`, and one `["unrelated"]`. Plan `rename_tag("old-tag", "new-tag")`: assert the
plan lists exactly the first two books with `proposed` tag *sets* `{"new-tag"}` and
`{"new-tag", "keep"}` respectively (other tag preserved, third book untouched), a token is returned,
and nothing is written. Apply with the token: assert both books read back the new tag sets, the third
is unchanged, exactly one backup exists, and `applied` has 2 entries / `failed` is empty. Then plan a
rename of a non-existent tag and assert it is rejected before any backup.

---

### P1: Other-tag-safe replacement & merge ⭐ MVP

**User Story**: As the library owner, I want renaming a tag to change **only** that tag on each book
— keeping its other tags intact — and to consolidate onto an existing tag when I rename to one, so
that a rename behaves like the GUI's rename (and de-dupes variants) instead of a destructive
overwrite.

**Why P1**: Other-tag preservation is what separates a correct rename from a data-losing bulk
overwrite; merge-onto-existing is the confirmed intent when consolidating variant tags. Without this
the feature is unsafe to ship.

**Acceptance Criteria**:

1. WHEN a book carries `old_tag` alongside one or more other tags THEN the resulting tag list SHALL
   replace **only** `old_tag` with `new_tag`, preserving every other tag (as a set) — e.g.
   `["a", "old", "b"]` → contains exactly `{"a", "new", "b"}`. *(TRENAME-07)*
2. WHEN a book carries **both** `old_tag` and `new_tag` THEN the resulting list SHALL contain
   `new_tag` exactly once, with the duplicate removed (order-preserving in-book dedupe) — e.g.
   `["old", "new"]` → `["new"]`. *(TRENAME-07)*
3. WHEN `new_tag` already exists as a separate tag in the library THEN the rename SHALL still apply
   (books consolidate onto `new_tag`) — a merge is allowed, not rejected. *(TRENAME-07)*

**Independent Test**: Scratch library, one book tagged `["old", "new"]` (both already present) and
one `["x", "old"]`. Rename `old → new`: assert the first book reads back `{"new"}` (single, deduped)
and the second `{"x", "new"}` (other tag preserved). Re-run the same rename and assert it is now
rejected as "tag not found" (no book carries `old` anymore) — proving the rename fully consumed the
old tag.

---

## Edge Cases

- WHEN exactly one book carries `old_tag` THEN the system SHALL still run the full plan→confirm path
  (degenerate batch, not an error).
- WHEN `old_tag` matches no tag THEN the system SHALL reject before any backup (TRENAME-02) — not
  return an empty success.
- WHEN a book somehow lists `old_tag` more than once (a data anomaly) THEN every occurrence SHALL be
  replaced by a single `new_tag`, deduped.
- WHEN the affected set changes between plan and apply (a book gained/lost `old_tag`) THEN the
  recomputed token SHALL mismatch and the apply SHALL be refused (TRENAME-05) — the user re-plans.
- WHEN one book fails to apply THEN the remaining books SHALL still apply and the failure SHALL be
  reported per book (TRENAME-06) — never a false "all renamed".
- WHEN books are processed THEN the order SHALL be ascending `book_id` for deterministic reporting.
- WHEN `new_tag` differs from `old_tag` only by case (e.g. `"scifi"` → `"SciFi"`) THEN it SHALL be a
  valid rename (not treated as a no-op), since the two are distinct tag entities.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| TRENAME-01 | P1: Rename via one reviewed call | Implementing | Implementing |
| TRENAME-02 | P1: Rename via one reviewed call | Implementing | Implementing |
| TRENAME-03 | P1: Rename via one reviewed call | Implementing | Implementing |
| TRENAME-04 | P1: Rename via one reviewed call | Implementing | Implementing |
| TRENAME-05 | P1: Rename via one reviewed call | Implementing | Implementing |
| TRENAME-06 | P1: Rename via one reviewed call | Implementing | Implementing |
| TRENAME-07 | P1: Other-tag-safe replacement & merge | Implementing | Implementing |
| TRENAME-08 | P1: Rename via one reviewed call | Implementing | Implementing |

**ID format:** `TRENAME-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 8 total, 8 mapped to tasks (T1..T4). Implemented across commits on `feat/author-rename`;
flips to `Verified` after the independent Verifier passes (author does not self-mark Verified).
Design at `.specs/features/tag-rename/design.md`.

---

## Success Criteria

How we know the feature is successful:

- [ ] A misspelled/variant tag is fixed across every book in one plan + one apply, no Calibre GUI.
- [ ] Renaming never erases another tag: every book keeps all its other tags.
- [ ] Renaming onto an existing tag consolidates (merges) cleanly, deduping within any book carrying
      both — never a doubled tag.
- [ ] A rename of a non-existent tag is rejected before any backup; `new_tag` empty or equal to
      `old_tag` is rejected too.
- [ ] A forced per-book failure yields a truthful `failed[]` entry and does not block the other books
      — never a false "all renamed".
- [ ] Every applied rename is preceded by exactly one `metadata.db` backup, and is provably the
      reviewed operation (token over `old_tag`/`new_tag`/discovered ids).
