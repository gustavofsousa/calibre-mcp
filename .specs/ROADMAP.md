# Roadmap — calibre-mcp

**Direction confirmed 2026-07-17 (AD-018):** personal use, polished (not open source, not a
packaging/distribution effort). Single user, single library.

**Ambition expanded 2026-07-17 (AD-019):** the user wants to stop touching the Calibre GUI
entirely for library work — "the best server possible, that does everything, fast and well." All
four GUI-replacement gap areas are in scope: covers, bulk operations, author/tag/series
organization, and library maintenance. This does **not** change AD-018 (still personal, still no
packaging) — it changes how much of the GUI's day-to-day surface calibre-mcp needs to cover.

This file is roadmap-only (Phase / Capability / Phase-gate, per the product-vocabulary skill
convention) — it never becomes a tracked issue by itself. Each Phase below spawns Features, and
each Feature gets its own `.specs/features/[feature]/spec.md` when picked up.

---

## Phase 0 — Core Curation Loop (SHIPPED)

**Capability:** read + curate + distribute locally, safely (backup-before-write, recoverable
delete, plan→confirm on every mutation).

- P1 (`calibre-management`): search/list/get/edit/add/remove — 29/29 requirements Verified.
- P2 (`calibre-management-p2`): convert/find_duplicates/email — 3/3 requirements Verified.

**Phase-gate:** closed. 39/39 total requirements Verified across both features.

---

## Phase 1 — Library Self-Knowledge (SPEC DONE, ready for Design/Execute)

**Capability:** "the host knows the library's shape without paging `list_books`."

- **STATS-01** (`library-stats`): `calibre://library/stats` MCP resource — totals, format/language
  mix, metadata completeness, identifier types, top authors/tags, data-quality flags (unknown
  authors, placeholder pubdates, unused series/rating, duplicate-title groups). Spec finalized at
  `.specs/features/library-stats/spec.md`.

**Phase-gate (KPI):** host can answer "how many books / what's incomplete / what looks like a
duplicate" from a single resource read — zero `list_books` calls needed for that class of
question.

**Next action:** Design/Execute STATS-01.

---

## Phase 2 — Bulk Operations & Library Organization (NEXT — no new external dependency)

**Capability:** "stop opening the GUI for routine, everyday curation" — the highest-frequency GUI
uses (multi-select edit, rename-across-library, convert/import in bulk) done through the MCP,
built entirely on primitives already proven in Phase 0 (no new subprocess pattern, no network).

**Why this comes before Enrichment/Covers (resequenced from the previous roadmap):** these
features reuse `update_metadata`/`convert_book`/`add_book`/`remove_book`'s existing plan→confirm
and backup machinery — lowest risk, fastest to ship at high quality, and they directly serve
"replace the GUI" for the tasks done most often. Enrichment/covers (old Phase 2) move to Phase 3
because they introduce a genuinely new dependency (outbound network) that deserves to be its own
hardening effort, not bundled with routine-curation work.

**Candidate features (not yet spec'd):**

- **BULK-01 — Bulk metadata edit.** `update_metadata` for N `book_ids` in one call. Design
  question for Specify: one `confirmation_token` covering the whole batch (single review, single
  apply — simpler UX) vs. one per book (finer-grained, safer against partial mismatches). Either
  way, AD-012's "review before write" must hold for every book in the batch, never a silent bulk
  apply.
- **BULK-02 — Bulk convert.** `convert_book` across many ids in one call; additive/no-confirm like
  today. Needs an explicit partial-failure contract: if book 5 of 20 fails to convert, the other
  19 still succeed and the failure is reported per-book — never one failure silently voiding the
  whole batch, never a fake "all succeeded."
- **BULK-03 — Import a folder.** Point at a directory, `add_book` every ebook file found in it
  (recursive vs. top-level-only is a Specify-time decision). One backup before the batch, per-file
  added/duplicate/failed report — same honesty contract as `add_book` (ADD-03/04), just N-wide.
- **ORGN-01 — Rename an author across the library.** Every book credited to `old_name` gets
  `new_name` in one call. No `calibredb` subcommand does this directly — it's a compound
  orchestration: find affected books (new `SqliteReader.books_by_author(name)` lookup, mirroring
  `format_files`'s reader-layer discipline) then apply through `BULK-01`. Reuse, not a new
  mutation primitive.
- **ORGN-02 — Rename a tag across the library.** Same pattern as ORGN-01, tag-scoped.
- **ORGN-03 — Merge a duplicate group.** Given a `find_duplicates` group, pick a surviving book id,
  attach every other member's formats onto it (reusing `convert_book`'s `add_format` step), then
  `remove_book` the losers (reusing the existing recoverable-remove flow). A genuine merge, built
  entirely from primitives that already exist and are Verified — gated like `remove_book`
  (plan→confirm, AD-012), since it deletes book records.

**Phase-gate (KPI):** a full curation session (retag a batch, fix an author's name everywhere,
resolve a duplicate group, import a folder of new books) never requires opening the Calibre GUI.

---

## Phase 3 — Covers & Metadata Enrichment (external integration #1)

**Capability:** "close the data-quality and cover gaps STATS-01 surfaces, using external sources."
Motivating numbers from the validated prototype (`.library-profile.json`, real library): 71% of
books missing `comments`, 62.9% missing `publisher`, 64.1% missing `identifiers`.

**Candidate features (not yet spec'd):**

- **COVER-01 — Read a book's cover.** Calibre always stores `cover.jpg` in the book's folder; a
  pure filesystem read through the reader layer (mirrors `format_files`'s discipline — no new
  invariant). Read-only, no network.
- **COVER-02 — Set a book's cover from a local file.** A mutation like any metadata field —
  gated through the existing plan→confirm handshake (AD-012), added to `update_metadata`'s field
  set or as its own tool (Specify-time decision).
- **ENRICH-01 — Identifier-based lookup.** Given an existing identifier (ISBN / Google Books id /
  ASIN), query an external metadata source (Open Library API — free, no key, fits "personal, no
  infra") for missing description/publisher/pubdate/cover.
- **ENRICH-02 — Route enrichment through the existing plan→confirm gate.** No new mutation path —
  enrichment is just another *source* of proposed values fed into `update_metadata`'s diff/confirm
  handshake.
- **ENRICH-03 (P3 candidate) — Batch review mode.** "Enrich all books missing comments" returns N
  independent plans to walk through — never a silent bulk apply.

**Phase-gate (KPI):** meaningful drop in `metadata_completeness` gaps (STATS-01's own output)
after a curation session, and every book has a viewable cover.

**Open architectural question to raise at Specify time:** this is the first feature where the
server makes an *outbound* network call. AD-002/AD-003 ("local stdio, no auth") were about the MCP
*transport* surface, not calibre-mcp acting as an HTTP *client* — worth an explicit new AD (timeout
policy, offline failure handling, rate limits against a free API) before Design.

---

## Phase 4 — Library Maintenance

**Capability:** the trust-building, "I never need the GUI's Library → Maintenance menu again"
layer — integrity checking, recovery, and export, all wrapping existing `calibredb` subcommands
via the same sibling-runner pattern as `CalibredbRunner`/`EbookConvertRunner`/`CalibreSmtpRunner`
(AD-014).

**Candidate features (not yet spec'd):**

- **MAINT-01 — Check library integrity.** Wraps `calibredb check_library` (new `CalibredbRunner`
  method) — surfaces Calibre's own integrity diagnostics (orphan records, missing files) as a
  read-only report, complementing STATS-01's data-quality flags with a structural check.
- **MAINT-02 — Restore a removed book.** Copy a book's files back from `backups/trash/` into the
  library via the existing `add_book` flow. **Known limitation to confirm at Specify time:** this
  creates a *new* book id — it does not resurrect the original record/id, since Calibre's own
  recycle bin (not our trash copy) is what would do a true same-id restore, and that's a manual
  GUI/OS action outside calibredb's CLI surface. Worth deciding whether that limitation is
  acceptable or whether restore is descoped to "recover the file, re-add manually."
- **MAINT-03 — Export books to a folder.** Wraps `calibredb export` (save-to-disk equivalent) —
  pure file copy-out, no `metadata.db` mutation.

**Phase-gate (KPI):** integrity issues and recovery are always answerable/actionable from the MCP;
zero manual `calibredb`/GUI intervention needed for these tasks.

---

## Phase 5 — Distribution / Device Integrations (external integration #2)

**Capability:** "get a curated book to where you'll actually read it," closing the loop after
curation, organization, and enrichment.

**Candidate features (not yet spec'd):**

- **DEVICE-01 — Direct e-reader copy.** Detect a connected e-reader (mounted volume, e.g.
  Kindle/Kobo over USB) and copy the right format directly — same sibling-runner pattern as
  `email_book`. Needs a design spike: whether `calibredb saveto` (through `calibredb`, honoring
  AD-001) can do this safely, vs. a raw filesystem copy (would need an explicit new AD, since
  today only the runner layer touches external I/O).
- **WEB-01 (low priority, likely stays deferred) — Calibre-Web/content-server awareness.** Usually
  a separately-run, always-on service, not something the MCP needs to orchestrate for a single
  personal user. Revisit only if it becomes real friction.

**Phase-gate (KPI):** time from "book curated" to "readable on my device" drops to one host-driven
action.

---

## Phase 6 — Trust & Polish (background; pull in opportunistically, no dedicated milestone)

- **Backup-retention visibility.** AD-011 already keeps the last N `metadata.db` backups; surface
  when a trim is about to drop a backup you'd still want.
- **Lessons housekeeping.** Two `candidate` lessons are sitting in `.specs/lessons.json` (call-order
  test pattern for AD-011 backup-before-write; AC-branch test-coverage pattern) — review and
  promote/quarantine them before later phases' Specify steps miss out on them (`specify.md` only
  loads `confirmed` lessons).

---

## Sequencing recommendation

1. **STATS-01** (Phase 1) — Design/Execute now; spec already finalized.
2. **Phase 2 (Bulk Ops & Organization)** — next Specify target. No new dependency, reuses existing
   Verified primitives, highest-frequency GUI replacement value.
3. **Phase 3 (Covers & Enrichment)** — first feature needing a new outbound-network AD.
4. **Phase 4 (Maintenance)** — check_library/restore/export, same low-risk runner pattern as
   Phase 2.
5. **Phase 5 (Device)** — needs the `calibredb saveto` research spike.
6. **Phase 6** — no dedicated slot; absorbed opportunistically.

This order front-loads the safest, most-reused, highest-frequency wins (Phase 2) and saves the
genuinely new architectural surface (outbound network in Phase 3, device I/O in Phase 5) for after
that foundation and its lessons are in place.

## Explicitly not on this roadmap

| Item | Reason |
| --- | --- |
| PyPI packaging, install docs, multi-library config | "Open source" horizon, explicitly not chosen (AD-018). |
| Any AI/LLM orchestration inside the server | AD-006 keeps intelligence in the host; calibre-mcp stays a clean tool/resource surface. |
| The Calibre e-book viewer / built-in ebook editor | Reading and in-place content editing are out of an MCP tool surface's reach — not a metadata/orchestration task. |
| Calibre-Web / content-server orchestration (WEB-01) | Deferred inside Phase 5 — usually a separate always-on service, low priority for a single user. |
| News/periodical fetch (Calibre "recipes") | Not part of the ebook-curation loop this project targets; a distinct capability the user hasn't asked for. |
