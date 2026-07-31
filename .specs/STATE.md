# Project State — calibre-mcp

MCP server (stdio, local) that lets an LLM host manage a Calibre ebook library:
fast reads via SQLite, integrity-safe writes via `calibredb`.

## Decisions (AD-NNN)

- **AD-001 — Connection model: hybrid.** Reads (search/list/view) query `metadata.db` directly
  (read-only, fast, never risks integrity). Writes (edit/add/remove) go through `calibredb`
  (respects Calibre's integrity logic). Never write via SQLite; never shell out for reads.
- **AD-002 — Transport: local stdio.** No HTTP, no network surface. Server is launched by the
  host (Claude Desktop/Code). Rationale: kills auth + remote-file complexity.
- **AD-003 — No auth.** Follows from AD-002 (local process, no port).
- **AD-004 — Add book takes a local filesystem path** (no byte upload). Server is co-located
  with the library.
- **AD-005 — Stack: Python + FastMCP** (official MCP SDK). `calibredb` invoked as a subprocess
  (argument list, never shell string).
- **AD-006 — Intelligence lives in the host, not the server.** No embedded AI/LLM calls. The MCP
  exposes clean tools; Claude orchestrates.
- **AD-007 — One server instance = one library**, path via `CALIBRE_LIBRARY_PATH` env var.
- **AD-008 (REVISED by AD-013) — Traction mode: MVP.** Cut anything off the core curation loop.
  P1 = read + edit + add/remove. ~~P2 = convert + organize/deduplicate.~~ P2 scope revised — see AD-013.
- **AD-009 (REVISED) — `remove` is recoverable, never `--permanent`.** `calibredb remove` sends to the
  recycle bin AND, before removing, the book's actual files are copied to a managed `backups/trash/`
  folder. Double safety net: even if the recycle bin is emptied, the files survive. Supersedes the
  original permanent-delete decision (user's data is irreplaceable).
- **AD-010 — Search = `calibredb search` → SQLite hydrate.** Ids resolved by `calibredb search`
  (real Calibre grammar), full metadata read from `metadata.db`. Consequence: the "reads work when
  GUI-locked" guarantee is scoped to `get_book`/`list_books`; `search_books` may fail under lock and
  surfaces the error, with `list_books` as the lock-independent fallback.
- **AD-011 — Auto-backup before every write.** Before any mutation (edit/add/remove), copy
  `metadata.db` → `backups/metadata-<timestamp>.db` with rolling retention (keep last N, default 20).
  metadata.db is small; the copy is instant. Gives a rollback point for wrong/bulk edits.
- **AD-012 — Mutations require explicit, server-enforced intent (plan → confirm).** `update_metadata`
  and `remove_book` are two-step: a **plan** call (no token) returns a human-readable review of what
  will change (edit: current→proposed diff; remove: book details + where files are backed up) plus a
  deterministic `confirmation_token`; the **apply** call must pass that exact token. The token is a
  hash of the operation params, so the applied op is provably what was reviewed. Tool docstrings tell
  the host to surface the plan to the user and only apply after approval. `add_book` stays single-step
  (additive, low-risk, still backed up). No global read-only flag (this supersedes that option).
- **Test safety rule — writes NEVER touch the user's real library.** Write tests bootstrap a scratch
  library in a temp dir; the real library (`/home/gustavo/Documents/BibliotecaCalibre`) is used
  read-only for read tests. This is non-negotiable.
- **Invariant — tool layer never touches `sqlite3`/`subprocess` directly.** Reads via `SqliteReader`,
  writes via `CalibredbRunner`, both behind the `CalibreLibrary` facade. Logging to **stderr only**
  (stdout is the stdio MCP channel). Subprocess always arg-list, `shell=False`.

- **AD-013 — P2 scope = CONV-01 + ORG-01 + EMAIL-01.** Supersedes AD-008's "P2 = convert +
  organize/deduplicate": EMAIL-01 (email a book's file) joins P2. Rationale: `calibre-smtp` is
  present and email is a natural distribution increment on the P1 read primitives. STATS-01 stays P3.
- **AD-014 — One sibling runner per external CLI.** `ebook-convert` → `EbookConvertRunner`,
  `calibre-smtp` → `CalibreSmtpRunner`, each mirroring `CalibredbRunner`'s single-call-site discipline
  (arg-list, `shell=False`, failure→taxonomy). `CalibredbRunner` stays calibredb-only. The tool layer
  still never touches `subprocess`/`sqlite3` directly (extends AD-001/AD-005). `add_format` is a
  calibredb subcommand → it lives on `CalibredbRunner`.
- **AD-015 — SMTP config via env, password hygiene.** `calibre-smtp` cannot read Calibre's GUI SMTP
  config, so relay/user/password/encryption/sender come from `CALIBRE_MCP_SMTP_*` env vars (follows
  AD-007), lazy-loaded inside `email_book` (server boots without SMTP). The password is **env-only**:
  never logged, never returned in any tool output/plan, and scrubbed from any echoed subprocess
  stderr. Known accepted limitation: the CLI exposes the password in the process arg list (`ps`);
  acceptable for a local single-user MVP, revisit with an `--outbox`/stdin path later.
- **AD-016 — Per-tool intent gates in P2.** `convert_book` is single-step + backup (additive like
  `add_book`; refuses when the target format already exists instead of a confirm gate).
  `find_duplicates` is a read-only advisory report (never auto-merges). `email_book` uses the
  plan→confirm gate (AD-012) because sending is outward-facing — data must be reviewed before it
  leaves the machine.
- **AD-017 — Format file-path resolution lives in `SqliteReader`.** `format_files(book_id)` resolves
  each format's on-disk path (`{library}/{books.path}/{data.name}.{ext}`), reused by convert (source)
  and email (attachment). Reads stay in the read layer (AD-001); `SqliteReader` gains the library root
  in its constructor.

- **AD-018 — Project direction: personal use, polished (not open source).** Confirmed 2026-07-17.
  Single user, single library; no packaging/distribution/multi-library-config work planned.
  STATS-01 is now in-spec (Phase 1); see `.specs/features/library-stats/spec.md`.
- **AD-019 — Ambition: full GUI replacement, resequenced roadmap.** Confirmed 2026-07-17. User
  wants calibre-mcp to eventually cover everything they currently use the Calibre GUI for — covers,
  bulk operations, author/tag/series organization, library maintenance — "the best server
  possible... fast and very good," not just the narrower P1/P2/enrichment scope. Does not revise
  AD-018 (still personal use, still no packaging). Resequences the previous roadmap: Phase 2 is
  now Bulk Operations & Library Organization (no new external dependency, reuses existing Verified
  primitives) instead of Metadata Enrichment — enrichment/covers move to Phase 3 since they
  introduce the project's first outbound-network dependency and deserve their own hardening pass.
  Full roadmap — phases, candidate features, phase-gates — lives in `.specs/ROADMAP.md`.
- **AD-020 — Multi-book batch pattern (best-effort loop + batch token).** Established by BULK-01,
  reused across Phase 2. A multi-book operation (a) validates batch-level input **before** any
  backup/write (bad field/target/id has no valid interpretation for the batch → fail fast, no
  partial state); (b) takes **exactly one** `metadata.db` backup before the loop as the single
  rollback point (AD-011); (c) processes `sorted(book_ids)` **best-effort** — a per-book failure
  never aborts the batch and never reports a fake "all succeeded"; every book lands in exactly one
  result bucket (`applied`/`failed` for BULK-01; `converted`/`skipped`/`failed` for BULK-02, which
  adds `skipped` for benign no-ops). For **destructive/overwriting** batches a single deterministic
  batch **confirmation token** — `plan_token` over a sentinel `book_id=0` + payload
  `{book_ids: sorted, …}` — gates the whole batch (AD-012); for **additive** batches (convert) there
  is **no token** (AD-016). ORGN-01/02/03 consume this pattern as their apply step.

- **AD-021 — Filesystem discovery is its own pure module.** Directory scanning (folder import,
  BULK-03, and any future tree-walk) lives in a dedicated pure module (`folder_scan.py`), never in
  `SqliteReader` (metadata.db-only, AD-001/AD-017), never inline in the `CalibreLibrary` facade, and
  never in the tool layer. Extends the existing invariant (tool layer touches no `sqlite3`/`subprocess`
  directly) to name **filesystem-walk** as a third I/O kind that the facade *orchestrates* but does
  not *perform*. The scan module has no `calibredb`/`sqlite3` dependency and reads the filesystem
  only (`os.walk`, `followlinks=False`, hidden entries pruned). The facade converts a scan-time
  `OSError` into an `InvalidInputError` so the tool-layer error mapping (`_map_errors`, which only
  catches `CalibreMcpError`) stays whole. Established by BULK-03 (`folder-import`).

## Backlog — deferred (post-P2)

- (empty — STATS-01 + BULK-01 + BULK-02 + BULK-03 shipped; see Handoff. Remaining Phase-2 targets:
  ORGN-01/02/03 not yet spec'd — see `.specs/ROADMAP.md`.)

## Environment

- Calibre 8.2.100 installed: `calibredb`, `ebook-convert` on PATH. Python 3.12.3.
- Real test library available: `/home/gustavo/Documents/BibliotecaCalibre/metadata.db`
  (also a second one at `/home/gustavo/Documents/metadata.db`).

## Handoff

- **Shipped & Verified:** Phase 0 (P1 + P2), Phase 1 (STATS-01), and Phase 2 BULK-01 + BULK-02 +
  BULK-03 — all committed with independent-Verifier PASS reports.
  - **P1 / P2** (`calibre-management`, `calibre-management-p2`): read + curate + convert +
    find_duplicates + email. `SqliteReader` constructor takes `(db_path, library_path)`.
  - **STATS-01** (`library-stats`, Phase 1): `calibre://library/stats` MCP resource (Option A,
    user-confirmed) — reader `library_stats()` aggregate profile + duplicate flags reusing ORG-01,
    exposed via the resource surface with `_map_resource_errors`. Design/tasks/validation PASS in
    `.specs/features/library-stats/`. Closed out in commit `f602fba`.
  - **BULK-01** (`bulk-metadata-edit`, Phase 2): `update_metadata_bulk` — broadcast fields to N books
    via one batch plan→confirm token + one backup + best-effort per-book `applied`/`failed`, with
    `list_mode` add/remove/replace for list fields (new pure `bulk_edit.py`). Verifier PASS
    (`.specs/features/bulk-metadata-edit/validation.md`). Established the AD-020 multi-book pattern.
  - **BULK-02** (`bulk-convert`, Phase 2): `convert_book_bulk` — broadcast one `target_format` to N
    books, additive/no-token (AD-016), one `metadata.db` backup before the batch, best-effort
    **three-bucket** result `converted`/`skipped`/`failed` (AD-020, adds `skipped` for benign
    no-ops). 50-book cap rejected as invalid input; duplicate/non-int/bool ids rejected pre-backup.
    Refactor extracted a shared convert core (`_classify_convert` = skip-as-data / `_convert_and_attach`
    = convert+add_format) reused by the single `convert_book`. Verifier PASS (3/3 mutants killed),
    `.specs/features/bulk-convert/validation.md`. Commits `c054920`/`af071ab`/`1bfb445`. One
    user-approved decision: single `convert_book` now backs up *before* the shared convert (unifying
    with the bulk one-backup order); its CONV-01 bogus-source assertion was aligned to spec AC-5
    (a pre-convert snapshot is harmless under AD-011). Full suite: 211 passed; mypy + ruff clean.
  - **BULK-03** (`folder-import`, Phase 2): `import_folder` — recursive ebook discovery under a
    directory (new pure `folder_scan.py`, case-insensitive 19-ext whitelist, hidden/dotfile excluded,
    no symlink-follow, sorted) imported additive/no-token (AD-016) in one batch: one `metadata.db`
    backup before the loop, best-effort **three-bucket** result `added`/`duplicate`/`failed`
    (AD-020). 500-candidate cap rejected pre-backup (boundary 500 accepted/501 rejected); non-dir and
    unreadable-dir also rejected pre-backup. Refactor extracted a shared add core (`_import_one`,
    no backup inside — L-006) reused by the single `add_book`. New **AD-021** (filesystem discovery
    is its own pure module — the sqlite/subprocess invariant gains a third named I/O kind). Verifier
    PASS (4/4 mutants killed), `.specs/features/folder-import/validation.md`. Commits
    `bab26e1`/`076bc5e`/`9fd7b71`/`015fafe`. Full suite: 236 passed; mypy + ruff clean.
- **Next Phase-2 targets after BULK-03:** ORGN-01/02/03 (author/tag rename, duplicate merge) — not
  yet spec'd. Full roadmap in `.specs/ROADMAP.md`.
- **Specs:** `calibre-management` (P1, 31 req), `calibre-management-p2` (P2, 3 req),
  `library-stats` (STATS-01), `bulk-metadata-edit` (BULK-01, 9 req `BEDIT`),
  `bulk-convert` (BULK-02, 6 req `BCONV`), `folder-import` (BULK-03, 7 req `BIMPORT`). Stack: uv +
  pytest + ruff; test-safety rule enforced via the `scratch_library` fixture (writes never touch the
  real library).
