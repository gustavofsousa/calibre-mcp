# Roadmap — calibre-mcp

**Direction updated 2026-07-31 (AD-023, supersedes AD-018):** open-source-as-brand. The repo has
been public + MIT since 2026-07-17; calibre-mcp is now positioned deliberately around its one
defensible niche — *safe writes* — against a field of ~10 read-only Calibre MCP servers. Direct
revenue is not the goal; leverage is (portfolio proof + a reusable safe-mutation pattern). Packaging
is back in scope (frictionless `uvx` install). The two forward bets that build on this — productize
the pattern, and apply it to a vertical that pays — are recorded below under **Strategic Horizon**
(Phases B/C) as strategy, not committed calibre-mcp features. Single user, single library still
holds for the product itself (AD-007).

**Ambition expanded 2026-07-17 (AD-019):** the user wants to stop touching the Calibre GUI
entirely for library work — "the best server possible, that does everything, fast and well." All
four GUI-replacement gap areas are in scope: covers, bulk operations, author/tag/series
organization, and library maintenance. This does **not** change AD-018 (still personal, still no
packaging) — it changes how much of the GUI's day-to-day surface calibre-mcp needs to cover.

This file is roadmap-only (Phase / Capability / Phase-gate, per the product-vocabulary skill
convention) — it never becomes a tracked issue by itself. Each Phase below spawns Features, and
each Feature gets its own `.specs/features/[feature]/spec.md` when picked up.

### Two tracks, gated independently

This roadmap holds **two parallel tracks** — don't sequence one behind the other:

- **Feature track (Phase 0–6)** — what calibre-mcp *does*. Advanced by picking the next feature and
  Specify→Design→Tasks→Execute. Bounded only by effort/appetite.
- **Strategic track (Phase A/B/C)** — what the work is *for* beyond a personal tool (AD-023). Each
  phase is gated on a real-world signal (A→B needs the repo *discovered*; B→C needs a *paid*
  signal). **Do not start B or C before its gate opens.** Full block at the end, under *Strategic
  Horizon*.

The feature track is always available to push on; the strategic track waits for its gates. So "what
do I build next?" is answered by the feature track (currently: **Phase 3**), regardless of where the
strategic track is parked.

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

## Phase 2 — Bulk Operations & Library Organization (SHIPPED — all 6 features Verified, 2026-07-31)

**Capability:** "stop opening the GUI for routine, everyday curation" — the highest-frequency GUI
uses (multi-select edit, rename-across-library, convert/import in bulk) done through the MCP,
built entirely on primitives already proven in Phase 0 (no new subprocess pattern, no network).

**Why this came before Enrichment/Covers (resequenced from the previous roadmap):** these features
reuse `update_metadata`/`convert_book`/`add_book`/`remove_book`'s existing plan→confirm and backup
machinery — lowest risk, fastest to ship at high quality, and they directly serve "replace the GUI"
for the tasks done most often. Enrichment/covers (old Phase 2) moved to Phase 3 because they
introduce a genuinely new dependency (outbound network) that deserves to be its own hardening
effort, not bundled with routine-curation work.

**Features shipped (all independent-Verifier PASS — see `.specs/STATE.md` Handoff for detail):**

- **BULK-01 — Bulk metadata edit.** ✅ Verified. `update_metadata_bulk` broadcasts fields to N
  `book_ids` behind one batch `confirmation_token` (single review, single apply) + one backup +
  best-effort per-book `applied`/`failed`. Established the AD-020 multi-book batch pattern reused
  by every feature below.
- **BULK-02 — Bulk convert.** ✅ Verified. `convert_book_bulk` — additive/no-confirm (AD-016), one
  backup before the batch, three-bucket `converted`/`skipped`/`failed` result; never one failure
  silently voiding the whole batch.
- **BULK-03 — Import a folder.** ✅ Verified. `import_folder` — recursive ebook discovery under a
  directory, additive/no-token, one backup before the batch, per-file
  `added`/`duplicate`/`failed` report. Established AD-021 (filesystem discovery is its own pure
  module).
- **ORGN-01 — Rename an author across the library.** ✅ Verified. `rename_author` — every book
  credited to `old_name` gets `new_name` in one reviewed call, co-author-safe swap + in-book
  merge/dedupe, `books_by_author` discovery. Established AD-022 (`set_metadata` must join `authors`
  with `" & "`, not `,` — fixed a latent multi-author bug BULK-01 never exercised).
  Prerequisite-fix-then-feature: the riskiest of the three ORGN features to build first.
- **ORGN-02 — Rename a tag across the library.** ✅ Verified. `rename_tag` — the tag-scoped twin of
  ORGN-01; the resolve rule was *generalized* into a shared `rename_resolve.resolve_renamed_values`
  (author/tag share one algebra instead of duplicating it), not cloned. No prerequisite fix needed —
  AD-022 already serializes `tags` correctly.
  Independently verified with two disjoint discrimination-sensor runs (7/7 mutants killed).
- **ORGN-03 — Merge a duplicate group.** ✅ Verified. `merge_duplicate_group` — the one feature that
  **deletes book records**. Caller passes `survivor_id`/`loser_ids` (no auto-pick); formats-only
  merge (survivor metadata untouched — field enrichment deferred to Phase 3). No new mutation
  primitive: orchestrates `format_files`/`add_format --dont-replace`/the `remove_book`
  recoverable-delete sequence. Core invariant — a loser's formats are attached to the survivor
  *before* that loser is deleted — confirmed both by an independent discrimination sensor (7/7
  killed across two disjoint runs) and by a structural code-trace proving the removal is
  unreachable on any path except a fully-completed attach loop.

**Phase-gate (KPI): ✅ MET.** A full curation session (retag a batch, fix an author's name
everywhere, resolve a duplicate group, import a folder of new books) never requires opening the
Calibre GUI.

**Follow-on gap identified 2026-07-31 (not part of the closed gate — cheap to add):**

- **ORGN-04 — Rename/merge a series across the library.** The organization triad AD-019 names is
  *author/tag/**series***; ORGN-01/02/03 shipped author-rename, tag-rename, and duplicate-merge, but
  **series was never covered.** This is the missing sibling of ORGN-01/02: it becomes the *third*
  consumer of the already-generalized `rename_resolve.resolve_renamed_values` (author + tag today),
  applied through the AD-020 batch pattern — **no new mutation primitive, no new algebra.** Small,
  pattern-consistent, closes the AD-019 organization triad. A natural pick-up either as a Phase 2
  addendum or slotted right after Phase 3's covers pair.

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

# Strategic Horizon — beyond the product (Phases A / B / C)

> **What this section is, and isn't.** Phases 0–3 above are calibre-mcp *features*. This section is
> the *business/leverage* track set by AD-023: what the work is *for* beyond a personal tool. It is
> deliberately gated — each phase has a kill/advance criterion, and later phases are more expensive
> and less certain than earlier ones. **Do not start a later phase before its gate opens.** These
> are bets, sequenced cheapest-and-surest → costliest-and-riskiest. Full reasoning and unit
> economics live in the business-plan artifact that spawned this section.

**Grounding evidence (why the direction is what it is).** (1) The "Calibre MCP" niche is already
crowded and 100% free — ~10 servers on GitHub/marketplaces, most read-only/search, one already with
RAG + a desktop app. (2) MCP servers are near-un-monetizable today: the *host* captures the value,
not a local-file wrapper. ⇒ Charging for calibre-mcp is a dead end. Its real assets are the
*safe-mutation, human-in-the-loop design* (a pattern) and the *portfolio proof* of building a tool
allowed to delete a user's files. **Not pursued:** any SaaS/hosting around Calibre itself — wrong
market, no moat, DMCA/storage liability.

## Phase A — Open source + brand — **ACTIVE (2026-07-31)**

**Bet:** claim the one defensible niche — *"the Calibre MCP that writes safely"* — before one of the
~10 read-only competitors occupies it. Cost ~0; return is reputation/positioning, not cash.

**Scope (this repo):**
- Record the direction flip (AD-023) — **done**.
- Reposition README to lead with the safe-write differentiator — **done**.
- Frictionless install: `uvx --from git+…` (no clone, no PyPI dependency) — **done + verified**
  (found and fixed a real blocker: unpinned `mcp>=1.2.0` resolved to 2.0.0, which dropped
  `mcp.server.fastmcp` → fresh installs crashed at import; now pinned `>=1.2.0,<2`).
- **Checkpointed one-way doors (need explicit go):** push current state to the public remote (stale
  since 2026-07-17); submit to an MCP directory/registry; post the launch write-up; (optional) PyPI
  publish. Launch write-up drafted at `docs/launch-notes.md` — not posted.

**Gate A→B (advance when):** the repositioned repo is live and discoverable (pushed, README leads
with safe-writes, listed in ≥1 MCP directory). **Kill/park if:** repositioning attracts no signal
after a fair window — Phase A still paid for itself as a portfolio piece; do not escalate to B/C
chasing vanity metrics.

## Phase B — Productize the safe-mutation pattern — **QUEUED (behind Gate A→B)**

**Bet:** the leverage isn't the Calibre wrapper, it's the *reusable pattern* — plan→confirm +
backup-before-write + recoverable-delete + honest partial-failure contract for any MCP that mutates
user data. Extract it into a template/skill/boilerplate + a written playbook. Highest expected value
for the target audience (teams applying AI), because that audience *pays* for authority/consulting,
not for a free MCP.

**Candidate shapes (not yet decided — a Specify-time choice at kickoff):**
- A `safe-mutation-mcp` cookiecutter/template repo generated from calibre-mcp's proven layers.
- A reusable skill/playbook ("how to design an MCP that's allowed to delete") — feeds content →
  authority → inbound consulting.
- Reuse in the user's own projects (periciamap, biblioteca-api) as the first internal consumers.

**Gate B→C (the expensive door — advance only with a *real paid signal*):** ≥1 person/org has paid,
or made a concrete commitment to pay, for the pattern, the content, or advisory built on it. **Do
not build C on interest alone.** **Kill/park if:** the pattern gets reused internally but generates
no external pull — keep it as internal tooling, don't productize further.

## Phase C — Apply the pattern to a vertical that pays — **NOT STARTED (behind Gate B→C)**

**Bet:** point the same safe-mutation engine at a corpus where an error is *expensive* and the buyer
is an organization — forensic reports (periciamap), legal documents, medical records. This is where
a real SaaS exists, because the data is valuable and the buyer has budget. Highest leverage, highest
cost/risk — a genuine business, not a side effect.

**Preconditions:** Gate B→C open (validated demand) **and** a chosen vertical where the user has
domain access (periciamap is the natural first candidate — same owner, forensic-report domain,
error-costly by nature). **Do not pre-build** before demand is validated (AGENTS.md Traction Mode:
no full architecture without confirmed traction). **Kill/park if:** discovery shows the vertical's
real bottleneck isn't safe mutation — re-aim, don't force the pattern.

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
- **MAINT-04 — List & restore a `metadata.db` backup (roll back a bad edit).** AD-011 already keeps
  the last 20 pre-write `metadata.db` snapshots, but they're invisible and unusable from the host: a
  wrong bulk edit leaves 20 rollback points and no host-driven way to see or apply one. A read-only
  `list_backups` (timestamp + what op it preceded, if recoverable) plus a **plan→confirm** `restore_backup`
  that swaps the live `metadata.db` for a chosen snapshot — itself backing up the current state
  first, so restore is never a one-way door. **This directly operationalizes the "safe writes"
  brand (Phase A): the safety net becomes usable, not just present.** Highest-value maintenance item
  for that reason. Gated hard (AD-012) — restoring `metadata.db` rewrites the whole library state,
  so the plan must show *exactly* what era you're rolling back to. (Supersedes Phase 6's
  "backup-retention visibility" note, which was only a warning, not a restore path.)

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

1. **STATS-01** (Phase 1) — ✅ Shipped & Verified.
2. **Phase 2 (Bulk Ops & Organization)** — ✅ Shipped & Verified in full (2026-07-31): BULK-01/02/03
   + ORGN-01/02/03, all independently Verified. Phase-gate met.
3. **Phase 3 (Covers & Enrichment)** — ← **next Specify target.** Sub-order within the phase:
   **COVER-01** (read cover, pure FS read, no new dependency) → **COVER-02** (set cover, local
   mutation) — this already meets *half* the phase-gate ("every book has a viewable cover") with
   zero new architecture — → then the **ENRICH** cluster, treating the first outbound network call
   as a deliberate hardening effort with its own AD (timeout/offline/rate-limit).
4. **ORGN-04 (series rename/merge)** — cheap follow-on closing the AD-019 organization triad;
   pull in as a Phase 2 addendum or right after Phase 3's covers pair.
5. **Phase 4 (Maintenance)** — check_library/restore/export + **MAINT-04 metadata rollback** (the
   highest-value item: makes the AD-011 safety net host-usable, reinforcing the Phase A brand).
6. **Phase 5 (Device)** — needs the `calibredb saveto` research spike.
7. **Phase 6** — no dedicated slot; absorbed opportunistically.

This order front-loads the safest, most-reused, highest-frequency wins (Phase 2) and saves the
genuinely new architectural surface (outbound network in Phase 3, device I/O in Phase 5) for after
that foundation and its lessons are in place.

**Strategic track (A/B/C) runs in parallel, not in this queue.** Phase A is active; **Gate A→B is
still closed** (repo pushed but not yet listed in an MCP directory or announced), so Phase B is not
a build target yet — pushing on the feature queue above is the right use of development time now.

## Explicitly not on this roadmap

| Item | Reason |
| --- | --- |
| Multi-library config (one server ⇒ many libraries) | Single-library model stands (AD-007); out of scope even under AD-023. |
| ~~PyPI packaging / install docs~~ | **No longer excluded (AD-023 reversed AD-018).** `uvx --from git+…` install shipped in Phase A; PyPI publish is an *optional* checkpointed door in Phase A, not a "never." |
| Any AI/LLM orchestration inside the server | AD-006 keeps intelligence in the host; calibre-mcp stays a clean tool/resource surface. |
| The Calibre e-book viewer / built-in ebook editor | Reading and in-place content editing are out of an MCP tool surface's reach — not a metadata/orchestration task. |
| Calibre-Web / content-server orchestration (WEB-01) | Deferred inside Phase 5 — usually a separate always-on service, low priority for a single user. |
| News/periodical fetch (Calibre "recipes") | Not part of the ebook-curation loop this project targets; a distinct capability the user hasn't asked for. |
