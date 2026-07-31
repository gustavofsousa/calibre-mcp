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

## Backlog — deferred (post-P2)

- (empty — Phase 2 fully closed: STATS-01 + BULK-01/02/03 + ORGN-01/02/03/04 all shipped & Verified;
  see Handoff. Phase 3 (Covers & Enrichment) now underway — see `.specs/ROADMAP.md`.)

## Environment

- Calibre 8.2.100 installed: `calibredb`, `ebook-convert` on PATH. Python 3.12.3.
- Real test library available: `/home/gustavo/Documents/BibliotecaCalibre/metadata.db`
  (also a second one at `/home/gustavo/Documents/metadata.db`).

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
- **In progress — COVER-01** (`cover-read`, Phase 3 — Covers & Metadata Enrichment): `read_cover` —
  T1-T3 implemented (`SqliteReader.cover_file` has_cover-keyed path resolution, `CalibreLibrary
  .read_cover` dict facade, `read_cover` MCP tool returning viewable image content), all commits
  green (ruff/mypy/pytest). **Status: Implementing, awaiting independent Verifier PASS** — T3 (this
  entry) is the traceability closeout, not the Verified mark. First tool to return non-text (image)
  content — see **AD-024** (incl. a SPEC_DEVIATION: `-> Any` return annotation instead of design's
  `Image | dict`, forced by an mcp-SDK schema-generation crash on that union, same runtime wire
  behavior verified). Test-seeding note: a real sample `.epub`'s embedded cover gets
  auto-extracted by `calibredb add`, so cover/no-cover fixtures seed via `calibredb add --empty` +
  a stdlib-only zlib-PNG helper instead, for deterministic has_cover state. Spec/design/tasks at
  `.specs/features/cover-read/`.
- **Next:** dispatch the independent Verifier for COVER-01 (spec-anchored check + discrimination
  sensor) — Execute is not done until it PASSes. After that: COVER-02 (`cover-set`, the mutating
  sibling — spec/design/tasks already drafted at `.specs/features/cover-set/`, not yet executed).
  Full roadmap in `.specs/ROADMAP.md`.
- **Specs:** `calibre-management` (P1, 31 req), `calibre-management-p2` (P2, 3 req),
  `library-stats` (STATS-01), `bulk-metadata-edit` (BULK-01, 9 req `BEDIT`),
  `bulk-convert` (BULK-02, 6 req `BCONV`), `folder-import` (BULK-03, 7 req `BIMPORT`),
  `author-rename` (ORGN-01, 8 req `ARENAME`), `tag-rename` (ORGN-02, 8 req `TRENAME`),
  `merge-duplicate-group` (ORGN-03, 8 req `MERGE`), `series-rename` (ORGN-04, 8 req `SRENAME`,
  Implementing), `cover-read` (COVER-01, 5 req `RCOVER`, Implementing). Stack: uv + pytest + ruff;
  test-safety rule enforced via the `scratch_library` fixture (writes never touch the real
  library). Full build gate re-run as the T3 closeout regression: 318 passed, 0 failed; mypy + ruff
  clean.
