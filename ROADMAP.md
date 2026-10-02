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
| v0.4 | 3 — Covers & enrichment | completeness gaps shrink measurably; every book has a cover | `covers` `enrichment` `catalog` | ⚠️ closed with debt — KPI source-limited |
| v0.5 | 4 — Library maintenance | integrity + recovery answerable from the MCP | `maintenance` `⟂ safety` | 🗓️ |
| v0.6 | 5 — Device delivery | "curated" → "readable on my device" in one action | `delivery` | ⚪ |
| v1.0 | — Stable & published | GUI-replacement pillar complete, installable from a registry | `— ops` | ⚪ |

**Now:** v0.4 closed with debt (see its gate below) → pull **MAINT-04 (metadata rollback)** —
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

## v0.4 — Phase 3 · Covers & metadata enrichment ⚠️ *(closed with debt 2026-10-01)*

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

**Gate check — round 1 (2026-10-01, live run, [`docs/live-smoke-test.md`](docs/live-smoke-test.md)):**
not measurable/reachable with the ISBN path alone (7 enrichable books of 196; no cover metric).
Two features were added to close the gap:

| Feature | Domain | Spec | Status |
| --- | --- | --- | --- |
| STATS-02 — cover coverage in `library_stats` | `catalog` | `cover-coverage` | ✅ |
| ENRICH-04 — title/author search for books without an ISBN (high-confidence only, AD-032) | `enrichment` | `title-search-enrichment` | ✅ |

**Gate check — round 2 (2026-10-01, read-only dry run of `enrich_missing` on the real library):**

| Gate half | Measured | Verdict |
| --- | --- | --- |
| Every book has a viewable cover | **192/194 (99.0%)** — missing ids 53, 184; neither is findable on Open Library | ⚠️ 2 books need a manual `set_cover` |
| Meaningful drop in completeness gaps | 142 candidates → **4 proposals** (3 ISBN, 1 search); applying all moves `comments` from 52 to at most 55 books | ❌ not met |

**Why, with evidence:** the matcher finds the right book — 11 `high` matches, all correct — but
**10 of those 11 Open Library works carry no description**. The gap is now *source-limited*: Open
Library is thin for this library (PT-BR, religious, technical). 38 more books matched at `medium`
and were (by design) not proposed.

**Closure:** v0.4 is **⚠️ done with debt** — every planned feature shipped and was independently
verified; the completeness KPI is not met because the data source lacks the data. The next lever is
a second metadata source (Google Books — **ENRICH-05**, needs an RFD: new external dependency,
terms of use, rate limits) or manual curation; neither blocks v0.5. Data to-do: set covers for books
53 and 184.

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
| v0.4 KPI — completeness gap is source-limited | v0.4 | open | ENRICH-05 (second source) gets an RFD, or a manual curation session is done |
| Full `enrich_missing` sweep takes minutes (1 req/s pacing) | v0.4 (AD-032) | open (accepted) | a host times out on a full page → lower the default `limit` |

## Out of scope (a decision not to do it — not "not yet")

| Item | Reason |
| --- | --- |
| Multi-library config | Single-library model stands (AD-007). |
| AI/LLM orchestration inside the server | Intelligence stays in the host (AD-006). |
| Calibre viewer / in-place ebook content editing | Not a metadata/orchestration task. |
| Calibre-Web / content-server orchestration | Separate always-on service; low value for one user. |
| News/periodical fetch (Calibre recipes) | Outside the curation loop; never asked for. |
