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

- **AD-018 (SUPERSEDED by AD-023) — Project direction: personal use, polished (not open source).**
  Confirmed 2026-07-17. Single user, single library; no packaging/distribution/multi-library-config
  work planned. STATS-01 is now in-spec (Phase 1); see `.specs/features/library-stats/spec.md`.
  Superseded 2026-07-31: the repo was already public + MIT since 2026-07-17, so this line no longer
  described reality; AD-023 adopts open-source-as-brand explicitly.
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

- **AD-022 — `calibredb set_metadata` serializes authors with ` & `, other list fields with `,`.**
  Establishes that the author field is separator-sensitive: `calibredb set_metadata --field
  "authors:A,B"` creates a single author `"A|B"`, whereas `"authors:A & B"` creates two. The shared
  write primitive (`CalibredbRunner.set_metadata`) therefore joins `authors` with `" & "` and
  `tags`/`languages` with `","`. Corrects a latent multi-author bug that predated ORGN-01 (BULK-01's
  author path was never exercised with more than one author). Established by ORGN-01 (`author-rename`).

- **AD-023 — Direction: open-source-as-brand (supersedes AD-018).** Confirmed 2026-07-31. The
  repo has been public + MIT since 2026-07-17, so "not open source" (AD-018) never matched reality;
  this decision makes the posture explicit and acts on it. **Why:** market evidence — there are
  already ~10 read-only Calibre MCP servers, all free, and MCP servers are near-impossible to
  monetize directly (the host captures the value, not a local-file wrapper). Charging for
  calibre-mcp is a dead end (wrong market, no moat, free competition). Its real leverage is
  (a) a portfolio-grade proof of *how to design a mutation tool that's allowed to delete a user's
  files* and (b) a reference prototype of a reusable **safe-mutation, human-in-the-loop MCP
  pattern**. **Consequence:** the one defensible niche is *safe writes* — every competitor is
  read-only/search. Positioning, README, and packaging lead with that differentiator (see Strategic
  Horizon → Phase A in `.specs/ROADMAP.md`). Packaging becomes in-scope (reverses AD-018's "no
  packaging"): frictionless `uvx --from git+…` install now, PyPI publish is a checkpointed one-way
  door to decide later. Does not change AD-002/003 (still local stdio, no network transport) or the
  single-library model (AD-007). The productize-the-pattern and vertical-that-pays bets (Phases B/C)
  are strategy, recorded in the roadmap's Strategic Horizon, not committed calibre-mcp features.

- **AD-024 — A tool may return MCP image content; the read layer resolves the path, FastMCP reads
  the bytes.** Established by COVER-01 (`read_cover`), the project's first non-text tool result.
  The read layer resolves and validates the file path (same `is_file()` discipline as
  `format_files`, AD-017); `FastMCP.Image(path=...)` performs the byte read + base64 encode — our
  code never reads image bytes, so no new I/O kind enters the facade/tool and the
  reads-go-through-the-read-layer invariant holds. `_map_errors` is now generic (`Callable[..., T]
  -> Callable[..., T]`, PEP 695 syntax) so a non-`dict` tool result typechecks; every existing
  dict-returning tool is unaffected (pure typing change). **SPEC_DEVIATION from design.md:** the
  design specified the tool's return annotation as `Image | dict`, but the installed mcp SDK
  (1.28.1) crashes at tool *registration* on that annotation — building the union's
  structured-output schema calls `pydantic.create_model()` unconditionally (even under
  `structured_output=False`), and pydantic has no schema for `Image` (`PydanticSchemaGenerationError`).
  `read_cover` is annotated `-> Any` instead; verified empirically that this produces the identical
  runtime wire behavior (FastMCP's content conversion dispatches on the actual returned value's
  type, not the static annotation) and the same `output_schema = None` either way — so the intended
  contract (image content on has-cover, structured dict on no-cover) is unchanged, only the
  annotation differs from the design doc. Future non-text tool results should default straight to
  `-> Any` rather than a real `Image | dict` union.

- **AD-025 — Dedicated `set_cover` tool, not a field on `update_metadata`.** Established by
  COVER-02 (`set_cover`). A cover's value is a **filesystem image path**, not a metadata string —
  it needs different validation (`is_file()` + an image-extension whitelist) and a replace-vs-add
  plan (`current_has_cover`, reusing `cover_file` from AD-024/COVER-01), so folding it into
  `update_metadata`'s string-field whitelist would mix a path-typed input into a string editor and
  complicate that tool's diff/validation. **The durable lesson**: `calibredb set_metadata --field
  cover:<path>` **silently no-ops on a missing/unreadable path** (verified) — cover-setting MUST
  pre-validate the file exists (`is_file()` + extension) before any backup/write, and MUST re-read
  the cover state after apply to demonstrate the result, never assert it. **SPEC_DEVIATION from
  design.md's Risks table:** the design additionally assumed a *decoded* bad image (valid
  extension, undecodable content) would also silently no-op the same way, needing the identical
  re-read defense. Empirically verified 2026-07-31 this is not what happens — a genuine decode
  failure makes `calibredb` crash with a non-zero exit (`CalibredbError` propagates loudly, does
  NOT silently no-op); only the missing-path case is silent. The re-read-to-demonstrate discipline
  is still correct practice (defense in depth, matches the sibling mutations' "demonstrated not
  asserted" pattern) — it just was never observed catching a decode failure in practice, since that
  case already fails loudly on its own.

- **AD-026 — First outbound-network policy: HTTP is a fourth I/O kind, confined and bounded.**
  Established by ENRICH-01 (`identifier-lookup`), the project's first outbound network call.
  **Context:** ENRICH-01 looks up gap-filling metadata from Open Library keyed on a book's ISBN —
  the first time the server reaches the internet. This does NOT revise AD-002/003: those keep the
  *transport* local stdio with no listening surface; this is an *outbound* GET the tool makes
  per-call, user-initiated (the tool call is the opt-in), sending only the ISBN (no secrets, no PII).
  **Decision:** all HTTP + cover-download I/O lives in one dedicated sibling module
  (`openlibrary_client.py`); the facade *orchestrates* but never *performs* the network I/O —
  extending the "one module per external I/O kind" invariant (AD-014 CLIs, AD-021 filesystem walk)
  to name **HTTP** as the fourth kind. Every request is bounded — default 10 s timeout + **at most
  one retry** — so the stdio server can never hang; every transport / HTTP ≥ 400 / parse failure
  maps to a single `EnrichmentSourceError` (a `CalibreMcpError`, so `_map_errors` turns it into a
  clean `ToolError`) — never a crash, never partial state. The client takes an injectable `http_get`
  seam so **tests never touch the real Open Library** — the network analog of the never-touch-the-
  real-library write rule, non-negotiable. Covers are fetched via the non-rate-limited cover-**id**
  URL (id/OLID are exempt from Open Library's 100-req / 5-min limit; by-ISBN is not). **Consequences:**
  the lookup is read-only — no plan→confirm gate, no backup, nothing is written (applying is
  ENRICH-02 / COVER-02, which gate); a failed cover or description follow-up is **non-fatal**
  (best-effort) so a failed image never loses the core text proposal; stdlib `urllib.request` covers
  the GETs with no new dependency (keeps the single-dep `uvx` install, AD-023). **Numbering:** AD-025
  was taken by COVER-02, so this is AD-026.

- **AD-027 — Batch outbound policy: a bounded, read-only sweep, never a bulk apply.**
  Established by ENRICH-03 (`enrichment-batch`), the batch twin of ENRICH-01. **Context:** ENRICH-01
  (AD-026) explicitly *deferred* the rate-limit question ("revisit only if ENRICH-03 batches hit the
  limit"); ENRICH-03 is that revisit — one call sweeps the shelf's enrichable-but-incomplete books
  and returns N proposals. **Decision:** the outbound volume is bounded by a **default cap (25) + hard
  ceiling (100) + `offset` paging**, not a token-bucket limiter (still single-user, low volume); a
  bound outside `1..100` (or a non-int / negative offset) is rejected as `InvalidInputError`
  **before any selection or network call** — never clamped into a huge sweep. The batch is
  **read-only advisory** (AD-016) — no `calibredb`, no backup, no confirmation token — and **never
  bulk-applies**: `results` are proposals the host walks and applies per book through the ENRICH-02
  chain. It adds **no new outbound site** — the sole HTTP module (AD-026) is reached only *through*
  `enrich_from_identifier`, one sequential lookup per candidate (each carrying LOOKUP-10's own
  timeout/retry). Per-book failure is **isolated** (AD-020 best-effort bucketing): one candidate's
  `EnrichmentSourceError` becomes that item's `status:"error"` and the sweep continues — a single
  offline blip never discards the other proposals. Candidate selection is a reader SQL query reusing
  the *exact* `_stats_completeness` "missing" rules (comments/publisher/placeholder-pubdate) + a
  non-blank `isbn` guard — one business rule, no drift. **Consequences:** the result is a bucketed
  `{proposed, no_new_data, no_record, error}` summary + `candidate_count` vs `processed` so the host
  can tell more remain and page them; nothing in the payload suggests a write happened (no token, no
  `applied` field). Tool: `enrich_missing` (sibling of `enrich_from_identifier`). One documented,
  intentional SPEC note: the residual "isbn present but normalizes to empty" negative folds into
  `no_record` (rare, guarded by the SQL `trim(val) != ''`).
- **AD-028 — Library path has no single source of truth across the two consumers (ops debt).**
  **Context:** the library moved on disk (`~/Documents/BibliotecaCalibre` →
  `~/Documents/livros/biblioteca`) during a workspace reorg. Nothing in *this* repo broke — the
  server correctly reads `CALIBRE_LIBRARY_PATH` (AD-007) — but the path is duplicated in **two
  places the server doesn't own**: the Calibre GUI config (`~/.config/calibre/global.py.json:
  library_path`) and the host's MCP env (`.claude.json: mcpServers.calibre.env`). Moving the
  library means editing both by hand; a stale env fails fast at startup (`ConfigError`) rather than
  silently, which is the intended safety, but the duplication is friction. **Decision:** accept the
  duplication for now — a single-user, single-library tool (AD-007) doesn't justify a resolver, and
  a config-discovery feature would reintroduce the very ambiguity AD-007 removed. **Debt tracked:**
  if the library moves again and the double-edit bites, revisit — options are (a) a tiny
  `calibre-mcp doctor` that prints/validates the resolved path so the host copies one value, or
  (b) reading the GUI's `library_path` as a fallback when the env is unset. Neither is scheduled.
  The operational contract (both files must agree) is documented host-side in
  `~/projects/10_dotfiles/docs/livros-calibre.md`.
- **AD-029 — Test samples are synthetic; the real library is opt-in and read-only.** Confirmed
  2026-10-01. **Context:** 14 test modules copied sample `.epub` files out of a hard-coded personal
  path (`~/Documents/BibliotecaCalibre`). After the library moved (AD-028) — and in CI, where that
  path never existed — **183 of 387 tests skipped silently** while the suite stayed green; the
  "387 passed" gates recorded above were only true on the maintainer's machine before the move.
  **Decision:** `tests/sample_books.py` builds distinct synthetic epubs with `ebook-convert` (present
  wherever `calibredb` is, incl. CI), cached once per run; the `real_library` fixture reads
  `CALIBRE_MCP_TEST_REAL_LIBRARY` (unset → skip) instead of a personal path; snapshot-pinned counts
  in the real-library read tests became invariants (they had already drifted: 170 → 194 books);
  `pytest -rs` is on by default so skips are always visible. **Consequences:** 358 passed / 34
  skipped (all 34 = opt-in real-library reads, which pass 47/47 when opted in); CI now runs the
  write path for real, at ~2× runtime.
- **AD-030 — `rating` crosses the `calibredb` boundary as stars.** Confirmed 2026-10-01, found by the
  first live smoke run against the real library (`docs/live-smoke-test.md`): `update_metadata(rating:
  8)` stored **10**. `calibredb set_metadata --field rating:N` takes **stars (0–5)** and stores N×2,
  while the tool contract, validation and `SqliteReader` all use the stored 0–10 scale — so every
  rating write was doubled (clamped at 10). No test had ever round-tripped a rating. **Decision:**
  `CalibredbRunner` halves `rating` when rendering `--field` (`_format_field_value`, half stars as
  `3.5`); the 0–10 contract stays unchanged for callers. Covered by a parametrized round-trip test
  (2/7/8/10; it was red for 2/7/8 before the fix). Bulk edit shares the same runner path.
- **AD-031 — Planning split into tactical roadmap / strategic roadmap / backlog.** Confirmed
  2026-10-01, following the workspace roadmap standard (`_hq/biblioteca/roadmaps`:
  `ROADMAP-projeto-PADRAO` for delivery, `IK-roadmap-estrategico` for strategy). The single
  `.specs/ROADMAP.md` (moved to the repo root) mixed a per-feature pipeline with quarterly,
  signal-gated bets and unspecified ideas. Now: `ROADMAP.md` (versions v0.1–v1.0, one row per
  Feature, phase gates, inherited debt), `ROADMAP-STRATEGY.md` (Phase A/B/C by quarter, gates,
  business risks), `BACKLOG.md` (unsequenced ideas by domain, evidence-tagged). Phase labels are
  kept in the tactical roadmap because every spec cites them.

- **AD-032 — ISBN-less enrichment searches by title/author; only a confident match proposes; requests
  are paced.** Confirmed 2026-10-01 (ENRICH-04, `title-search-enrichment`; user decisions A1/A2).
  **Context:** only 51/194 books carry an ISBN, so ENRICH-01..03 reached 7 books. **Decision:**
  (1) `enrich_from_identifier` falls back to Open Library *search* (title + primary author, ≤5 works,
  one title-only retry) when there is no usable ISBN — same tool, plus a `match` block; (2) a
  deterministic matcher (`title_match.py`, stdlib `difflib`, no LLM per AD-006) scores candidates —
  `high` needs title ≥ 0.90 **and** author ≥ 0.85, never without a usable book author; (3) only a
  `high` match proposes, and only work-level fields (description → `comments`, cover) — never
  publisher/pubdate, which are edition-specific; (4) `enrich_missing` sweeps ISBN-less books
  missing comments or a cover, with a new `no_confident_match` bucket; (5) every Open Library
  request is paced to ≥ 1 s apart, per its documented limit for unidentified clients (the client had
  no pacing before). **Supersedes** LOOKUP-02 (no ISBN → no network; now: no ISBN *and* no usable
  title) and ENRICH3-01 (candidates need an ISBN). Extends AD-026/027 (still one HTTP module,
  still a bounded read-only sweep). **Consequences — measured on the real library (read-only dry
  run, metadata.db hash unchanged):** 142 candidates → 4 `proposed` (3 ISBN, 1 search), 13
  `no_new_data`, 87 `no_record`, 38 `no_confident_match`, 0 errors. The matcher finds the right book
  (11 `high`, all correct), but **10 of those 11 Open Library works have no description** — the
  completeness gap is now *source-limited*, not lookup-limited. A full sweep takes minutes at 1 req/s.

## Backlog — deferred (post-P2)

- Moved to [`BACKLOG.md`](../BACKLOG.md) (AD-031) — this section is no longer maintained.

## Environment

- Calibre 8.2.100 installed: `calibredb`, `ebook-convert` on PATH. Python 3.12.3.
- Real library (moved 2026-09, AD-028): `/home/gustavo/Documents/livros/biblioteca/metadata.db`.
  Tests never depend on it (AD-029); opt in to the read-only checks with
  `CALIBRE_MCP_TEST_REAL_LIBRARY=/home/gustavo/Documents/livros/biblioteca`.
- If `uv run pytest` fails with "Failed to spawn", the `.venv` was created before the repo moved
  (stale shebangs) — `uv sync --reinstall` fixes it.

## Handoff

- **Shipped & Verified:** Phase 0 (P1 + P2), Phase 1 (STATS-01), and Phase 2 in full — BULK-01 +
  BULK-02 + BULK-03 + ORGN-01 + ORGN-02 + ORGN-03 + ORGN-04 — all committed with
  independent-Verifier PASS reports. **Phase 2 phase-gate is closed** (2026-07-31): a full curation
  session (retag a batch, fix an author's name everywhere, resolve a duplicate group, import a
  folder, fix a series' name) never requires the Calibre GUI.
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
  - **ORGN-01** (`author-rename`, Phase 2): `rename_author` — rename one author across every credited
    book via one batch plan→confirm token, co-author-safe swap + in-book merge/dedupe
    (`resolve_renamed_authors`, now aliasing the shared `rename_resolve.resolve_renamed_values`),
    `books_by_author` exact-match discovery, one backup before the loop. Established **AD-022**
    (`set_metadata` must join `authors` with `" & "`, not `,`, to avoid mashing co-authors into one
    entity — a prerequisite correctness fix, also fixed BULK-01's latent same bug). Verifier PASS
    (8/8 ARENAME, 3/3 mutants killed), `.specs/features/author-rename/validation.md`.
  - **ORGN-02** (`tag-rename`, Phase 2): `rename_tag` — tag-scoped twin of ORGN-01: `books_by_tag`
    discovery, the resolve rule *generalized* to shared `rename_resolve.resolve_renamed_values`
    (author/tag now share one pure algebra instead of duplicating it) rather than cloned. No
    prerequisite serialization fix needed — AD-022 already joins `tags` with `,` correctly. Tags are
    a set: re-read assertions use set-equality, not positional order. Independent Verifier PASS
    (8/8 TRENAME; two disjoint discrimination-sensor runs, author 3/3 + verifier 4/4, 7/7 killed),
    `.specs/features/tag-rename/validation.md`.
  - **ORGN-03** (`merge-duplicate-group`, Phase 2): `merge_duplicate_group` — the one Phase-2
    organization feature that **deletes book records**. User-decided scope (2026-07-31):
    caller-chosen `survivor_id`/`loser_ids` (no auto-pick), **formats-only** merge (survivor metadata
    untouched — field enrichment deferred to Phase 3). No new mutation primitive: orchestrates
    already-Verified `format_files`/`add_format --dont-replace`/the `remove_book` recoverable-delete
    sequence, gated like `remove_book` extended to an AD-020 batch. Core invariant — a loser's
    formats are attached to the survivor **before** that loser is recoverably deleted; an attach
    failure leaves the loser untouched. Independent Verifier PASS (8/8 MERGE; two disjoint sensor
    runs, author 3/3 + verifier 4/4, 7/7 killed) **plus a structural code-trace** confirming the
    removal lines are unreachable except after a fully-completed attach loop — the data-safety
    ordering is a guarantee, not just a tested behavior. `.specs/features/merge-duplicate-group/validation.md`.
- **ORGN-04** (`series-rename`, Phase 2 follow-on, closes the AD-019 author/tag/series organization
  triad): `rename_series` — series-scoped sibling of ORGN-01/02 (`books_by_series` discovery, facade
  plan→confirm batch, MCP tool). Key divergence from ORGN-01/02: series is a single-valued field, so
  there is no list resolver — the apply writes `{"series": new_series}` ONLY, never `series_index`,
  so each book's position survives the rename (SRENAME-07, empirically verified against `calibredb`
  and covered by a fractional-index (`7.5`) round-trip test). The real library has 0 books in any
  series (`series_unused`), so all tests seed a `scratch_library` rather than anchoring on the real
  one. **Shipped & Verified** (independent Verifier PASS, 8/8 SRENAME matched spec-defined outcomes,
  3/3 discrimination-sensor mutants killed, `.specs/features/series-rename/validation.md`,
  commit `b4f0598`) — this Handoff entry was simply never updated after that Verified commit until
  now (found while closing out COVER-01); Phase 2 was in fact fully closed at that point.
- **COVER-01** (`cover-read`, Phase 3 — Covers & Metadata Enrichment): `read_cover` — T1-T3
  implemented (`SqliteReader.cover_file` has_cover-keyed path resolution, `CalibreLibrary
  .read_cover` dict facade, `read_cover` MCP tool returning viewable image content). **Shipped &
  Verified** (commit `94044f4`): independent Verifier PASS, 5/5 RCOVER requirements matched
  spec-defined outcomes, 3/3 discrimination-sensor mutants killed, full build gate 318 passed.
  First tool to return non-text (image) content — see **AD-024** (incl. a SPEC_DEVIATION: `-> Any`
  return annotation instead of design's `Image | dict`, forced by an mcp-SDK schema-generation
  crash on that union, same runtime wire behavior verified). Test-seeding note: a real sample
  `.epub`'s embedded cover gets auto-extracted by `calibredb add`, so cover/no-cover fixtures seed
  via `calibredb add --empty` + a stdlib-only zlib-PNG helper instead, for deterministic has_cover
  state. `.specs/features/cover-read/validation.md`. (This entry was stale — recorded "Implementing"
  in error until fixed while closing out COVER-02.)
- **COVER-02** (`cover-set`, Phase 3, mutating sibling of COVER-01 — closes the Phase-3 covers
  pair): `set_cover` — `CalibreLibrary.set_cover` plan→confirm facade reusing `cover_file`/
  `set_metadata` unchanged, plus the `set_cover` MCP tool. **Shipped & Verified**: independent
  Verifier PASS, 7/7 SCOVER requirements + L-001 matched spec-defined outcomes (evidence-or-zero),
  3/3 discrimination-sensor mutants killed, full build gate 329 passed.
  `.specs/features/cover-set/validation.md`. Cover-typed twin of `update_metadata`: validates the
  image file (`is_file()` + extension whitelist) BEFORE any backup/write, since `calibredb`
  silently no-ops on a bad path; apply re-reads `cover_file` to demonstrate the result rather than
  asserting it. New **AD-025** (the dedicated-tool decision + the silent-no-op lesson + a
  SPEC_DEVIATION: a genuine decode failure was empirically found — and independently reproduced by
  the Verifier — to raise loudly, `CalibredbError`, not silently no-op as design.md assumed).
  **Phase-3 covers pair now closed** (COVER-01 + COVER-02 both Shipped & Verified).
- **ENRICH-01** (`identifier-lookup`, Phase 3 — the project's first outbound-network feature):
  `enrich_from_identifier` — a **read-only** ISBN lookup that proposes gap-filling
  `comments`/`publisher`/`pubdate` from Open Library plus a downloaded cover, writing NOTHING (the
  advisory precedent of `find_duplicates`, AD-016). New sibling module `openlibrary_client.py` (the
  sole outbound-I/O site: Books API + edition→work description follow-up + cover-id download,
  bounded 10 s timeout + ≤1 retry, injectable `http_get` seam so tests never hit the real network),
  new `EnrichmentSourceError` in the taxonomy, `CalibreLibrary.enrich_from_identifier` facade
  (gap-only proposal reusing the `0101-01-01%` placeholder-pubdate rule + `cover_file` COVER-01),
  and the `enrich_from_identifier` MCP tool. New **AD-026** (first outbound-network policy).
  **Shipped & Verified**: independent Verifier PASS (2 iterations — the first flagged two coverage
  gaps, ISBN upper-case edge + LOOKUP-10 User-Agent, both closed by test-only commit `f32dc94`),
  LOOKUP-01..10 all matched spec-defined outcomes (evidence-or-zero), 6/6 discrimination-sensor
  mutants killed across client + facade layers, full suite 361 passed; mypy + ruff clean.
  `.specs/features/identifier-lookup/validation.md`. Test-seeding notes: `calibredb add --empty`
  yields the placeholder pubdate `0101-01-01%` (so an empty book reads as pubdate-missing) and
  stores identifiers verbatim (hyphens/lower-case `x` preserved → the facade normalizes); the
  real outbound `_urllib_get` is exercised via a monkeypatched `urlopen` (UA + timeout + error
  wrapping), everything else through the injectable `http_get` seam (zero real network).
  **Phase-3 Covers & Enrichment: covers pair (COVER-01/02) + ENRICH-01 now closed.**
- **ENRICH-02** (`enrichment-apply`, Phase 3 — routes ENRICH-01's proposal through the existing
  gates): no new tool. User-decided scope (2026-08-07): `enrich_from_identifier`'s `proposed` dict
  is already a strict subset of `update_metadata`'s `ALLOWED_EDIT_FIELDS`, so the host chains
  `enrich_from_identifier` → `update_metadata` (fields) → `set_cover` (cover) — three already-Shipped
  tools, zero new mutation path. Deliverable: new integration test module
  (`tests/integration/test_enrichment_apply.py`, 5 tests / 7 ACs) proving the round-trip, plus a
  docstring cross-reference on `enrich_from_identifier` documenting the two-step flow and two skip
  rules. **Two spec assumptions were corrected against empirically observed `calibredb` behavior**
  while writing the tests: an empty `fields` dict does NOT no-op at `update_metadata`'s apply step —
  it raises `CalibredbError` (`calibredb` rejects a zero-field `set_metadata` call); and `calibredb`
  normalizes a partial `pubdate` string (`"April 2009"`) into a full ISO datetime
  (`"2009-04-15 00:00:00+00:00"`) rather than preserving it verbatim — both documented as
  SPEC_DEVIATION in `.specs/features/enrichment-apply/design.md` and reflected in the final spec
  text. **Shipped & Verified**: independent Verifier PASS, 7/7 ENRICH2 requirements matched
  spec-defined outcomes (evidence-or-zero), 3/3 discrimination-sensor mutants killed across
  `_gap_proposal`/`update_metadata`/`set_cover`, full suite 366 passed (361 + 5 new, no count
  regression); mypy + ruff clean. `.specs/features/enrichment-apply/validation.md`. Commits
  `b57ba83` (tests + spec/design) / `ed5db75` (docstring).
- **ENRICH-03** (`enrichment-batch`, Phase 3 — batch review mode, the batch twin of ENRICH-01):
  new tool `enrich_missing(limit=None, offset=0)`. A bounded, **read-only** sweep (new **AD-027**):
  selects the books that carry an ISBN AND are missing an enrichable field (new reader query
  `enrichable_candidates`, reusing the exact `_stats_completeness` "missing" rules), looks each up
  through the **existing** `enrich_from_identifier` path (zero new network/proposal logic), and
  returns one advisory proposal per book + a bucketed `{proposed, no_new_data, no_record, error}`
  summary — writing NOTHING, NEVER bulk-applying (host walks `results`, applies each per book via the
  ENRICH-02 chain). Bounded: default cap 25 / ceiling 100 / `offset` paging; a bad bound is rejected
  (`InvalidInputError`) before any selection or network call. Per-book `EnrichmentSourceError` is
  isolated to that item (`status:"error"`) and the sweep continues. **Shipped & Verified**:
  independent Verifier PASS, 9/9 ENRICH3 requirements matched spec-defined outcomes (evidence-or-zero),
  4/4 discrimination-sensor mutants killed (isbn guard / error-isolation / cap constant / classifier).
  Full suite **387 passed** (366 + 21 new: 5 reader + 13 batch + 3 e2e); mypy + ruff clean. (The
  Verifier's gate observed 386 at T3, before the ENRICH3-07 end-to-end cap test `6ef64c7` was added.)
  `.specs/features/enrichment-batch/validation.md`. Commits `0cec3d6` (reader) / `1e56ddd`
  (facade) / `6b77862` (tool) / `6ef64c7` (end-to-end cap test closing the Verifier's ENRICH3-07
  caveat). **Phase-3 ENRICH cluster (01/02/03) now closed.**
- **Phase-3 gate check (2026-10-01, live run — `docs/live-smoke-test.md`):** all 21 tools + the
  stats resource exercised against the real library on `MCPTEST` copies; 194/194 real books
  identical field by field afterwards. Gate **not met and not reachable with the shipped features**:
  `enrich_missing` has 7 candidates in 196 books (only 51 carry an ISBN), and stats can't measure
  cover coverage. Found + fixed the rating bug (AD-030); fixed the silently-skipping suite (AD-029).
- **v0.4 closed with debt (2026-10-01):** STATS-02 (`cover-coverage`) + ENRICH-04
  (`title-search-enrichment`, AD-032) shipped; independent Verifier reports in each feature's
  `validation.md`. Gate round 2 on the real library: covers 192/194 (ids 53, 184 not on Open
  Library); completeness KPI **not met** — 4 proposals from 142 candidates, source-limited (10 of 11
  confident matches have no description). Debt rows in `ROADMAP.md`.
- **Next:** **MAINT-04 (metadata rollback)**, v0.5. Before reusing the confirmation token there, decide
  (AD) the token-binding issue in `BACKLOG.md` (⟂ safety). ENRICH-05 (second source) needs an RFD.
- **Specs:** `calibre-management` (P1, 31 req), `calibre-management-p2` (P2, 3 req),
  `library-stats` (STATS-01), `bulk-metadata-edit` (BULK-01, 9 req `BEDIT`),
  `bulk-convert` (BULK-02, 6 req `BCONV`), `folder-import` (BULK-03, 7 req `BIMPORT`),
  `author-rename` (ORGN-01, 8 req `ARENAME`), `tag-rename` (ORGN-02, 8 req `TRENAME`),
  `merge-duplicate-group` (ORGN-03, 8 req `MERGE`), `series-rename` (ORGN-04, 8 req `SRENAME`,
  Verified), `cover-read` (COVER-01, 5 req `RCOVER`, Verified), `cover-set` (COVER-02, 7 req
  `SCOVER`, Verified), `identifier-lookup` (ENRICH-01, 10 req `LOOKUP`, Verified),
  `enrichment-apply` (ENRICH-02, 7 req `ENRICH2`, Verified),
  `enrichment-batch` (ENRICH-03, 9 req `ENRICH3`, Verified). Stack: uv + pytest + ruff;
  test-safety rule enforced via the `scratch_library` fixture (writes never touch the real
  library) + the injectable `http_get` seam (tests never touch the real Open Library).
  Full build gate as of ENRICH-03's closeout: 387 passed, 0 failed; mypy + ruff clean.
  **As of 2026-10-01 (AD-029/030):** 358 passed, 34 skipped (opt-in real-library reads; 47/47 pass
  when opted in), mypy + ruff clean — the first gate where the write path runs without a personal
  library, i.e. the first one CI actually reproduces.
