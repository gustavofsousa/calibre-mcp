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

- **Phase:** P1 and P2 both COMPLETE and Verified. P1: all 10 tasks (T1–T10), 29/29 P1 requirements.
  P2 (`calibre-management-p2`, 2026-07-17): all 10 tasks (T1–T10) — CONV-01 (`convert_book`), ORG-01
  (`find_duplicates`), EMAIL-01 (`email_book`) — implemented, each its own atomic commit, executed
  inline (user declined per-phase sub-agents). Full gate green: `ruff check` clean + `pytest` 137
  passed (up from 88 at P1 baseline). `SqliteReader` constructor now takes `(db_path, library_path)`.
  The independent Verifier ran after T10, found 1 surviving mutant + 2 coverage gaps (backup-before-
  `add_format` ordering untested for `convert_book`; EMAIL-01 AC-3 explicit-format success path
  untested; T10's stdout-clean assertion didn't cover the 3 new tools) — all three fixed and
  re-verified PASS (iteration 2 of the fix→re-verify loop). Report: `.specs/features/
  calibre-management-p2/validation.md`. **Also fixed in T8**: a real bug in T3's `format_files`
  (`Path.with_suffix` corrupted filenames when Calibre's `data.name` contains a literal period, e.g.
  "Robert C. Martin") — now built by concatenation instead.
- **Next step:** none in flight. STATS-01 (library baseline profile, P3) remains in the Backlog
  section above, deferred until traction warrants — see that section for the two design options.
- **Spec:** `.specs/features/calibre-management/spec.md` (P1, 31 requirements, 29 P1 / 2 P2) and
  `.specs/features/calibre-management-p2/spec.md` (P2, 3 requirements — CONV-01/ORG-01/EMAIL-01, all
  Verified).
- **Design:** `.specs/features/calibre-management/design.md` (P1, 8 modules) and
  `.specs/features/calibre-management-p2/design.md` (P2, adds `EbookConvertRunner`,
  `CalibreSmtpRunner`, `SmtpConfig`, reader/`calibredb_runner` extensions).
- **Tasks:** `.specs/features/calibre-management/tasks.md` (P1) and
  `.specs/features/calibre-management-p2/tasks.md` (P2). Stack: uv + pytest + ruff.
  Test-safety rule enforced via `scratch_library` fixture (writes never touch the real library).
