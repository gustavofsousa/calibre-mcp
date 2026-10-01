# Roadmap (tactical) — calibre-mcp

> **What this doc is.** The *delivery* pipeline: which Feature ships in which version, what each
> phase must prove, and what debt it left behind. Revised per feature (it moves every PR or two).
>
> **Division of labor** — three docs, three questions, no overlap:
>
> | Doc | Answers | Cadence |
> | --- | --- | --- |
> | [`ROADMAP-STRATEGY.md`](ROADMAP-STRATEGY.md) | **Why / for what** — the bets beyond a personal tool, their gates, by quarter | quarterly |
> | **`ROADMAP.md`** (this) | **In what order** it ships — versions, features, phase-gates, debt | per feature |
> | [`BACKLOG.md`](BACKLOG.md) | **What it could become** — the unsequenced pool of ideas, by domain | whenever an idea shows up |
>
> **Invariant:** nothing enters this pipeline without first living in the backlog and earning a
> version. The dated decision log (`AD-NNN`) and per-feature handoff live in
> [`.specs/STATE.md`](.specs/STATE.md); each Feature's spec lives in `.specs/features/<feature>/`.

**Status:** ✅ done · ⚠️ done with debt · 🔄 in progress · 🗓️ planned · ⚪ no spec · 🔒 blocked
**SemVer:** MINOR (`0.x`) = a phase of the GUI-replacement pillar · `1.0` = the pillar is complete
and published. Phase labels (`Phase N`) are kept because every spec in `.specs/features/` cites them.

---

## Overview (one screen)

| Version | Phase | Phase target | Domains | Status |
| --- | --- | --- | --- | --- |
| v0.1 | 0 — Core curation loop | read + curate + distribute locally, safely | `catalog` `curation` `intake` `formats` `dedupe` `removal` `delivery` | ✅ closed |
| v0.2 | 1 — Library self-knowledge | host knows the library's shape from one resource read | `catalog` | ✅ closed |
| v0.3 | 2 — Bulk ops & organization | a full curation session never opens the Calibre GUI | `curation` `intake` `formats` `dedupe` | ✅ closed |
| v0.4 | 3 — Covers & enrichment | completeness gaps shrink measurably; every book has a cover | `covers` `enrichment` | 🔄 features shipped, gate **not met** |
| v0.5 | 4 — Library maintenance | integrity + recovery answerable from the MCP | `maintenance` `⟂ safety` | 🗓️ |
| v0.6 | 5 — Device delivery | "curated" → "readable on my device" in one action | `delivery` | ⚪ |
| v1.0 | — Stable & published | GUI-replacement pillar complete, installable from a registry | `— ops` | ⚪ |

**Now:** close v0.4 honestly (see its gate below), then pull **MAINT-04 (metadata rollback)** —
the highest-value v0.5 item because it makes the safety net *usable*, not just present.

---

## v0.1 — Phase 0 · Core curation loop ✅ *(closed 2026-07)*

**Target met:** search/list/get/edit/add/remove/convert/dedupe/email, each mutation behind
backup-before-write + plan→confirm, deletes recoverable. 39/39 requirements Verified.

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| search / list / get / edit / add / remove | `catalog` `curation` `intake` `removal` | `calibre-management` (31 req) | ✅ |
| convert / find_duplicates / email | `formats` `dedupe` `delivery` | `calibre-management-p2` (3 req) | ✅ |

## v0.2 — Phase 1 · Library self-knowledge ✅

**Target met:** "how many books / what's incomplete / what looks duplicated" answered from one read
of `calibre://library/stats` — zero `list_books` paging.

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| STATS-01 — `calibre://library/stats` resource | `catalog` | `library-stats` | ✅ |

## v0.3 — Phase 2 · Bulk operations & organization ✅ *(closed 2026-07-31)*

**Target met:** retag a batch, fix an author everywhere, resolve a duplicate group, import a folder —
none of it needs the GUI. Built only on Phase 0 primitives (AD-020 batch pattern).

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| BULK-01 — `update_metadata_bulk` | `curation` | `bulk-metadata-edit` | ✅ |
| BULK-02 — `convert_book_bulk` | `formats` | `bulk-convert` | ✅ |
| BULK-03 — `import_folder` | `intake` | `folder-import` | ✅ |
| ORGN-01 — `rename_author` | `curation` | `author-rename` | ✅ *(fixed AD-022 multi-author join)* |
| ORGN-02 — `rename_tag` | `curation` | `tag-rename` | ✅ |
| ORGN-03 — `merge_duplicate_group` | `dedupe` | `merge-duplicate-group` | ✅ |
| ORGN-04 — `rename_series` *(follow-on gap)* | `curation` | `series-rename` | ✅ |

## v0.4 — Phase 3 · Covers & metadata enrichment 🔄

**Target:** a meaningful drop in `metadata_completeness` gaps after one curation session, and every
book has a viewable cover. Introduces the first outbound network call (Open Library) — AD-026/027; covers AD-024/025.

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| COVER-01 — `read_cover` | `covers` | `cover-read` | ✅ |
| COVER-02 — `set_cover` | `covers` | `cover-set` | ✅ |
| ENRICH-01 — `enrich_from_identifier` (ISBN → Open Library) | `enrichment` | `identifier-lookup` | ✅ |
| ENRICH-02 — enrichment applied through plan→confirm | `enrichment` | `enrichment-apply` | ✅ |
| ENRICH-03 — `enrich_missing` batch review | `enrichment` | `enrichment-batch` | ✅ |
| Trustworthy suite + rating-scale fix *(this PR, AD-029/030)* | `— ops` `curation` | — | ✅ |

**Gate check (2026-10-01, live run against the real library — see
[`docs/live-smoke-test.md`](docs/live-smoke-test.md)):** **not met, and not reachable with the
shipped features alone.**

- *Completeness:* `enrich_missing` found only **7 candidates in 196 books** — enrichment is
  ISBN-keyed, and only 51 books carry an ISBN. Even a perfect run moves `comments` (26.5% filled)
  and `publisher` (35.2%) by a few points. The gap lives in the ~145 books *without* an ISBN.
- *Covers:* the stats resource doesn't report cover coverage at all, so "every book has a cover"
  can't be measured yet.

**To close v0.4** (both are backlog items promoted here; specs not written yet):

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| STATS-02 — cover coverage in `library_stats` (count + ids without cover) | `catalog` | — | ⚪ |
| ENRICH-04 — title/author search for books without an ISBN (proposal-only, same gate) | `enrichment` | — | ⚪ |

Decision at spec-pull for ENRICH-04: a title/author match is *fuzzy* (ISBN is exact) — the proposal
must surface the match confidence and the candidate edition, or a wrong-book enrichment becomes a
silent bad write behind a "confirmed" token.

## v0.5 — Phase 4 · Library maintenance 🗓️

**Target:** integrity issues and recovery are answerable/actionable from the MCP — zero manual
`calibredb`/GUI intervention. Wraps existing `calibredb` subcommands via the sibling-runner pattern
(AD-014).

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| MAINT-04 — list & restore a `metadata.db` backup (roll back a bad edit) | `⟂ safety` | — | ⚪ **next** |
| MAINT-01 — `check_library` integrity report | `maintenance` | — | ⚪ |
| MAINT-02 — restore a removed book from trash | `removal` | — | ⚪ *(decide: new id vs. same id)* |
| MAINT-03 — export books to a folder | `maintenance` | — | ⚪ |

MAINT-04 is first: AD-011 already keeps 20 rollback points, but the host can neither see nor apply
them. Restore is itself plan→confirm and backs up the current state first, so it is never a one-way
door.

## v0.6 — Phase 5 · Device delivery ⚪

**Target:** time from "book curated" to "readable on my device" drops to one host-driven action.

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| DEVICE-01 — copy to a mounted e-reader | `delivery` | — | 🔒 *(needs a `calibredb saveto` spike + AD)* |

## v1.0 — Stable & published ⚪

**Target:** the pillar is complete and installable from a registry; the public promise ("safe
writes") is backed by a usable rollback (MAINT-04) and a suite that runs fully in CI.

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| Tagged releases + changelog | `— ops` | — | ⚪ |
| PyPI publish *(optional one-way door — strategy A4)* | `— ops` | — | ⚪ |

---

## Domains (reference)

calibre-mcp has no `dominios.md` yet — the domain list is small enough to live here and in
[`BACKLOG.md`](BACKLOG.md). Code is still organized by I/O boundary (reader / runners / facade), not
by domain; that's deliberate at this size (see the backlog's tech-debt band).

- **`catalog`** — search, list, view, stats · **`curation`** — single/bulk edit, author/tag/series
  rename · **`intake`** — add, folder import · **`formats`** — convert, bulk convert ·
  **`dedupe`** — find + merge duplicates · **`removal`** — recoverable delete + trash ·
  **`covers`** — read/set covers · **`enrichment`** — external metadata proposals ·
  **`delivery`** — email, device · **`maintenance`** — integrity, export.
- Cross-cutting (never a folder): **`⟂ safety`** — backup-before-write, plan→confirm,
  recoverable delete · **`— ops`** — CI, packaging, release.

## Debt inherited from closed phases

| ID | Origin | Status | Revisit trigger |
| --- | --- | --- | --- |
| AD-028 | workspace reorg | open (accepted) | library moves again and the double-edit of the path bites |
| TD — lessons housekeeping | v0.3 | open | two `candidate` lessons in `.specs/lessons.json` await promote/quarantine before the next Specify |
| TD — backup retention is silent | v0.1 (AD-011) | open | superseded by MAINT-04 once rollback exists |
| ~~TD — tests sourced epubs from a personal path~~ | v0.1–v0.4 | ✅ paid (AD-029) | — |
| ~~Bug — `rating` written doubled~~ | v0.1 (EDIT) | ✅ fixed (AD-030) | — |

## Out of scope (a decision not to do it — not "not yet")

| Item | Reason |
| --- | --- |
| Multi-library config | Single-library model stands (AD-007). |
| AI/LLM orchestration inside the server | Intelligence stays in the host (AD-006). |
| Calibre viewer / in-place ebook content editing | Not a metadata/orchestration task. |
| Calibre-Web / content-server orchestration | Separate always-on service; low value for one user. |
| News/periodical fetch (Calibre recipes) | Outside the curation loop; never asked for. |
