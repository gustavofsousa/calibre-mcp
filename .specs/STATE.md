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

## Backlog — deferred (post-P2)

- **STATS-01 — Library baseline profile exposed by the server (P3, after P2).** Surface aggregate
  library knowledge — totals, format/language breakdown, metadata completeness, identifier-type mix,
  author/tag distribution, and data-quality flags (Unknown-author count, `0101-01-01` placeholder
  pubdates, unused `series`/`rating`, duplicate-title groups) — so the host knows the library's shape
  on connect **without** paging `list_books` (slow, context-heavy, and it even hid the id 61–114 range
  when we first classified the library).
  - **Motivation / prototype:** validated ad-hoc by reading `metadata.db` read-only and caching the
    result at `.library-profile.json` (gitignored, personal data — never committed). That file is the
    reference schema for what STATS-01 should compute. The direct-DB read caught a real duplicate
    ("A fé explicada", ids 68 & 132) that the paginated listing missed.
  - **Open design decision (resolve when picked up):**
    - *Option A — MCP resource* (`resources/list` + `resources/read`, e.g. `calibre://library/stats`):
      host can auto-load on connect; fits "known without a tool call". Freshness: compute on read, or
      cache with a generated-at stamp + cheap invalidation.
    - *Option B — `library_stats` read tool*: recomputed on demand from `metadata.db`; simpler, always
      fresh, but the host must choose to call it (not auto-known).
    - *Recommendation:* **A** for the auto-known-on-connect goal, computed on read (metadata.db is
      small; the SQLite reader is already read-only and lock-independent). Reuse `SqliteReader` behind
      the `CalibreLibrary` facade per the existing invariant — no new SQL in the tool/resource layer.
  - **Scope guard:** read-only, additive, no write path; must not violate the stderr-only / arg-list
    invariants. Deferred until P2 (CONV-01, ORG-01) ships and traction warrants.

## Environment

- Calibre 8.2.100 installed: `calibredb`, `ebook-convert` on PATH. Python 3.12.3.
- Real test library available: `/home/gustavo/Documents/BibliotecaCalibre/metadata.db`
  (also a second one at `/home/gustavo/Documents/metadata.db`).

## Handoff

- **Phase:** Execute — COMPLETE. All 10 tasks (T1–T10) implemented and committed; 29/29 P1
  requirements covered. Full gate green: `ruff check` clean + `pytest` 86 passed. End-to-end
  demonstrated: server boots over stdio, MCP `initialize` + `tools/list` returns all 6 tools, and
  a live `list_books` call reads the real library. Packaging finished: `calibre-mcp` console script
  (`[project.scripts]`) + `python -m calibre_mcp` entry point; README with Claude Desktop/Code setup.
- **Next step:** P2 Execute IN PROGRESS (2026-07-17) — `.specs/features/calibre-management-p2/`.
  Phase 1 (T1 errors, T2 SMTP config) and Phase 2 (T3 reader format_files/find_duplicate_groups,
  T4 EbookConvertRunner, T5 CalibreSmtpRunner, T6 calibredb add_format) are **done**, each its own
  atomic commit, executed inline (user declined per-phase sub-agents). Full gate green after every
  task: `ruff check` clean + `pytest` 111 passed (up from 88 at P1). `SqliteReader` constructor now
  takes `(db_path, library_path)` — `CalibreLibrary` and existing tests updated to match.
  **Remaining:** Phase 3 (T7 facade `find_duplicates`, T8 facade `convert_book`, T9 facade
  `email_book` — sequential, same file `library.py`) and Phase 4 (T10 FastMCP tool surface). The
  feature-level Verifier has NOT run yet — it only runs after T10 (the last task). Do not report P2
  as done until T7–T10 are implemented and the Verifier returns PASS.
  Env verified: `ebook-convert` + `calibre-smtp` on PATH (Calibre 8.2.100).
- **Spec:** `.specs/features/calibre-management/spec.md` (31 requirements, 29 P1 / 2 P2).
- **Design:** `.specs/features/calibre-management/design.md` (8 modules: config, errors,
  sqlite_reader, calibredb_runner, backup, confirmation, library, server).
- **Tasks:** `.specs/features/calibre-management/tasks.md` — Phase 1 (T1 scaffold→T2 errors→T3 config),
  Phase 2 [P] (T4 reader, T5 backup, T6 confirm, T7 runner), Phase 3 (T8 facade reads→T9 facade
  mutations), Phase 4 (T10 server). Stack: uv + pytest + ruff (ruff = new MICRO tooling choice).
  Test-safety rule enforced via `scratch_library` fixture (writes never touch the real library).
