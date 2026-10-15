# Backlog — calibre-mcp

> **Version** 1.0 · October 2026. The **unsequenced pool**: every path each domain could take,
> organized by domain (same order as the domain list in [`ROADMAP.md`](ROADMAP.md#domains-reference)).
> **Nothing here is decided.** An item enters the tactical [`ROADMAP.md`](ROADMAP.md) only after it
> is validated and earns a version; strategic bets live in [`ROADMAP-STRATEGY.md`](ROADMAP-STRATEGY.md).
>
> **Division of labor:** `BACKLOG.md` says **what** it could become · `ROADMAP.md` says **in what
> order** it ships · `ROADMAP-STRATEGY.md` says **what it's for** · `.specs/STATE.md` records **why**
> (AD-NNN).

## How to read

Each domain shows only the bands that have content:

- **Mature** — what an existing capability can gain. Concrete, almost spec-ready.
- **New / Vision** — behavior that doesn't exist yet.
- **Decision at spec-pull** — the choice that must be made before specifying (kept next to its domain).
- **Tech debt** — code/structure chores, recorded so they aren't lost.

Items already sequenced carry their version: `(v0.4)`. Evidence tags: **[live]** = observed in the
2026-10-01 live run against the real library ([`docs/live-smoke-test.md`](docs/live-smoke-test.md)),
**[code]** = read in the source, **[hyp]** = hypothesis, not yet verified.

**Status:** ✅ done · 🔄 in progress · 🗓️ planned · ⚪ no spec · 💤 future

---

## Core · the curation loop

### catalog — search, list, view, stats
- **Mature:**
  - ✅ STATS-02 — cover coverage in `library_stats` (v0.4) — 192/194 covered; missing ids 53, 184.
  - `list_books` filter by missing field (`missing="publisher"`) — turns the stats percentages into a
    worklist without the host paging 196 books ⚪.
  - `search_books` pagination (`limit`/`offset`) — it returns every match today; a broad query on a
    large library floods the context window **[code]** ⚪.
- **New / Vision:** read Calibre **custom columns** (reading status, "read on", personal notes) ·
  "what changed since date X" (recently added/modified) as a resource.
- **Decision at spec-pull:** custom columns — read-only first, or design the write path up front?
  *(recommendation: read-only first; writes go through the same `update_metadata` gate later)*.

### curation — single/bulk edit, author/tag/series rename
- **Mature:**
  - **`identifiers` as an editable field** (add/fix an ISBN) ⚪ — highest leverage in this list:
    enrichment is ISBN-keyed and only 51/196 books have one **[live]**. Adding an ISBN by hand unlocks
    the whole ENRICH pipeline for that book.
  - Series auto-proposal from title numbering ("One Piece vol. 12", "E1 Lumen Fidei") ⚪ — 20 books
    by one author and `series_unused: true` **[live]**. Proposal-only, applied via `rename_series`/bulk.
  - Guided cleanup of `Unknown` authors (23 books) and placeholder pubdates (`0101-01-01`, 74 books)
    **[live]** — a read-only "worklist" plus the existing bulk tools.
  - `rename_publisher` (fourth consumer of `rename_resolve`) ⚪.
- **New / Vision:** propose metadata from the file itself (embedded OPF/PDF info) — offline
  enrichment, no network.
- **Tech debt:**
  - ✅ **resolved** (2026-10-01, AD-030) — `rating` was written doubled (`calibredb` takes stars) **[live]**.
  - `rating: 0` clears the rating (Calibre stores no row) — the re-read returns `null`, not `0`.
    Document in the tool docstring or normalize ⚪ **[live]**.

### intake — add, folder import
- **Mature:** `import_folder` dry-run (preview `added`/`duplicate` before importing) · `add_book`
  with metadata overrides (fix title/author at import time).
- **New / Vision:** an "inbox" folder convention the host can sweep on request (not a daemon).
- **Decision at spec-pull:** forced add of a known duplicate (`calibredb add -d`) — allow it behind
  plan→confirm, or keep "duplicates are never re-added" absolute?

### formats — convert, bulk convert
- **Mature:** `remove_format` (drop one format, recoverable, plan→confirm) · conversion profiles
  (output profile per device: Kindle/Kobo).
- **New / Vision:** `ebook-polish` — embed the curated metadata + cover *into* the file, so a book
  emailed or copied to a device carries the fixed metadata.

### dedupe — find + merge duplicates
- **Mature:** ISBN-based duplicate detection (exact, complements the title/author key) · accent- and
  punctuation-insensitive title key.
- **New / Vision:** merge *metadata* too — propose filling the survivor's gaps from the losers
  (today the merge is formats-only by design, ORGN-03).
- **Note:** the real library has 2 duplicate groups right now (ids 196/209 and 68/132) **[live]** —
  data work, not code; see *Curation to-do* below.

### removal — recoverable delete, trash
- **Mature:** MAINT-02 restore from trash (v0.5) ⚪.
- **Tech debt:** `.calibre-mcp-backups/trash/` has **no retention** — `metadata.db` snapshots are
  pruned to 20, trashed book files are kept forever **[code]** ⚪.
- **Decision at spec-pull (MAINT-02):** restored book gets a new id (simple) vs. same id (needs the
  Calibre recycle bin, outside the CLI).

## Core · enrichment pillar

### covers — read/set covers
- **Mature:** batch cover fill from `enrich_missing` results (still per-book confirm) · a minimum
  resolution check before `set_cover` accepts an image.
- **New / Vision:** generated placeholder cover (title/author typeset) for books no source has.

### enrichment — external metadata proposals
- **Mature:**
  - ✅ ENRICH-04 — title/author search for books without an ISBN (v0.4, AD-032). Dry run on the real
    library: 11 confident matches, but only 1 had a description **[live]**.
  - **ENRICH-05 — a second source (Google Books) behind the same proposal contract** ⚪ — the v0.4
    KPI is now *source-limited*: Open Library lacks descriptions for 10 of 11 confidently matched
    books **[live]**. Needs an RFD (new external dependency, terms of use, quota).
  - Let the user pick among the top-3 candidates for `medium` matches — 38 books sit there **[live]**.
  - Propose the matched edition's ISBN (needs editable `identifiers` — see `curation`), so later
    lookups become exact.
  - Fill `languages` (110 books unset **[live]**) — detect from the book text locally, no network.
  - Propose tags from Open Library `subjects` (proposal-only).
- **New / Vision:** a source that covers Brazilian editions better — confirmed thin on Open Library
  for this library **[live]**.
- **Decision at spec-pull:** cache Open Library responses (and for how long)? Identify the client
  with a contact e-mail in the `User-Agent` (Open Library then allows 3 req/s instead of 1)? —
  pacing itself is ✅ done (AD-032).
- **Tech debt:** a full `enrich_missing` sweep takes minutes at 1 req/s (AD-032) — fine for one
  user; lower the default `limit` if a host's tool timeout cuts it.

## Support

### delivery — email, device
- **Mature:** named recipients (`kindle`, `kobo`) from config instead of raw addresses — fewer
  typos on an outward-facing action.
- **New / Vision:** DEVICE-01 copy to a mounted e-reader (v0.6) 🔒 — needs a `calibredb saveto` spike.
- **Note:** the live run didn't exercise `email_book` (the plan step was blocked by the agent's
  permission classifier) — needs a manual run with SMTP configured **[live]**.

### maintenance — integrity, export
- **Mature:** MAINT-01 `check_library` (v0.5) ⚪ · MAINT-03 export to a folder (v0.5) ⚪.
- **New / Vision:** a library "health score" combining stats + integrity, tracked over time.

---

## Cross-cutting (cut every domain — never a folder)

- **⟂ safety**
  - MAINT-04 — list & restore a `metadata.db` backup (v0.5) ⚪ **next** — the safety net made usable.
  - **Bind the confirmation token to the reviewed state, and make it unforgeable** ⚪ — today
    `token = sha256(op|id|payload)` **[code]**: (1) it doesn't include the book's *current* values,
    so if the book changes between plan and confirm, the apply still goes through against a diff the
    user never saw; (2) it never expires; (3) anyone who knows the params can compute it, so a
    misbehaving host can skip the human review entirely. Fix shape: HMAC with a per-process secret +
    a hash of the planned "current" values + a TTL. This is the core of the "safe writes" promise.
  - Mutation audit log (JSONL next to the backups: op, ids, diff, backup file) — answers "what did
    the AI change today?" and gives MAINT-04 its index.
  - Read-only mode (`CALIBRE_MCP_READ_ONLY=1`) — try the server on a real library with zero risk.
- **— ops**
  - Release process: version is still `0.1.0` while the roadmap is at v0.4 — tags + CHANGELOG ⚪.
  - MCP registry metadata (`server.json`) — prerequisite for strategy A2.
  - CI runtime went from ~4 to ~10 min once ~150 write-path tests stopped skipping (AD-029) —
    split unit/integration jobs or `pytest-xdist` if it starts to hurt.
  - **10 orphan `calibre-mcp` processes** found running from old sessions **[live]** — check the
    server exits cleanly when the host closes stdin **[hyp]**.
  - The host config runs the server from the **working tree** (`uv --directory <repo>`), so
    checking out a dev branch silently changes the live server — use a separate worktree or a
    pinned `uvx --from git+…@<tag>` for daily use **[code]**.
- **Docs / brand:** a generated tool reference from the docstrings · a short demo GIF of the
  plan→confirm flow in the README.
- **Privacy:** enrichment sends ISBNs to Open Library — stated in the README now; an "offline"
  switch that disables all outbound calls.

---

## Incubator (no domain yet — needs name + user + problem)

- **Reading-life sync** — KOReader/Kobo reading progress and highlights into Calibre custom columns.
- **Import from Goodreads/StoryGraph** — shelves and ratings into tags/rating.

**Raw — to distill:** "what to read next" as a resource the host reasons over (the server stays
LLM-free, AD-006) · read-only multi-library (conflicts with AD-007 — likely stays out) · Calibre
content-server awareness.

---

## Curation to-do on the real library (data work, not code)

Found during the 2026-10-01 live run; doable today with the shipped tools:

- Resolve 2 duplicate groups — ids **196/209** ("APOSTILA MÓDULO 4.2") and **68/132** ("A fé
  explicada") via `merge_duplicate_group`.
- Apply the 4 `enrich_missing` proposals (books 84, 98, 110, 205) via
  `update_metadata`.
- Set covers by hand for books **53** and **184** (the only two without one; not on Open Library).
- Fix the 23 `Unknown`-author books and the 74 placeholder pubdates.
