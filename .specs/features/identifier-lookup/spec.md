# Identifier-Based Metadata Lookup (ENRICH-01) Specification

**Phase:** 3 — Covers & Metadata Enrichment (ROADMAP.md)
**Feature id:** ENRICH-01
**Requirement prefix:** `LOOKUP`
**Context:** decisions captured inline (Assumptions & Open Questions) — no separate context.md. The
four defining decisions were confirmed with the user at Specify time (see the Assumptions table).

ENRICH-01 is the **first feature in which calibre-mcp makes an outbound network call.** It is the
*lookup* half of the enrichment cluster: given a book that already carries an ISBN, query a free
external source (Open Library) and **return proposed values for the metadata the book is missing** —
description, publisher, pubdate — plus a downloaded cover image ready to be set. It writes **nothing**
to the library. Applying those values is ENRICH-02 (route the proposal through `update_metadata`'s
existing plan→confirm gate); walking a whole shelf of proposals is ENRICH-03. Keeping ENRICH-01
read-only isolates the new network surface (its timeout/offline/rate-limit hardening) from any
mutation, exactly as the roadmap sequenced it.

## Problem Statement

The real library has large, measurable metadata gaps (from the validated `.library-profile.json`):
**71% of books missing `comments`** (description), **62.9% missing `publisher`**, and many with a
placeholder pubdate. Today the only way to fill them is retyping in the Calibre GUI, or Calibre's own
"Download metadata" dialog. calibre-mcp has no path to pull authoritative metadata from an external
source. ENRICH-01 adds that path in the safest possible shape — a **read-only lookup keyed on an
identifier the book already has** — so the host can propose gap-filling values (and a cover) without
the server ever writing on its own. The proposal is advisory, exactly like `find_duplicates`
(AD-016): the source suggests, the user (via ENRICH-02) decides.

**Why "identifier-based" and not title/author search** — an ISBN is an *exact* key: one ISBN → one
edition, no fuzzy matching, no wrong-book risk. Title/author search returns ranked guesses that would
need disambiguation UI and could silently propose the wrong book's description. Starting from an
identifier the book already carries keeps the first network feature deterministic and trustworthy —
the "safe writes" brand extended to "safe reads-from-the-internet."

**The two facts that shape this design (verified against the live Open Library API 2026-07-31):**
1. Open Library's clean structured endpoint (`/api/books?...&jscmd=data`) returns
   publisher / publish_date / cover URLs / subjects but **not** the description — description lives on
   the *work* record, one link away. Since `comments` is the single biggest gap (71%), ENRICH-01
   **follows that second link** to fetch it (user-confirmed).
2. Open Library resolves **ISBN / OCLC / LCCN / OLID** — **not** Google Books ids or ASIN. A book
   whose only identifier is `google`/`amazon` has no Open-Library key; ENRICH-01 reports that as a
   normal "nothing to look up" result, not an error.

## Goals

- [ ] Given a `book_id` whose record carries an **ISBN**, fetch metadata from Open Library and return
      **proposed values only for the fields the book currently lacks** (`comments`, `publisher`,
      `pubdate`) — advisory, writing nothing to the library.
- [ ] Fetch the **description** (the 71%-gap field) by following the edition→work link when the
      structured record omits it.
- [ ] When the book has **no cover**, download Open Library's cover image to a temp file and return
      its **local path** (ready to be set by COVER-02) plus the source URL — no library write.
- [ ] Treat the network as a bounded, fallible dependency: a short timeout, at most one retry, and
      **every** offline/timeout/HTTP/parse failure surfaced as a clean, mapped error — never a crash,
      never partial state. Establish this as an explicit new AD (the project's first outbound-network
      policy).

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| **Applying** the proposed values to the book | That is **ENRICH-02** — feed `proposed` into `update_metadata`'s existing plan→confirm gate (AD-012). ENRICH-01 is read-only by decision (Assumptions). |
| **Batch** "enrich every book missing comments" | That is **ENRICH-03** (N independent plans to walk). ENRICH-01 is single-book. |
| **Setting** the downloaded cover on the book | That is **COVER-02** (`set_cover`), which takes the **local path** ENRICH-01 produces. ENRICH-01 downloads but never writes the cover into the library. |
| Lookup by **Google Books id / ASIN** | Open Library does not resolve these identifier types (verified). Documented limitation; a different source (e.g. Google Books API) would be its own feature/AD. |
| Lookup by **title/author** (fuzzy search) | Wrong-book risk; needs disambiguation. ENRICH-01 is deterministic identifier-keyed lookup only. |
| Enriching **tags** from Open Library `subjects` | Subjects are noisy and often over-broad; auto-proposing them as tags is a separate, opt-in concern (not among the named gap fields). Not built here. |
| Enriching `series` / `number_of_pages` / `languages` | Not among the roadmap's named gap fields (description/publisher/pubdate/cover); avoid scope creep. |
| **Overwriting** fields the book already has | ENRICH-01 proposes for **missing** fields only (gap-filling); a present value is reported as skipped, never proposed. |
| A second/fallback source when Open Library has no record | One source for the MVP (Open Library — free, no key). A fallback chain is a later enrichment feature. |
| A persistent HTTP cache / rate-limit token bucket | Single-user, low call volume; a bounded timeout + retry + preferring the non-rate-limited cover URL is sufficient. Revisit only if ENRICH-03 batches hit the limit. |
| Adding an HTTP **client library dependency** (`requests`/`httpx`) | Stdlib `urllib.request` covers a couple of simple GETs; keeps the dep surface minimal ("personal, no infra"). |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here — nothing left silently unclear. The first four rows
were **confirmed with the user at Specify time** (the macro decisions AGENTS.md/roadmap require for a
first outbound-network call).

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Scope boundary | **Lookup-only (read-only)** — return `proposed` values; the write is ENRICH-02 | Matches the roadmap split; isolates the new network surface from any mutation. Advisory, like `find_duplicates` (AD-016). | y |
| Network failure policy (the new AD) | **Graceful, bounded, no crash**: ~10s timeout, ≤1 retry, offline/timeout/HTTP/parse → a clean mapped `EnrichmentSourceError`, never partial | First outbound call; AGENTS.md treats external calls as a MACRO decision; the roadmap flags an explicit AD (timeout/offline/rate-limit) before Design. | y |
| Description (the 71% gap) | **Include it via a 2nd call** — follow the edition→work link when the structured record omits `description` | `comments` is the biggest gap and the phase's main motivation; the clean endpoint alone omits it (verified). | y |
| Cover handling | **Download to a temp file** and return the local path + URL (ready for COVER-02); do not set it | Closes the net-fetch→local-path gap COVER-02 left open (COVER-02 takes a *local* path); still no library write. | y |
| External source | **Open Library** (`openlibrary.org`), free, no API key | Roadmap default; fits "personal, no infra". Single source for the MVP. | y |
| Usable identifier | **ISBN** (`identifiers["isbn"]`), normalized (strip non-alphanumerics, upper-case) | The dominant identifier in the library; Open Library's cleanest key. OCLC/LCCN/OLID are same-endpoint cheap extensions, deferred to keep the MVP tight. | y |
| No usable identifier (no ISBN) | Return `{found: false, reason: "no usable identifier (ISBN)"}` — **no network call**, no error | A book without an ISBN is a normal "nothing to look up", not a failure. | y |
| Source has no record for the ISBN | Return `{found: false, identifier_used, reason: "no record at source"}` — not an error | A 404/empty from Open Library is a normal negative result, distinct from a transport failure. | y |
| "Missing" definition | `comments`/`publisher`: `None` or empty string. `pubdate`: `None` **or** matches Calibre's placeholder `0101-01-01%` | Reuse the **exact** placeholder rule `library_stats` already uses (`pubdate LIKE '0101-01-01%'`, `sqlite_reader.py:531`) — one business rule, no drift (AGENTS.md). | y |
| `pubdate` value returned | The **raw** Open Library `publish_date` string (e.g. `"2009"`, `"April 2009"`) | ENRICH-01 is a pure fetch; date normalization/coercion belongs to the apply step (ENRICH-02), not the lookup. | y |
| Cover: which URL | Prefer the **cover-id** URL (`/b/id/<id>-L.jpg`) from the Books API `cover` object | Verified: cover access by **id/OLID is not rate-limited**, whereas by ISBN it is (100 req / 5 min / IP). Using the id URL sidesteps the limit. | y |
| Cover only when book lacks one | Download/propose a cover **only if** `cover_file(book_id) is None` (reuse COVER-01) | Gap-filling: don't propose replacing a cover the book already has. Reuses COVER-01's `cover_file`. | y |
| Cover download failure | **Non-fatal** — return metadata `proposed` with `cover: {url, local_path: null, error}`; the whole lookup does **not** fail | The cover is best-effort; a failed image download must not lose the (more valuable) text metadata already fetched. | y |
| Test-safety rule (network) | Network tests **never hit the real Open Library** — the client takes an injectable HTTP-fetch seam; tests feed canned responses | The network analog of the "writes never touch the real library" rule — deterministic, offline, fast tests. Non-negotiable. | y |
| Dependency | **stdlib `urllib.request`** — no new package | Two simple GETs; keeps the install a single `mcp` dep (AD-023 frictionless `uvx`). | y |
| Temp-file lifecycle | Downloaded cover goes to a uniquely-named file under the system temp dir; the OS/user reaps it | The file must **survive** the ENRICH-01 call to be consumed by a later COVER-02 call, so it can't be a context-managed dir cleaned on return. | y |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Look up an ISBN and propose the missing metadata ⭐ MVP

**User Story**: As the library owner, I want to point calibre-mcp at a book that has an ISBN and get
back authoritative values for the fields it's missing — description, publisher, pubdate — plus a
cover image, so that I can fill metadata gaps without retyping from the GUI, and without the server
changing anything until I approve it.

**Why P1**: This is the whole feature and the Phase-3 motivation (close the 71%/62.9% gaps
STATS-01 surfaced) — and doing it read-only makes the project's first internet call trustworthy: the
source proposes, ENRICH-02 (later) applies through the existing gate.

**Acceptance Criteria**:

1. WHEN `enrich_from_identifier(book_id)` is called AND the book has a normalizable `isbn` AND Open
   Library has a record THEN the system SHALL return `{book_id, found: true, source: "openlibrary",
   identifier_used: {type: "isbn", value: <normalized>}, proposed: {...}, skipped_present: [...],
   cover: {...} | null}` — **writing nothing** to the library. *(LOOKUP-01)*
2. WHEN the book has **no** Open-Library-usable identifier (no `isbn`) THEN the system SHALL return
   `{book_id, found: false, reason: "no usable identifier (ISBN)"}` and SHALL make **no network
   call** — this is a normal result, not an error. *(LOOKUP-02)*
3. WHEN `book_id` does not exist THEN the system SHALL raise `BookNotFoundError`, before any network
   call. *(LOOKUP-03)*
4. WHEN the structured record omits a description THEN the system SHALL follow the edition→work link
   and include the work's `description` as proposed `comments` (only if the book lacks comments).
   *(LOOKUP-04)*
5. WHEN a target field (`comments`/`publisher`/`pubdate`) already has a value on the book (`pubdate`
   present-and-not-`0101-01-01%`) THEN the system SHALL **not** include it in `proposed` and SHALL
   name it in `skipped_present`; only genuinely-missing fields appear in `proposed`. *(LOOKUP-05)*
6. WHEN the book has **no cover** (`cover_file(book_id) is None`) AND Open Library has a cover THEN
   the system SHALL download the cover image (via the cover-**id** URL) to a temp file and return
   `cover: {url, local_path: <temp path>}` — ready for COVER-02, no library write. WHEN the book
   already has a cover THEN `cover` SHALL be `null`. *(LOOKUP-06)*
7. WHEN the book has an ISBN but Open Library has **no record** for it THEN the system SHALL return
   `{book_id, found: false, identifier_used, reason: "no record at source"}` — not an error.
   *(LOOKUP-07)*

**Independent Test**: Seed a scratch library with a book that has `identifiers.isbn`, no `comments`,
no `publisher`, placeholder `pubdate`, and **no** cover. Inject a fake HTTP fetcher returning a canned
Books-API record (publisher + publish_date + cover-id URL, **no** description) and a canned work
record (with `description`). Call `enrich_from_identifier(id)`: assert `found: true`,
`identifier_used.value` = the normalized ISBN, `proposed` = `{comments, publisher, pubdate}` with the
description sourced from the **work** record, `skipped_present` empty, and `cover.local_path` points
to an on-disk file whose bytes equal the canned image. Then: (a) a book with only a `google`
identifier → `found: false, reason` names the missing ISBN and the fake fetcher was **never** called;
(b) an unknown id → `BookNotFoundError`; (c) a book that already has a publisher → `publisher` is in
`skipped_present`, not `proposed`; (d) a book that already has a cover → `cover: null`; (e) the fake
fetcher returns "no record" → `found: false, reason: "no record at source"`.

---

### P1: Fail the network gracefully — bounded, mapped, never partial

**User Story**: As the library owner, I want a lookup to fail cleanly when I'm offline, the source is
slow, or it errors — with an actionable message and nothing half-done — so that the first
internet-touching feature can't hang the server or leave garbage behind.

**Why P1**: This is the point of the confirmed network AD. A first outbound call that could hang
indefinitely or crash the stdio server is unacceptable; the failure contract is part of the MVP, not
a polish item.

**Acceptance Criteria**:

1. WHEN the metadata fetch cannot reach the source, times out, or the source returns an HTTP error
   (≥400 other than a clean not-found) or an unparseable body THEN the system SHALL raise
   `EnrichmentSourceError` (a `CalibreMcpError`, mapped by `_map_errors` to a clean `ToolError`) —
   never an unhandled crash, never partial state. *(LOOKUP-08)*
2. WHEN the metadata fetch succeeds but the **cover download** fails (network/HTTP/rate-limit) THEN
   the system SHALL still return the metadata `proposed`, with `cover: {url, local_path: null, error:
   <reason>}` — a cover failure SHALL NOT fail the whole lookup. *(LOOKUP-09)*
3. WHEN any request is made THEN the client SHALL apply a **bounded timeout** (default 10s) and **at
   most one retry**, and SHALL identify itself with a descriptive `User-Agent`; a lookup SHALL never
   block the server indefinitely. *(LOOKUP-10)*

**Independent Test**: Inject a fetcher that raises a timeout/connection error → assert
`EnrichmentSourceError` and that nothing was written or left behind. Inject a fetcher that succeeds
for metadata but raises on the cover URL → assert `proposed` is returned and `cover.local_path is
None` with an `error`. Inject a fetcher that records call count and fails once then succeeds → assert
exactly one retry occurred. Assert the timeout value is passed through to the transport (spy on the
seam).

---

## Edge Cases

- WHEN the `isbn` value has hyphens/spaces or lower-case `x` check digit THEN it SHALL be normalized
  (strip non-alphanumerics, upper-case) before the lookup and echoed normalized in `identifier_used`.
- WHEN the book has an ISBN but **all** target fields are already populated AND it already has a cover
  THEN `found: true` with `proposed: {}`, `skipped_present` listing all three, `cover: null` — a
  valid "nothing to fill" result.
- WHEN the work `description` is the object form `{"value": "..."}` (Open Library returns either a
  string or that object) THEN the system SHALL extract the string. *(LOOKUP-04)*
- WHEN Open Library returns a record with no cover THEN `cover: null` (nothing to download).
- WHEN the cover download hits the rate limit (HTTP 403) THEN it is a non-fatal cover failure
  (LOOKUP-09), and — because the cover-**id** URL is used — this should be rare.
- WHEN the source is unreachable THEN `EnrichmentSourceError` (LOOKUP-08), never a Python traceback to
  the host.
- WHEN a non-int `book_id` is passed THEN `InvalidInputError` before any network call (reuses
  `get_book`'s existing `_require_int`).

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| LOOKUP-01 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-02 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-03 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-04 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-05 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-06 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-07 | P1: Look up an ISBN and propose missing metadata | Execute | Implementing |
| LOOKUP-08 | P1: Fail the network gracefully | Execute | Implementing |
| LOOKUP-09 | P1: Fail the network gracefully | Execute | Implementing |
| LOOKUP-10 | P1: Fail the network gracefully | Execute | Implementing |

**ID format:** `LOOKUP-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 10 total, all mapped in `design.md` §Requirement Coverage; task mapping produced at the
Tasks step. Design at `.specs/features/identifier-lookup/design.md`.
**Prerequisite:** COVER-01's `SqliteReader.cover_file` (reused for cover-presence) must exist first.

---

## Success Criteria

How we know the feature is successful:

- [ ] For a book with an ISBN and gaps, one call returns authoritative `comments`/`publisher`/
      `pubdate` proposals and a downloaded cover — with the server writing nothing.
- [ ] Description (the 71% gap) is captured via the work-record follow-up, not dropped.
- [ ] A book without an ISBN, or one the source doesn't know, returns a clear `found: false` result —
      no error, and (for no-ISBN) no wasted network call.
- [ ] Offline / timeout / HTTP / parse failures surface as one clean `EnrichmentSourceError`, never a
      crash or partial result; a bounded timeout + ≤1 retry are enforced.
- [ ] A failed cover download never loses the text metadata already fetched.
- [ ] The whole feature is tested with **zero** real network calls (injected HTTP seam) — the network
      test-safety rule holds, mirroring the never-touch-the-real-library write rule.
- [ ] The first outbound-network policy is recorded as an explicit AD.
