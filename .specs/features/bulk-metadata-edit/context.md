# Bulk Metadata Edit (BULK-01) Context

**Gathered:** 2026-07-20
**Spec:** `.specs/features/bulk-metadata-edit/spec.md`
**Status:** Ready for design

---

## Feature Boundary

Apply one broadcast set of metadata fields to N `book_ids` in a single plan→confirm call, reusing
the Verified `update_metadata` / backup / confirmation-token machinery. Includes list-field
`add`/`remove`/`replace` modes for `tags`/`authors`. Does **not** include per-book distinct edits,
transactional rollback, bulk convert/import, or the ORGN organization features.

---

## Implementation Decisions

### Field application model

- **Broadcast**: one `fields` dict applied identically to every `book_id`. Per-book distinct edits
  stay out of scope (achievable by looping the existing single-book `update_metadata`).

### Confirmation token scope

- **Single batch token** hashing `(sorted book_ids, fields, list_mode)`. One review, one apply.
  AD-012 still holds because the plan surfaces a per-book `current → proposed` diff for every book;
  tampering with any id, field, or mode invalidates the recomputed token (reuse
  `confirmation.verify`).

### Partial-failure contract

- **Best-effort per-book.** A per-book calibredb failure or a vanished id does not abort the batch;
  the result reports `applied: [ids]` and `failed: [{book_id, error}]`. Exactly one `metadata.db`
  backup is taken before the first write and returned as the rollback point. No auto-restore.

### List-field semantics (user override of the agent's replace-only recommendation)

- `list_mode ∈ {replace (default), add, remove}` applies to the list fields present in `fields`
  (`tags`, `authors`).
- `add` = union of the book's current values with the supplied values; `remove` = set difference;
  `replace` = overwrite (today's semantics).
- Computed **per book** from the read layer (`SqliteReader`), then written via `set_metadata`
  (which replaces) with the computed set — a compound orchestration on existing primitives, no new
  runner method. This mirrors how ORGN-01/02 are described in the roadmap.
- The plan diff shows the **true resulting set** per book, not the raw supplied list.

### Agent's Discretion

- Exact tool signature shape for `list_mode` (top-level param vs. per-field) — defaulted to a single
  batch-level `list_mode` param; Design may refine.
- Whether the applied report re-reads only affected fields or the full record — defaulted to affected
  fields for a lean payload.
- Processing order — defaulted to ascending `book_id` for deterministic reporting.

### Declined / Undiscussed Gray Areas → Assumptions

- Duplicate-id handling, non-existent-id handling, invalid-field abort behavior, tool naming, and
  `list_mode`-on-authors were not separately debated; each is recorded in the spec's **Assumptions &
  Open Questions** table with a chosen default and rationale.

---

## Specific References

- Reuse `confirmation.plan_token` / `confirmation.verify`, `backup.backup_metadata_db`,
  `CalibredbRunner.set_metadata`, and `SqliteReader.get_book` — no new subprocess or network
  surface (AD-001, AD-005, AD-014 unchanged).
- Honesty contract mirrors BULK-02/BULK-03 as stated in `ROADMAP.md` (per-item report, never a fake
  all-succeeded).

---

## Deferred Ideas

- **Per-book distinct field maps** — a future enhancement if looping single-book edits proves
  insufficient.
- **Per-field list modes** (different mode per list field in one call) — only if a real need appears.
- **Search-and-replace field edits** (GUI bulk S&R) — separate capability, not requested.
- **Transactional all-or-nothing apply with auto-restore** — would need a new restore mechanism; not
  chosen for BULK-01.
