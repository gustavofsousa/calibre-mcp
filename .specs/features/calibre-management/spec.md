# Calibre Management MCP — Specification

## Problem Statement

Managing a Calibre ebook library today means clicking through the desktop GUI for every
search, metadata fix, or import. There is no way to let an AI assistant (Claude) do curation
work — "find all untagged sci-fi books and tag them", "fix the author on these three", "import
this file and set its series". This feature exposes the library to an LLM host through a set of
reliable MCP tools so the assistant can read and mutate the library in natural language.

## Goals

- [ ] A local MCP server (stdio) exposes read + write tools over one Calibre library.
- [ ] Reads (search / list / view) are fast and never risk library integrity (SQLite read-only).
- [ ] Writes (edit metadata / add / remove) go through `calibredb` so Calibre's integrity logic is respected.
- [ ] Every tool returns structured, LLM-friendly output and surfaces failures explicitly (never a silent wrong result).

## Out of Scope

Explicitly excluded from this feature to prevent scope creep.

| Feature                                   | Reason                                                             |
| ----------------------------------------- | ----------------------------------------------------------------- |
| Format conversion (epub↔mobi)             | P2 — separate feature (`ebook-convert`), not MVP                   |
| Organize / deduplicate / merge            | P2 — depends on the read+write primitives shipped here            |
| AI calls embedded in the server           | Decided: intelligence lives in the host (Claude), not the server  |
| HTTP / remote transport, auth, multi-user | Decided: local stdio only; no network surface                     |
| Global read-only env flag                 | Superseded by per-mutation plan→confirm (AD-012) — stronger, server-enforced intent |
| Undo/restore tooling for backups & trash  | MVP provides the safety net (backups + trash + recycle bin); restoring is manual for now — a later feature |
| Remote file upload (bytes) for add        | Decided: add takes a local filesystem path                        |
| Managing multiple libraries in one server | One server instance = one library (configurable path)             |
| Reading/searching book *content* (RAG)    | Metadata-only management; full-text/semantic search is a later idea |
| Cover image editing / generation          | Not part of the curation loop for MVP                             |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing is left silently unclear.

| Assumption / decision                                                | Chosen default                                                             | Rationale                                                                 | Confirmed? |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------- | ---------- |
| Connection model                                                     | Hybrid: SQLite read `metadata.db`, `calibredb` for writes                 | Fast reads + integrity-safe writes                                        | y          |
| Transport                                                            | Local stdio                                                               | Simplest; no auth/network surface                                         | y          |
| Auth                                                                 | None                                                                       | Local process launched by host; no port                                   | y          |
| Add book input                                                       | Local filesystem path                                                      | No remote upload; server co-located with library                          | y          |
| Stack                                                                | Python + FastMCP (official MCP SDK)                                        | Matches ecosystem + mcp-builder skill; `calibredb` is a subprocess anyway | y          |
| Library location                                                     | Configured via `CALIBRE_LIBRARY_PATH` env var at startup                  | One server = one library; explicit beats guessing                         | y          |
| Which fields are editable                                            | title, authors, tags, series, series_index, rating, comments, publisher, pubdate, languages | The common curation fields `calibredb set_metadata` supports              | y          |
| `remove` is permanent                                               | Yes — `calibredb remove` deletes from library                             | Matches Calibre behavior; destructive action flagged in tool description  | y          |
| Behavior when `calibredb` is locked (Calibre GUI open on same lib)   | Write tools fail with a clear "library is locked by another process" error | Never corrupt; tell the host to close the GUI and retry                   | y          |
| Read/write consistency (SQLite read may lag a just-committed write)  | Accept eventual consistency; a write tool re-reads via `calibredb` to confirm | Single-user local use; staleness window is negligible                     | y          |
| Search implementation                                                | `calibredb search "query"` resolves ids (real Calibre grammar), then SQLite hydrates metadata | Correct grammar over reimplementing a SQL subset; user-confirmed (AD-010) | y          |
| "Reads work when GUI locks the library" scope                        | Guaranteed for `get_book` / `list_books` (pure SQLite). `search_books` depends on `calibredb` and may fail/route through the running instance when locked — it surfaces the error, and `list_books` is the lock-independent fallback | Follows from the search decision (AD-010); honest scoping of the earlier guarantee | y          |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Search & browse the library ⭐ MVP

**User Story**: As a library owner, I want the assistant to search and list my books by
title/author/tag/series so that I can find what I mean in natural language.

**Why P1**: Every curation action starts by locating books; without read, nothing else is usable.

**Acceptance Criteria**:

1. WHEN a `search_books` tool is called with a query THEN the system SHALL resolve matching book ids via `calibredb search "query"` (Calibre's own grammar) and hydrate their full metadata (id, title, authors, tags, series) from `metadata.db`.
2. WHEN a `list_books` tool is called with limit/offset/sort THEN the system SHALL return a page of books ordered by the requested field.
3. WHEN the query matches nothing THEN the system SHALL return an empty result set (not an error).
4. WHEN `CALIBRE_LIBRARY_PATH` is unset or points to a directory with no `metadata.db` THEN the system SHALL fail startup (or the tool call) with a clear, actionable error naming the missing path.

**Independent Test**: Point the server at the real test library, call `search_books("author:asimov")`, see Asimov titles; call with a nonsense query, see empty list.

---

### P1: View a book's full metadata ⭐ MVP

**User Story**: As a library owner, I want to see all metadata for one book so that I can decide what to fix.

**Why P1**: Editing requires seeing the current state first; it's the read half of every edit.

**Acceptance Criteria**:

1. WHEN `get_book` is called with a valid book id THEN the system SHALL return the full metadata record (all standard fields listed in Assumptions) read from `metadata.db`.
2. WHEN `get_book` is called with an id that does not exist THEN the system SHALL return a clear "book not found" error naming the id, not an empty/misleading record.
3. WHEN `get_book` is called with a non-integer id THEN the system SHALL reject it as invalid input before touching the database.

**Independent Test**: Call `get_book` on a known id from the search result, verify fields match Calibre GUI; call on id 999999, get not-found.

---

### P1: Edit metadata ⭐ MVP

**User Story**: As a library owner, I want the assistant to change a book's metadata so that I can fix
authors, tags, series, ratings, etc. by asking.

**Why P1**: The core curation action — the reason to build this at all.

**Acceptance Criteria**:

1. WHEN `update_metadata` is called **without** a `confirmation_token` THEN the system SHALL NOT modify anything and SHALL return a plan: the current→proposed diff per field plus a deterministic `confirmation_token` for that exact change (explicit-intent step, AD-012).
2. WHEN `update_metadata` is called **with** a `confirmation_token` that matches the requested change THEN the system SHALL first back up `metadata.db` (AD-011), then apply the fields via `calibredb set_metadata`, then return the re-read updated record.
3. WHEN the provided `confirmation_token` does not match the requested change THEN the system SHALL refuse to apply and SHALL instruct the caller to re-plan (prevents applying something other than what was reviewed).
4. WHEN a field outside the allowed set is provided THEN the system SHALL reject the call (at the plan step) listing the allowed fields, without producing a token.
5. WHEN `calibredb` exits non-zero (e.g. library locked, bad value) THEN the system SHALL return a failure that includes `calibredb`'s stderr, and SHALL NOT report success.
6. WHEN the book id does not exist THEN the system SHALL return a "book not found" error at the plan step, without running any write.
7. WHEN `series_index` is provided without `series`, or a rating outside 0–10 (Calibre's 0–5 stars ×2) is given THEN the system SHALL reject the input with a specific validation message at the plan step.

**Independent Test**: Call `update_metadata` on a scratch-library book without a token → get a diff + token, library unchanged; call again with the token → tag applied and visible in `get_book`; call with a wrong token → refused; invalid field / locked library → explicit failures.

---

### P1: Add a book ⭐ MVP

**User Story**: As a library owner, I want to import an ebook file by path so that new books enter the
library through the assistant.

**Why P1**: Curation includes intake; add + edit is the "import and tag it" flow.

**Acceptance Criteria**:

1. WHEN `add_book` is called with a path to an existing, readable ebook file THEN the system SHALL first back up `metadata.db` (AD-011), import the file via `calibredb add`, and return the new book id and its parsed metadata.
2. WHEN the path does not exist or is not a file THEN the system SHALL return a clear input error before invoking `calibredb`.
3. WHEN the file appears to duplicate an existing book (Calibre reports it) THEN the system SHALL surface that outcome (added-as-duplicate or skipped) rather than hiding it.
4. WHEN `calibredb add` fails (unsupported/corrupt file) THEN the system SHALL return the failure with `calibredb`'s stderr.

**Independent Test**: Add a sample `.epub` from a path, get back a new id, confirm it in the library; add a nonexistent path, get an input error.

---

### P1: Remove a book ⭐ MVP

**User Story**: As a library owner, I want to remove a book so that I can prune the library by asking.

**Why P1**: Completes the CRUD loop; without remove, mistakes and junk accumulate.

**Acceptance Criteria**:

1. WHEN `remove_book` is called **without** a `confirmation_token` THEN the system SHALL NOT delete anything and SHALL return a review: the book's title/authors/formats, a note that files will be copied to `backups/trash/` and the book sent to the recycle bin (recoverable), plus a deterministic `confirmation_token`.
2. WHEN `remove_book` is called **with** a matching `confirmation_token` THEN the system SHALL, in order: (a) copy the book's files to `backups/trash/<id>-<timestamp>/`, (b) back up `metadata.db`, (c) run `calibredb remove` **without** `--permanent` (recycle bin), then confirm the id removed and report the trash location.
3. WHEN the id does not exist THEN the system SHALL return a "book not found" (no-op) result at the review step, not a false success.
4. WHEN `calibredb remove` fails (e.g. locked) THEN the system SHALL surface the failure and SHALL NOT claim the book was removed; any files already copied to trash remain as a safe leftover.
5. WHEN the `confirmation_token` does not match THEN the system SHALL refuse and instruct the caller to re-review.
6. The `remove_book` tool description SHALL state that removal is recoverable (recycle bin + trash copy) and requires the two-step review→confirm, so the host reviews with the user before confirming.

**Independent Test**: On a scratch library, `remove_book` without token → review + token, book still present; with token → book gone from `get_book`, files present in `backups/trash/`, metadata.db backup created; nonexistent id → not-found; wrong token → refused.

---

### P1: Data-safety net (backup + recoverable delete) ⭐ MVP

**User Story**: As the owner of an irreplaceable library, I want every write protected by an
automatic backup and every delete recoverable, so that no AI action can lose my books or data.

**Why P1**: The user's explicit hard constraint — data must be recoverable. This is a safety
requirement, not a nice-to-have; it gates whether writes are allowed to exist at all.

**Acceptance Criteria**:

1. WHEN any mutation (`update_metadata` apply / `add_book` / `remove_book` apply) runs THEN the system SHALL copy `metadata.db` to `backups/metadata-<timestamp>.db` **before** invoking `calibredb`.
2. WHEN the number of `metadata-*.db` backups exceeds the retention cap (default 20) THEN the system SHALL delete only the oldest surplus backups, keeping the most recent N.
3. WHEN `remove_book` applies THEN the book's files SHALL be copied to `backups/trash/<id>-<timestamp>/` before removal, and removal SHALL use the recycle bin (never `--permanent`).
4. WHEN the backup directory cannot be created or written THEN the mutation SHALL abort with a clear error **before** any `calibredb` write — no unbacked-up write is ever performed.
5. The backup root SHALL default to `<library>/.calibre-mcp-backups/` and be overridable via `CALIBRE_MCP_BACKUP_DIR`.

**Independent Test**: On a scratch library, run an edit → a `metadata-*.db` backup exists before the change; run 25 edits → only 20 backups remain (oldest pruned); remove a book → its files are in `backups/trash/`; make the backup dir unwritable → the mutation aborts without writing.

---

### P2: Convert formats

**User Story**: As a library owner, I want to convert a book between formats so the right device gets the right file.

**Why P2**: Valuable but not required for the read+edit+CRUD curation loop; depends on `ebook-convert`.

**Acceptance Criteria**:

1. WHEN `convert_book` is called with a book id and a target format THEN the system SHALL run `ebook-convert` and add the new format to the book.

---

### P2: Organize & deduplicate

**User Story**: As a library owner, I want to find duplicates and organize books into series/collections in bulk.

**Why P2**: A higher-order workflow built on the P1 read+write primitives.

**Acceptance Criteria**:

1. WHEN `find_duplicates` is called THEN the system SHALL return groups of likely-duplicate books by title+author similarity.

---

### P2: Email a book's file(s)

**User Story**: As a library owner, I want the assistant to email a book's file to an address (the same
thing the Calibre GUI's "Connect/share → Email to…" button does) so I can send myself or someone a book by asking.

**Why P2**: Distribution/delivery, not part of the core read+edit+CRUD curation loop; depends on SMTP config
outside the library. Built on the P1 read primitives (resolve id → attach its format file).

**Acceptance Criteria**:

1. WHEN `email_book` is called with a book id and a recipient address THEN the system SHALL send the book's file as an attachment via Calibre's email mechanism.

**Open questions for P2 design** (do not resolve now):
- Delivery mechanism: Calibre ships `calibre-smtp` (CLI) and the GUI reads its own SMTP config — decide whether to
  shell out to `calibre-smtp`, reuse Calibre's stored SMTP settings, or take SMTP config via env. `calibredb` itself
  does not send email.
- Which format to attach when a book has several (epub/mobi/pdf), and how to pick.
- Recipient allow-list / confirmation step (sending is an outward-facing action — likely wants a plan→confirm gate like edits/removes).

---

## Edge Cases

- WHEN `calibredb` is not found on PATH THEN the system SHALL fail write tools with an explicit "calibredb not installed / not on PATH" error (reads still work via SQLite).
- WHEN `metadata.db` is missing/unreadable THEN the system SHALL fail read tools with a clear path-named error.
- WHEN the Calibre GUI holds a lock on the library THEN write tools SHALL fail with a "locked by another process" message; `get_book`/`list_books` (pure SQLite) SHALL still succeed; `search_books` (via `calibredb`) MAY fail and SHALL surface that failure explicitly rather than returning a misleading empty set.
- WHEN a search query uses Calibre grammar the library doesn't understand THEN the system SHALL return an explicit query error, not a silent empty set masquerading as "no matches".
- WHEN `limit` is absent or huge THEN `list_books` SHALL apply a sane default cap (e.g. 50) and expose `offset` for paging.
- WHEN a text field contains quotes/newlines THEN values SHALL be passed to `calibredb` safely (argument list, never shell-interpolated).

---

## Requirement Traceability

| Requirement ID | Story                     | Phase  | Status  |
| -------------- | ------------------------- | ------ | ------- |
| SEARCH-01      | P1: Search & browse       | Tasks  | Implementing |
| SEARCH-02      | P1: Search & browse       | Tasks  | Implementing |
| SEARCH-03      | P1: Search & browse       | Tasks  | Implementing |
| CFG-01         | P1: Search & browse       | Tasks  | Implementing |
| VIEW-01        | P1: View metadata         | Tasks  | Implementing |
| VIEW-02        | P1: View metadata         | Tasks  | Implementing |
| VIEW-03        | P1: View metadata         | Tasks  | Implementing |
| EDIT-01        | P1: Edit metadata         | Tasks  | Implementing |
| EDIT-02        | P1: Edit metadata         | Tasks  | Implementing |
| EDIT-03        | P1: Edit metadata         | Tasks  | Implementing |
| EDIT-04        | P1: Edit metadata         | Tasks  | Implementing |
| EDIT-05        | P1: Edit metadata         | Tasks  | Implementing |
| EDIT-06        | P1: Edit metadata         | Tasks  | Implementing |
| EDIT-07        | P1: Edit metadata         | Tasks  | Implementing |
| ADD-01         | P1: Add a book            | Tasks  | Implementing |
| ADD-02         | P1: Add a book            | Tasks  | Implementing |
| ADD-03         | P1: Add a book            | Tasks  | Implementing |
| ADD-04         | P1: Add a book            | Tasks  | Implementing |
| REM-01         | P1: Remove a book         | Tasks  | Implementing |
| REM-02         | P1: Remove a book         | Tasks  | Implementing |
| REM-03         | P1: Remove a book         | Tasks  | Implementing |
| REM-04         | P1: Remove a book         | Tasks  | Implementing |
| REM-05         | P1: Remove a book         | Tasks  | Implementing |
| REM-06         | P1: Remove a book         | Tasks  | Implementing |
| SAFE-01        | P1: Data-safety net       | Tasks  | Implementing |
| SAFE-02        | P1: Data-safety net       | Tasks  | Implementing |
| SAFE-03        | P1: Data-safety net       | Tasks  | Implementing |
| SAFE-04        | P1: Data-safety net       | Tasks  | Implementing |
| SAFE-05        | P1: Data-safety net       | Tasks  | Implementing |
| CONV-01        | P2: Convert formats       | -      | Pending |
| ORG-01         | P2: Organize & dedup      | -      | Pending |
| EMAIL-01       | P2: Email a book's file(s)| -      | Pending |

**ID format:** `[CATEGORY]-[NUMBER]`
**Status values:** Pending → In Design → In Tasks → Implementing → Verified
**Coverage:** 32 total (29 P1, 3 P2), 29 P1 mapped to tasks (see `tasks.md`).

---

## Success Criteria

- [ ] Pointed at the real test library, the assistant can find a book, change a tag, and see it reflected — end to end — without touching the GUI.
- [ ] A locked library or a bad input produces an explicit, actionable failure every time (no silent wrong results).
- [ ] Reads never write; writes never bypass `calibredb`.
- [ ] Adding then removing a throwaway book leaves the library recoverable (backup + trash + recycle bin present).
- [ ] **No mutation ever runs without a preceding `metadata.db` backup, and no delete is irrecoverable** — the user's explicit hard constraint.
- [ ] Every edit and delete requires the two-step plan→confirm; a mismatched token never applies.
