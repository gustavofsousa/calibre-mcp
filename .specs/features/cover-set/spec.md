# Set a Book's Cover From a Local File (COVER-02) Specification

**Phase:** 3 — Covers & Metadata Enrichment (ROADMAP.md)
**Feature id:** COVER-02
**Requirement prefix:** `SCOVER`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md.
COVER-02 is the **write half** of the Phase-3 covers pair — the mutating sibling of COVER-01
(`read-cover`). It is a single-book metadata mutation gated through the existing plan→confirm
handshake (AD-012) with one `metadata.db` backup (AD-011), exactly like `update_metadata`, but for
the cover. **Prerequisite:** it reuses `SqliteReader.cover_file` introduced by COVER-01 (to show the
current cover state in the plan and to demonstrate the change after apply) — COVER-01 ships first.

## Problem Statement

Setting or replacing a book's cover today requires the Calibre GUI (right-click → Edit metadata →
change cover). There is no MCP path. Calibre accepts a cover via `calibredb set_metadata <id>
--field cover:<path>`, which reads a local image file and writes it into the book folder as
`cover.jpg` (flipping `books.has_cover` to 1). COVER-02 exposes that as a dedicated, reviewed tool:
given a book id and a **local image file path**, plan the change, and on confirmation set the cover
behind one backup — then re-read to prove the cover actually changed.

**Why a dedicated `set_cover` tool (not a field on `update_metadata`)** — confirmed at Specify time.
A cover's value is a **filesystem image path**, not a metadata string: it needs different validation
(the file must exist and be an image), a cover-specific plan (current cover present? → replace vs
add), and it is symmetric with `read_cover`. Folding `cover` into `update_metadata`'s text-field
whitelist would mix a path-typed input into a string editor and complicate that tool's diff/validation.

**The footgun that shapes this design** — empirically verified 2026-07-31: `calibredb set_metadata
--field cover:<path>` **does not error when the path is missing or unreadable** — it silently
no-ops, leaving `has_cover` unchanged. So COVER-02 **must** validate the file exists (and looks like
an image) **before** the write, and **re-read `has_cover` after** the write, or a bad path would be
reported as a false "cover set." (A valid image *does* work: a hand-built 100×150 PNG became a
392-byte `cover.jpg` and flipped `has_cover` 0→1.)

## Goals

- [ ] Set a book's cover from a **local image file** in one plan→confirm call: plan shows whether the
      book currently has a cover (replace vs add) and the proposed image; apply writes it via
      `calibredb set_metadata --field cover:<path>` behind exactly one `metadata.db` backup (AD-011).
- [ ] Validate **before** any backup/write (fail-fast at the boundary, because `calibredb` silently
      no-ops on a bad path): the book must exist, and `image_path` must be an existing local file with
      an image extension — else a clear invalid-input / not-found error and **zero** side effects.
- [ ] **Demonstrate, not assert**: after applying, re-read the book's cover state and return
      `has_cover: true` + the on-disk `cover.jpg` path — so a silent no-op (e.g. an image `calibredb`
      rejected) surfaces as a truthful result, never a false success.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| **Reading** a cover | That is COVER-01 (`read-cover`), the read sibling (whose `cover_file` this feature reuses). |
| **Fetching** a cover from the internet (Open Library, etc.) | ENRICH cluster (Phase 3, later) — the project's first outbound-network call, its own AD. COVER-02 takes a **local** path only (consistent with AD-004: add-book also takes a local path, no byte upload). |
| **Removing** a cover (set-to-nothing) | COVER-02 only *sets* a cover from a file. Deleting a cover is a distinct capability, not requested. |
| Accepting **image bytes** (base64 upload) instead of a path | AD-004 precedent: the server is co-located with the library; it takes a filesystem path, not an upload. |
| **Resizing / re-encoding** the image ourselves | `calibredb` re-encodes to `cover.jpg` (JPEG) itself; we do no image processing (AD-006 keeps logic out of the server). |
| **Bulk** set-cover (N books) | Single-book mutation, mirroring `update_metadata`. A batch cover flow would follow the AD-020 pattern separately, not requested here. |
| Adding `cover` to `update_metadata`'s field set | Rejected at Specify time — a cover is a path-typed input needing its own validation/plan; a dedicated tool keeps `update_metadata` about metadata strings (see Problem Statement). |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear.

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Tool surface | **Dedicated `set_cover` tool** (not a field on `update_metadata`) | Confirmed at Specify time: cover value is a filesystem image path with path-specific validation and a replace-vs-add plan; symmetric with `read_cover`. | y |
| Cover source | A **local filesystem path** to an image file (no upload) | AD-004 precedent (add-book takes a local path); server is co-located with the library. | y |
| Apply mechanism | `calibredb set_metadata <id> --field cover:<path>` (reuse `CalibredbRunner.set_metadata` **unchanged**) | Empirically verified 2026-07-31: this invocation reads the file, writes `{book}/cover.jpg`, flips `has_cover` 0→1. `set_metadata` already emits `--field name:value` for a scalar value → `--field cover:<path>`. **No runner change.** | y |
| Missing / unreadable `image_path` | **Reject** as `InvalidInputError`, **before** any backup/write | **Critical, verified:** `calibredb` does **not** error on a missing cover path — it silently no-ops. Without a pre-write `is_file()` guard, a bad path is a false "cover set." | y |
| Non-image `image_path` (unsupported extension) | **Reject** as `InvalidInputError`, before write | Narrow untrusted input at the boundary (AGENTS.md); don't hand `calibredb` a file it will reject or mis-handle. Accepted set: `.jpg/.jpeg/.png/.webp/.gif/.bmp`. | y |
| Unknown `book_id` | **`BookNotFoundError`**, before write | Same as every mutation (`update_metadata`); never a silent miss. | y |
| Book **already has** a cover | **Allowed — replace.** Plan surfaces `current_has_cover: true`; apply overwrites | Replacing a cover is the common intent; the one backup makes it recoverable. Not a reason to reject. | y |
| Gate | **plan→confirm** (AD-012) + exactly **one** `metadata.db` backup before the write (AD-011) | Cover is a mutation of existing library state (writes into the book folder + flips `has_cover`) → reviewed before it writes, single rollback point. | y |
| Token scope | `plan_token(_OP_SET_COVER, book_id, {"image_path": <resolved str>})` over the **real** `book_id` | Single-book op (like `update_metadata`/`remove_book`), not a batch — the real id is the token subject, not the `_BULK_TOKEN_ID` sentinel. | y |
| Path in the token / plan | The **resolved** `str(Path(image_path))`, used identically in plan and apply | Deterministic token recompute (plan == apply when nothing changed); mirrors the sibling features' payload discipline. | y |
| Success demonstration | Re-read via `cover_file` after apply; return `has_cover` + the library `cover.jpg` path | "Demonstrated, not asserted": a `calibredb` silent no-op (rejected image) yields `has_cover` still false in the result, not a fake success. | y |
| Where "current cover?" comes from | **`SqliteReader.cover_file`** (COVER-01) — `has_cover = cover_file(id) is not None` | Reuse the read primitive COVER-01 introduces; no second cover-presence query. Establishes the COVER-01 → COVER-02 dependency. | y |
| New reader / runner method | **None** — reuses `cover_file` (COVER-01) and `set_metadata` (unchanged) | Cover set is pure orchestration over existing primitives + the one new reader method from COVER-01. | y |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Set/replace a book's cover via one reviewed call ⭐ MVP

**User Story**: As the library owner, I want to point a book at a local image file and set it as the
cover in a single reviewed call, so that fixing a missing or wrong cover stops requiring the Calibre
GUI — and I can trust the change was actually applied.

**Why P1**: This completes the Phase-3 gate ("every book has a viewable cover" — COVER-01 lets you
see them, COVER-02 lets you fix the ones without one), and the plan→confirm gate + post-apply
re-read is what makes an LLM-driven cover write trustworthy given `calibredb`'s silent-no-op behavior.

**Acceptance Criteria**:

1. WHEN `set_cover(book_id, image_path)` is called **without** a token THEN the system SHALL validate
   the book exists and `image_path` is an existing local image file, and return a plan
   `{book_id, current_has_cover, new_cover: <resolved path>, confirmation_token}` — writing nothing.
   *(SCOVER-01)*
2. WHEN `image_path` does not exist or is not a file THEN the system SHALL reject with
   `InvalidInputError`, **before** any backup or write — never a silent no-op. *(SCOVER-02)*
3. WHEN `image_path` has an unsupported (non-image) extension THEN the system SHALL reject with
   `InvalidInputError`, before any backup or write. *(SCOVER-03)*
4. WHEN `book_id` does not exist THEN the system SHALL raise `BookNotFoundError`, before any backup
   or write. *(SCOVER-04)*
5. WHEN the apply call passes the token matching `(book_id, resolved image_path)` THEN the system
   SHALL take exactly one `metadata.db` backup **before** the write (AD-011), set the cover via
   `calibredb set_metadata <id> --field cover:<path>`, **re-read** the book's cover state, and return
   `{status: applied, book_id, has_cover, cover_path, backup}` — demonstrating the change. *(SCOVER-05)*
6. WHEN the apply call passes a token that does not match `(book_id, resolved image_path)` THEN the
   system SHALL refuse with a clear error and write nothing (reuse `confirmation.verify`). *(SCOVER-06)*
7. WHEN the book already has a cover THEN the plan SHALL show `current_has_cover: true` and the apply
   SHALL still proceed (replace), overwriting the existing `cover.jpg` — a replace is allowed, not
   rejected. *(SCOVER-07)*

**Independent Test**: Bootstrap a scratch library with a book that has **no** cover. Generate a valid
local image file (stdlib zlib-PNG helper). Plan `set_cover(id, image_path)`: assert the plan has
`current_has_cover: false`, `new_cover` = the resolved path, a token, and that `has_cover` is still 0
and **no backup exists**. Apply with the token: assert the result is `status: applied` with
`has_cover: true` and a `cover_path` ending in `cover.jpg`, that `cover.jpg` is now on disk, and that
exactly one `metadata.db` backup was created. Then: (a) plan with a **missing** `image_path` and
assert `InvalidInputError` before any backup (no backup file appears); (b) apply with a **wrong
token** and assert it is refused with no write; (c) re-run `set_cover` with a second valid image and
assert the plan now shows `current_has_cover: true` and the apply replaces the cover successfully.

---

## Edge Cases

- WHEN `image_path` is missing/unreadable THEN reject before backup (SCOVER-02) — never rely on
  `calibredb` to error (it does not; it silently no-ops — verified).
- WHEN `image_path` has a non-image extension THEN reject before backup (SCOVER-03).
- WHEN the token does not match THEN refuse and write nothing (SCOVER-06) — the user re-plans.
- WHEN the book already has a cover THEN the apply replaces it (SCOVER-07) — not an error.
- WHEN `calibredb` accepts the path but the re-read shows `has_cover` still false (e.g. an image it
  could not decode) THEN the result SHALL report `has_cover: false` (truthful), never a fake success
  (SCOVER-05, "demonstrated not asserted").
- WHEN the apply succeeds THEN exactly one `metadata.db` backup SHALL precede the write (SCOVER-05).

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| SCOVER-01 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |
| SCOVER-02 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |
| SCOVER-03 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |
| SCOVER-04 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |
| SCOVER-05 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |
| SCOVER-06 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |
| SCOVER-07 | P1: Set/replace a cover via one reviewed call | Implementing | Implementing |

**ID format:** `SCOVER-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 7 total, all mapped to tasks T1–T2 in `tasks.md`; verification pending (independent
Verifier runs after the final Execute task). Design at `.specs/features/cover-set/design.md`.
**Prerequisite:** COVER-01's `SqliteReader.cover_file` must exist first (reused for cover-presence).

---

## Success Criteria

How we know the feature is successful:

- [ ] A book's missing/wrong cover is fixed from a local image in one plan + one apply, no GUI.
- [ ] A missing or non-image path is rejected before any backup — never a silent "cover set" that
      changed nothing.
- [ ] An unknown id is a clear not-found error; a wrong token is refused with no write.
- [ ] Replacing an existing cover works (plan shows `current_has_cover: true`); the apply overwrites.
- [ ] Every applied cover set is preceded by exactly one `metadata.db` backup, and the result
      **re-reads** the cover state — a `calibredb` no-op surfaces as `has_cover: false`, not a fake
      success.
- [ ] No new reader/runner method — pure orchestration over `cover_file` (COVER-01) + `set_metadata`.
