# Merge a Duplicate Group (ORGN-03) Specification

**Phase:** 2 — Bulk Operations & Library Organization (ROADMAP.md)
**Feature id:** ORGN-03
**Requirement prefix:** `MERGE`
**Context:** the two genuine gray areas were resolved with the user at Specify time (2026-07-31):
survivor selection = **caller passes `survivor_id`**; merge scope = **formats-only + recoverable
delete** (survivor metadata untouched). Recorded inline (Assumptions) — no separate context.md.

## Problem Statement

`find_duplicates` surfaces groups of likely-duplicate books, but resolving one still means the GUI:
manually copy the missing format from one record to another, then delete the leftover. ORGN-03 does
that consolidation in one reviewed call — given a survivor and its losers, it attaches every format
the losers have onto the survivor (never overwriting a format the survivor already holds), then
sends each emptied-out loser to the recycle bin **recoverably**. It is the only Phase-2 organization
feature that **deletes book records**, so it is gated exactly like `remove_book` (plan→confirm,
backup, recoverable trash), extended to a batch with an honest per-loser partial-failure contract.

Unlike a naive "delete the duplicates," ORGN-03 is **data-safe by construction**: a loser is removed
only after all of its formats are provably on the survivor. A loser whose format fails to attach is
left untouched, never deleted.

## Goals

- [ ] Consolidate a duplicate group in one plan→confirm call: attach each loser's formats onto the
      caller-named survivor (`add_format --dont-replace` — the survivor's existing format always
      wins), then recoverably remove each loser.
- [ ] Gate the change like `remove_book` (AD-012) extended batch-wide (AD-020): one batch
      `confirmation_token` over `(survivor_id, sorted loser_ids)`, a plan showing per-loser which
      formats will be added vs. already present and which records will be deleted, exactly one
      `metadata.db` backup before the first mutation (AD-011), and a recoverable trash copy per
      removed loser.
- [ ] Data-safety + honest partial-failure (AD-020): a loser is deleted **only after** its formats
      are on the survivor; a per-loser failure never deletes that loser, never voids the batch, and
      never reports a fake "all merged" — `merged[]` / `failed[]` reported per loser.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| **Metadata / field merge** (inherit survivor's missing cover, comments, publisher, identifiers… from losers) | User decision (2026-07-31): merge is **formats-only**; the survivor's metadata is untouched. Field-level enrichment needs a per-field conflict/precedence policy and is Phase 3 (Enrichment) work, not a merge tool. |
| **Auto survivor selection** (tool picks by most-formats / completeness / lowest id) | User decision (2026-07-31): the **caller passes `survivor_id`** and `loser_ids`. Auto-picking would make a near-irreversible deletion choice on the user's behalf; the host already sees `find_duplicates` output. |
| **Enforcing that survivor+losers form a recognized `find_duplicates` group** | The caller asserts they are duplicates; the plan→confirm review is the safety, not a grouping precondition. Enforcing the normalized-(title,author) grouping would block legitimate merges `find_duplicates` didn't group. The tool validates the ids **exist**, not that they were grouped. |
| **Format conflict resolution beyond survivor-wins** | `add_format --dont-replace` keeps the survivor's copy when both hold the same format; ORGN-03 does not offer "prefer the loser's copy" or content comparison. |
| **Permanent deletion** | Losers go to the recycle bin + a trash copy (recoverable), exactly like `remove_book` — never `--permanent`. |
| Author/tag rename (ORGN-01/02) | Verified siblings — different discovery/apply target; a rename mutates metadata, a merge deletes records. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Survivor selection | Caller passes `survivor_id` (+ explicit `loser_ids`) | User decision (2026-07-31). Human-in-the-loop for a deletion (AD-007/AD-012). | y |
| Merge scope | **Formats-only**, then recoverable-delete losers; survivor metadata untouched | User decision (2026-07-31). Field enrichment is Phase 3. | y |
| Format conflict (survivor and loser both hold format X) | Survivor's copy wins (`add_format --dont-replace`); loser's X reported as "already present", not added | Reuses the existing primitive's behavior; no content comparison in scope. | y |
| Data-safety ordering | Per loser: attach ALL its formats to the survivor first; remove that loser **only if** every attach succeeded | A loser must never be deleted while a format of it is not yet on the survivor — that would lose data. | y |
| Reused apply mechanism | `remove_book`'s recoverable flow (`trash_book_files` + `backup_metadata_db` + `calibredb remove`) + `add_format` + the AD-012 token + AD-020 best-effort per-loser buckets | All primitives already Verified (REM-01..05, ORG-01, CONV-01 `add_format`). ORGN-03 is orchestration, not a new mutation primitive. | y |
| Backup | Exactly one `metadata.db` backup before the first mutation (never per loser) | AD-011/AD-020 single rollback point for the whole batch; plus per-loser trash copies (recoverable). | y |
| Group membership enforcement | **Not enforced** — validate ids exist only | The review is the safety; enforcing grouping blocks legitimate merges (Out of Scope). | y |
| Invalid inputs | Reject before any backup: survivor not found, any loser not found, empty `loser_ids`, `survivor_id` in `loser_ids`, duplicate ids in `loser_ids` | No valid interpretation; fail fast (mirrors REM-03 / ARENAME-03). | y |
| Processing order | Ascending `loser_id` | Deterministic `merged[]`/`failed[]` ordering (AD-020 `sorted` discipline). | y |
| `merged[]` payload | Per removed loser: formats added + its trash location; plus a re-read of the survivor's resulting formats | Demonstrates the consolidation rather than asserting it (project principle). | y |
| A loser that vanishes between plan and apply | Lands in `failed[]` at apply (best-effort); also protected by the token (set change → mismatch → refuse) | AD-020; one bad id never sinks the batch. | y |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Merge a duplicate group in one reviewed call ⭐ MVP

**User Story**: As the library owner, when `find_duplicates` shows the same book twice, I want to name
the record to keep and the ones to fold into it, and in one reviewed call have their formats
consolidated onto the survivor and the leftovers recoverably deleted — so resolving a duplicate stops
requiring the Calibre GUI.

**Why P1**: "resolve a duplicate group … never requires opening the Calibre GUI" is a Phase-2
phase-gate item, and a record-deleting operation is exactly what the plan→confirm + recoverable gate
exists to make trustworthy.

**Acceptance Criteria**:

1. WHEN `merge_duplicate_group(survivor_id, loser_ids)` is called **without** a token THEN the system
   SHALL return a plan: the survivor, and per loser which formats would be **added** vs. **already
   present** on the survivor, that each loser will be **recoverably** deleted, and one deterministic
   `confirmation_token` over `(survivor_id, sorted loser_ids)` — and SHALL write nothing. *(MERGE-01)*
2. WHEN the survivor id, or any loser id, matches no book THEN the system SHALL reject the call
   (`BookNotFoundError`/invalid input) at plan time, **before** any backup or write. *(MERGE-02)*
3. WHEN `loser_ids` is empty, OR `survivor_id` appears in `loser_ids`, OR `loser_ids` contains
   duplicate ids THEN the system SHALL reject the call as invalid input **before** any backup or
   write. *(MERGE-03)*
4. WHEN the apply call passes the token matching `(survivor_id, sorted loser_ids)` THEN the system
   SHALL take exactly one `metadata.db` backup **before** the first mutation (AD-011), and for each
   loser attach its formats onto the survivor via `add_format --dont-replace`, then recoverably
   remove that loser (trash copy + recycle bin), returning the backup path and each loser's trash
   location. *(MERGE-04)*
5. WHEN the apply call passes a token that does not match the recomputed batch token THEN the system
   SHALL refuse with a clear error and write nothing (reuse `confirmation.verify`). *(MERGE-05)*
6. WHEN attaching a loser's format fails THEN the system SHALL **not** remove that loser (data-safe),
   record it in `failed[]`, and still process the remaining losers — never aborting the batch, never
   reporting a fake "all merged". *(MERGE-06)*
7. WHEN a loser holds a format the survivor already has THEN that format SHALL NOT be duplicated on
   the survivor (`--dont-replace`, survivor's copy wins) and SHALL be reported as "already present".
   *(MERGE-07)*
8. WHEN a merge applies THEN the system SHALL re-read the survivor's resulting formats (demonstrating
   the union) and return each removed loser's trash location (recoverable). *(MERGE-08)*

**Independent Test**: Scratch library — survivor `S` holding `[EPUB]`, loser `L1` holding
`[EPUB, PDF]` (EPUB overlaps, PDF is unique), loser `L2` holding `[MOBI]`. Plan
`merge_duplicate_group(S, [L1, L2])`: assert the plan lists `L1` with `formats_to_add==["PDF"]` /
`formats_already_present==["EPUB"]`, `L2` with `formats_to_add==["MOBI"]`, both marked for
recoverable delete, a token is returned, and nothing is written (both losers still present, survivor
still `[EPUB]`). Apply with the token: assert the survivor now holds `{EPUB, PDF, MOBI}`, both losers
are gone (and each `merged[]` entry carries a `trash_location`), exactly one backup exists, and
`failed` is empty. Then plan a merge naming a non-existent loser and assert it is rejected before any
backup.

---

### P1: Data-safe, recoverable deletion ⭐ MVP

**User Story**: As the library owner, I want the merge to never delete a leftover until its unique
formats are provably on the survivor, and to keep every deletion recoverable — so a merge can never
silently lose a file, and a mistaken merge is undoable.

**Why P1**: This is a record-deleting operation; without attach-before-delete ordering and
recoverability it is unsafe to ship.

**Acceptance Criteria**:

1. WHEN a loser is processed THEN its formats SHALL be attached to the survivor **before** that loser
   is removed; IF any attach fails, the loser SHALL NOT be removed. *(MERGE-06)*
2. WHEN a loser is removed THEN it SHALL go to the recycle bin with a trash copy under
   `backups/trash/` (recoverable) — never `--permanent`. *(MERGE-08)*
3. WHEN the batch applies THEN exactly one `metadata.db` backup SHALL be taken before the first
   mutation (AD-011). *(MERGE-04)*

**Independent Test**: Scratch library, survivor `S=[EPUB]`, loser `L=[PDF]`. Monkeypatch
`add_format` to raise for `L`. Apply the merge: assert `L` is **still present** (not removed), `L`
lands in `failed[]`, the survivor is unchanged (`[EPUB]`), and the one backup still exists. Then in a
clean run assert a removed loser's `trash_location` exists on disk (recoverable).

---

## Edge Cases

- WHEN exactly one loser is given THEN the full plan→confirm path still runs (degenerate batch).
- WHEN a loser has **no** formats THEN nothing is attached and the loser is simply recoverably removed
  (a pure duplicate record).
- WHEN every one of a loser's formats is already on the survivor THEN nothing is attached and the
  loser is removed (all formats accounted for → data-safe).
- WHEN one loser fails to attach and another succeeds THEN the successful one is merged+removed and
  the failed one is left in place and reported (MERGE-06) — never a false "all merged".
- WHEN the group changes between plan and apply (a loser removed elsewhere) THEN the recomputed token
  mismatches and the apply is refused (MERGE-05) — the user re-plans.
- WHEN losers are processed THEN the order SHALL be ascending `loser_id` for deterministic reporting.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| MERGE-01 | P1: Merge in one reviewed call | Design | Pending |
| MERGE-02 | P1: Merge in one reviewed call | Design | Pending |
| MERGE-03 | P1: Merge in one reviewed call | Design | Pending |
| MERGE-04 | P1: Merge in one reviewed call | Design | Pending |
| MERGE-05 | P1: Merge in one reviewed call | Design | Pending |
| MERGE-06 | P1: Data-safe, recoverable deletion | Design | Pending |
| MERGE-07 | P1: Merge in one reviewed call | Design | Pending |
| MERGE-08 | P1: Data-safe, recoverable deletion | Design | Pending |

**ID format:** `MERGE-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 8 total. Design pending at `.specs/features/merge-duplicate-group/design.md`.

---

## Success Criteria

- [ ] A duplicate group is resolved in one plan + one apply, no Calibre GUI.
- [ ] The survivor ends with the union of all members' formats; no format is ever duplicated.
- [ ] A loser is never deleted while any of its formats is not yet on the survivor.
- [ ] Every deletion is recoverable (trash copy + recycle bin) and preceded by exactly one backup.
- [ ] A forced per-loser failure leaves that loser intact and yields a truthful `failed[]` — never a
      false "all merged".
- [ ] Invalid inputs (missing id, empty/duplicate/self loser list) are rejected before any backup.
