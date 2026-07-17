# Calibre Management — P2: Convert, Organize & Email — Spec

**Feature**: `calibre-management-p2`
**Builds on**: `calibre-management` (P1 — read + edit + add/remove, shipped). This is a **separate,
self-contained P2 spec**; it reuses P1's primitives and invariants but tracks its own requirements.
**Traction mode**: MVP.
**Project decisions**: `.specs/STATE.md` (AD-001…AD-017). P2 scope is set by **AD-013**.

---

## Overview

Three tools layered on the P1 curation loop:

1. **Convert formats** (CONV-01) — add a new format to a book via `ebook-convert`, keeping the
   existing format(s). Additive, never destructive.
2. **Organize & deduplicate** (ORG-01) — a read-only report of likely-duplicate books by
   title+author similarity. Advisory only; never auto-merges.
3. **Email a book's file** (EMAIL-01) — send a book's format file to a recipient via `calibre-smtp`.
   Outward-facing → gated by plan→confirm.

All three conform to the P1 invariants: reads via `SqliteReader`, writes/subprocess via runners
(arg-list, `shell=False`), the tool layer never touches `sqlite3`/`subprocess` directly (AD-001),
backup-before-write (AD-011), plan→confirm for gated ops (AD-012).

---

## Requirements

### CONV-01 — Convert formats

**User Story**: As a library owner, I want to convert a book between formats so the right device
gets the right file — **without losing the original format**.

**Why P2**: Valuable but not required for the read+edit+CRUD curation loop; depends on `ebook-convert`.

**Acceptance Criteria**:

1. WHEN `convert_book` is called with a book id and a supported target format THEN the system SHALL
   run `ebook-convert` and add the new format to the book via `calibredb add_format`.
2. The conversion SHALL be **additive**: the book's existing format(s) remain; after a successful
   convert the book has both the old and the new format.
3. WHEN the book already has the target format THEN the system SHALL refuse (no overwrite) with a
   clear message, rather than replacing the existing file.
4. WHEN the book has no source file to convert from THEN the system SHALL refuse before running
   `ebook-convert`.
5. WHEN `ebook-convert` fails (bad/corrupt source) THEN the system SHALL surface its stderr and
   SHALL NOT add a format or report success.
6. The system SHALL back up `metadata.db` before `add_format` (AD-011) and clean up the temporary
   converted file even on failure.

**Independent Test**: On a scratch library, add an epub, `convert_book(id, "pdf")` → the book has
**both** EPUB and PDF; converting to an existing format refuses; a bogus source surfaces the
convert error and adds nothing; a `metadata-*.db` backup exists before the `add_format`.

---

### ORG-01 — Organize & deduplicate

**User Story**: As a library owner, I want to find likely-duplicate books so I can decide what to
merge or remove.

**Why P2**: A higher-order workflow built on the P1 read primitives.

**Acceptance Criteria**:

1. WHEN `find_duplicates` is called THEN the system SHALL return groups (size ≥ 2) of likely-duplicate
   books, grouped by a normalized (title, primary-author) key.
2. The operation SHALL be **read-only**: it never mutates the library and never auto-merges — it is
   an advisory report the host/user acts on.
3. WHEN there are no duplicates THEN the system SHALL return an empty group set (not an error).

**Independent Test**: On a scratch library with two same-title/same-author books, `find_duplicates`
returns exactly one group of 2; with all-distinct books it returns zero groups; the library is
unchanged afterward.

---

### EMAIL-01 — Email a book's file

**User Story**: As a library owner, I want the assistant to email a book's file to an address (the
same thing the Calibre GUI's "Connect/share → Email to…" does) so I can send a book by asking.

**Why P2**: Distribution/delivery, not part of the core curation loop; outward-facing; depends on
SMTP config outside the library. Built on the P1 read primitives (resolve id → attach its format).

**Acceptance Criteria**:

1. WHEN `email_book` is called with a book id and a recipient THEN the system SHALL send the book's
   format file as an attachment via `calibre-smtp`.
2. Because sending is **outward-facing**, `email_book` SHALL use the plan→confirm gate (AD-012): a
   plan call (no token) returns the recipient, chosen format, subject, and file to be sent plus a
   `confirmation_token`, and sends nothing; an apply call must pass the matching token.
3. The attachment format SHALL be the explicit `format` argument if given, else chosen by the
   device-preference order `epub → azw3 → mobi → pdf`.
4. SMTP relay config (relay host, port, username, password, encryption, sender) SHALL come from
   `CALIBRE_MCP_SMTP_*` environment variables, loaded lazily (the server boots without SMTP).
5. The SMTP password SHALL be treated as a secret: never logged, never returned in any tool output
   or plan, and scrubbed from any echoed subprocess stderr (AD-015).
6. WHEN SMTP is not configured THEN `email_book` (apply step) SHALL fail with a clear error naming
   the missing variable, and SHALL NOT attempt to send.
7. WHEN the book has no attachable format THEN the system SHALL refuse before sending.

**Resolved design questions** (were open in the P1 spec; resolved here + AD-015/AD-016):
- Delivery mechanism → shell out to `calibre-smtp` (compose mode); it cannot read the GUI SMTP
  config, so relay credentials come from `CALIBRE_MCP_SMTP_*` env (lazy). — AC-4, AC-5.
- Which format to attach → explicit `format`, else device-preference order. — AC-3.
- Confirmation step → plan→confirm (outward-facing). — AC-2.

**Independent Test**: With a **stubbed** `calibre-smtp` (a temp script recording argv), the plan
step returns a token and sends nothing; the apply step invokes `calibre-smtp` with the right
relay/attachment/subject args; a token mismatch is refused; missing SMTP env raises a clear error;
the password string appears in **no** returned value, log, or exception text.

---

## Edge Cases

- WHEN `ebook-convert` is not on PATH THEN `convert_book` SHALL fail with an explicit
  "ebook-convert not installed / not on PATH" error.
- WHEN `calibre-smtp` is not on PATH THEN `email_book` (apply) SHALL fail explicitly.
- WHEN a converted temp file cannot be produced THEN no format is added and the failure is surfaced.
- WHEN a book's on-disk format file is missing (metadata references a file that isn't there) THEN
  path resolution SHALL fail with a clear error rather than passing a bad path to a CLI.
- WHEN duplicate detection sees different editions of the same title THEN it MAY group them (advisory
  false positives are acceptable) — the report never auto-acts.
- WHEN any value contains quotes/newlines THEN it SHALL be passed to the CLIs safely (argument list,
  never shell-interpolated).

---

## Requirement Traceability

| Requirement ID | Story                     | Phase  | Status   |
| -------------- | ------------------------- | ------ | -------- |
| CONV-01        | P2: Convert formats       | Tasks  | Planned  |
| ORG-01         | P2: Organize & dedup      | Tasks  | Planned  |
| EMAIL-01       | P2: Email a book's file   | Tasks  | Planned  |

**ID format:** `[CATEGORY]-[NUMBER]`
**Status values:** Pending → In Design → In Tasks/Planned → Implementing → Verified
**Coverage:** 3 requirements, all mapped to tasks (see `tasks.md`).
