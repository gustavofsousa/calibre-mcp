# Read a Book's Cover (COVER-01) Specification

**Phase:** 3 — Covers & Metadata Enrichment (ROADMAP.md)
**Feature id:** COVER-01
**Requirement prefix:** `RCOVER`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md.
COVER-01 is the **read half** of the Phase-3 covers pair and the first feature that returns
**non-text content** (the cover image itself) on the tool surface. It is a pure filesystem read —
no mutation, no backup, no network — mirroring `SqliteReader.format_files`'s path-resolution
discipline (AD-017): the read layer resolves and validates a book-folder file path, and the host
receives it. Its sibling COVER-02 (`set-cover`) reuses the reader method this feature introduces.

## Problem Statement

There is no way to see a book's cover through the MCP today. `list_books`/`get_book` return metadata
but never the cover, and STATS-01 can flag books with no cover but cannot show the ones that have
one. Calibre always stores a book's cover as `cover.jpg` inside the book's own folder
(`{library}/{books.path}/cover.jpg`) and records its presence in the `books.has_cover` column.
COVER-01 exposes that: given a book id, return the cover **as viewable image content** so the host
(an LLM) can actually see and describe it — or a clear "no cover" signal when the book has none —
without opening the Calibre GUI and without any write.

The decision (confirmed with the user at Specify time) is that `read_cover` returns the **image
content itself** (MCP image content, base64), not merely a path. A path is metadata the host could
already derive; the point of *reading* a cover is to view it. This is deliberately different from
`format_files`, which returns a *path* because a CLI (convert/email) consumes it — here the consumer
is a human/LLM who needs to see the image.

## Goals

- [ ] `read_cover(book_id)` returns the book's cover as **viewable image content** (MCP image,
      `image/jpeg`), read from the reader-resolved `{library}/{books.path}/cover.jpg` — no write, no
      backup, no network.
- [ ] A book with **no cover** (`has_cover = 0`) returns a clear structured "no cover" result
      (`has_cover: false`) — **not** an error and **not** a fake/empty image.
- [ ] Honest failure at the boundary: an unknown id is a clear not-found error; a book whose metadata
      claims a cover but whose `cover.jpg` is missing on disk is surfaced as invalid input (a real
      data-quality inconsistency), mirroring `format_files` — never a broken or empty image.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| **Setting / changing** a cover | That is COVER-02 (`set-cover`), the mutating sibling. COVER-01 is read-only. |
| **Fetching** a cover from an external source (Open Library, etc.) | That is the ENRICH cluster (Phase 3, later) — the project's first outbound-network call, gated behind its own AD. COVER-01 never touches the network. |
| Returning cover **thumbnails / resized** variants | The stored `cover.jpg` is returned verbatim; resizing is an image-processing concern the reader has no business doing (AD-006 keeps logic out of the server, and it's not requested). |
| Returning covers for **many** books in one call (bulk) | Single-book read; a bulk "show me all covers" belongs to a future batch-review flow, not this leaf. |
| Extracting an **embedded** cover from an EPUB/PDF when `cover.jpg` is absent | Calibre's own cover cache (`cover.jpg`) is the single source of truth; reaching into format files is a distinct capability, not requested. |
| Reading the cover **path only** (no image bytes) | Rejected at Specify time — the confirmed contract returns the viewable image itself (see Problem Statement). The resolved path still exists internally (facade result) but the tool hands the host the image. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| What the tool returns | **MCP image content** (`FastMCP.Image`, base64 `image/jpeg`) when a cover exists | Confirmed with the user at Specify time: reading a cover is for *viewing* it; a bare path is metadata the host already has. First non-text tool result in the project. | y |
| Book with **no cover** (`has_cover = 0`) | Return `{book_id, has_cover: false, cover_path: null}` — a normal structured result, **not** an error | Missing covers are a common, expected state (STATS-01 flags them); erroring would make "does this book have a cover?" impossible to answer without exception handling. | y |
| `has_cover = 1` but `cover.jpg` **missing on disk** | Reject as **`InvalidInputError`** (metadata↔disk inconsistency), before returning any image | Direct mirror of `format_files` (a format row with no file → `InvalidInputError`, AD-017). A silent "no cover" would hide a real data-quality problem; a broken image would be worse. | y |
| Unknown `book_id` | **`BookNotFoundError`** (→ `ToolError`) | Same contract as every other read (`get_book`, `format_files`); never an empty/misleading result. | y |
| Source of "has cover?" truth | The **`books.has_cover`** column (not "is there a cover.jpg on disk?") | `has_cover` is Calibre's authoritative signal; keying off it and *then* validating the file catches both no-cover and inconsistent-metadata cases cleanly. | y |
| Cover file location | `{library_path}/{books.path}/cover.jpg` (lowercase `cover.jpg`) | Calibre's fixed convention (verified against a real add + `set_metadata --field cover:` round-trip, 2026-07-31 — writes `{book}/cover.jpg`). | y |
| Where path resolution lives | New read-layer method **`SqliteReader.cover_file(book_id) -> Path \| None`** | Reads stay in the read layer (AD-001/AD-017); structural sibling of `format_files`. The facade and tool never touch `sqlite3`/filesystem-walk directly (project invariant). | y |
| Who reads the image **bytes** | **FastMCP** reads them, from the reader-validated path (`Image(path=...)`) | Our code never does raw byte I/O: the reader resolves+validates the path (`is_file()`), FastMCP loads/encodes it. Keeps the invariant intact (no new I/O kind in the facade/tool). | y |
| Cover format / MIME | `image/jpeg` (Calibre stores `cover.jpg`; it re-encodes any input to JPEG — verified 2026-07-31, a PNG input became a 392-byte `cover.jpg`) | Single, predictable MIME; FastMCP infers it from the `.jpg` suffix. | y |
| Read-only guarantee | No `metadata.db` backup, no `calibredb`, no network — pure reader path resolution + FastMCP byte read | It is a read; AD-011's backup-before-write and AD-012's plan→confirm apply only to mutations. | y |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: See a book's cover ⭐ MVP

**User Story**: As the library owner, I want to ask for a book's cover by id and actually *see* the
image, so that I can verify a cover looks right, describe it, or confirm which edition I'm holding —
without opening the Calibre GUI.

**Why P1**: This is the core capability and half of the Phase-3 gate ("every book has a viewable
cover" — you cannot confirm "viewable" without a way to view). It is also the reader primitive
COVER-02 builds on.

**Acceptance Criteria**:

1. WHEN `read_cover(book_id)` is called for a book with a cover (`has_cover = 1` and `cover.jpg`
   present) THEN the system SHALL return the cover as **viewable image content** (`image/jpeg`, the
   bytes of `{library}/{books.path}/cover.jpg`) and SHALL write nothing. *(RCOVER-01)*
2. WHEN `read_cover(book_id)` is called for a book with **no cover** (`has_cover = 0`) THEN the
   system SHALL return a structured result `{book_id, has_cover: false, cover_path: null}` — not an
   error, not an image. *(RCOVER-02)*
3. WHEN `read_cover(book_id)` is called with an id that does not exist THEN the system SHALL raise a
   clear "book not found" error naming the id — never an empty or misleading result. *(RCOVER-03)*
4. WHEN a book has `has_cover = 1` but its `cover.jpg` is **not on disk** THEN the system SHALL
   reject with a clear invalid-input error (metadata↔disk inconsistency), before returning any image
   — mirroring `format_files`. *(RCOVER-04)*
5. WHEN `read_cover` runs (any outcome) THEN it SHALL perform **no** mutation: no `metadata.db`
   backup, no `calibredb` call, no network — a pure read (the reader resolves the path; FastMCP reads
   the bytes). *(RCOVER-05)*

**Independent Test**: Bootstrap a scratch library with two books — one given a real cover
(`calibredb set_metadata <id> --field cover:<valid image>`), one left with no cover. Call
`read_cover` on the covered book and assert the result is image content with MIME `image/jpeg` and
non-empty bytes. Call `read_cover` on the uncovered book and assert `{has_cover: false, cover_path:
null}` (no image, no error). Call `read_cover` on a non-existent id and assert a not-found error.
Delete the covered book's `cover.jpg` from disk (leaving `has_cover = 1`) and assert `read_cover`
now raises invalid input. Assert no `metadata.db` backup file was created by any of these calls.

---

## Edge Cases

- WHEN `has_cover = 0` THEN return the structured no-cover result (RCOVER-02) — never touch the
  filesystem for a `cover.jpg` that is not expected to exist.
- WHEN `has_cover = 1` but `cover.jpg` is missing THEN raise `InvalidInputError` (RCOVER-04) — do not
  silently degrade to "no cover" (that would mask a real inconsistency).
- WHEN the id does not exist THEN raise `BookNotFoundError` before any filesystem access (RCOVER-03).
- WHEN the cover exists THEN the returned MIME SHALL be `image/jpeg` (Calibre stores `cover.jpg`).
- WHEN `read_cover` is called repeatedly THEN it SHALL be idempotent and side-effect-free (RCOVER-05)
  — no backup, no write, safe to call as often as the host likes.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| RCOVER-01 | P1: See a book's cover | Implementing | Verified |
| RCOVER-02 | P1: See a book's cover | Implementing | Verified |
| RCOVER-03 | P1: See a book's cover | Implementing | Verified |
| RCOVER-04 | P1: See a book's cover | Implementing | Verified |
| RCOVER-05 | P1: See a book's cover | Implementing | Verified |

**ID format:** `RCOVER-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 5 total, all mapped to tasks T1–T3 in `tasks.md`; verification pending (independent
Verifier runs after the final Execute task). Design at `.specs/features/cover-read/design.md`.

---

## Success Criteria

How we know the feature is successful:

- [ ] Asking for a covered book's cover returns a viewable `image/jpeg` — the host can see and
      describe it.
- [ ] A book with no cover returns a clear `has_cover: false` result, never an error or empty image.
- [ ] An unknown id is a clear not-found error; a metadata-says-cover-but-file-missing book is a
      clear invalid-input error (not a silent degrade).
- [ ] `read_cover` never writes: no backup, no `calibredb`, no network — provably a read.
- [ ] The new `SqliteReader.cover_file` is a clean sibling of `format_files`, reused unchanged by
      COVER-02.
