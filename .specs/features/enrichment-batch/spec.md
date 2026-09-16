# Batch Enrichment Review Mode (ENRICH-03) Specification

**Phase:** 3 — Covers & Metadata Enrichment (ROADMAP.md)
**Feature id:** ENRICH-03
**Requirement prefix:** `ENRICH3`
**Context:** the three defining gray areas (candidate filter, batch cap / rate-limit guard, partial
failure handling) were confirmed with the user at Specify time (see the Assumptions table).

ENRICH-03 is the **batch review** half of the enrichment cluster. ENRICH-01 looks up **one** book by
its ISBN and returns an advisory proposal (writing nothing); ENRICH-03 answers "do that across the
shelf": **find the books that both carry a usable ISBN and are missing enrichable metadata, look each
one up, and return N independent proposals** for the host to walk through and apply one at a time
through the existing ENRICH-02 gates. It **writes nothing** and **never bulk-applies** — the batch is
advisory exactly like `find_duplicates` (AD-016): the source suggests, the user decides, per book.

## Problem Statement

STATS-01 measured the real gaps (`.library-profile.json`): **71% of books missing `comments`**,
**62.9% missing `publisher`**, many with a placeholder pubdate. ENRICH-01/02 close those gaps **one
book at a time** — the owner must already know a book's id and drive each lookup by hand. There is no
way to ask "which of my books *can* be enriched, and what would each proposal be?" without manually
listing candidates and calling `enrich_from_identifier` in a loop. ENRICH-03 adds that single
entry point — a **bounded, read-only sweep** that selects the enrichable candidates and returns a
proposal per book — turning a shelf-wide curation session into one call to review, then per-book
approvals through the gates that already exist. It is the natural close of the Phase-3 motivation
(drive down the `metadata_completeness` gaps) without ever handing the server a silent bulk write.

**Why a sweep, not a bulk apply** — the whole safe-mutation brand (AD-012 plan→confirm, AD-016
advisory reports) rests on a human approving each write. A "fix everything" button that silently
writes N books from an external source is exactly the anti-pattern this project refuses. ENRICH-03
therefore returns **proposals to walk**, never applies; applying stays the host's per-book decision
via `update_metadata` + `set_cover` (the ENRICH-02 chain, unchanged).

## Goals

- [ ] Add **one read-only entry point** that selects the books which (a) carry a normalizable ISBN
      **and** (b) are missing at least one enrichable field (`comments`/`publisher`/`pubdate`), looks
      each up via the **existing** `enrich_from_identifier` path, and returns a **per-book proposal**
      plus an aggregate summary — writing **nothing** to the library.
- [ ] Bound the outbound-call volume: a **default cap** on how many candidates are processed per call
      (revisiting the rate-limit concern ENRICH-01 explicitly deferred to here), with an optional
      caller override and an `offset` so a host can page the rest of the shelf across calls.
- [ ] Isolate per-book failure: a single book's transport/parse failure is recorded against **that
      book** and the sweep **continues**, so one offline blip never discards the other proposals.
- [ ] Report the sweep as a **bucketed, best-effort result** (AD-020) the host can act on: which
      books produced proposals, which had no new data, which had no record, which errored — plus
      whether more candidates remain beyond the processed window.

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| **Applying** any proposed value or cover | ENRICH-03 is read-only by decision (the batch twin of ENRICH-01). Applying stays the host's per-book job via `update_metadata` + `set_cover` (the ENRICH-02 chain). No new mutation path, no token, no backup (AD-016). |
| A **"apply all" / bulk-write** convenience | The core refusal of the feature — a silent shelf-wide write from an external source violates AD-012/AD-016. The host walks proposals and approves each. |
| Selecting candidates by **title/author** (fuzzy) | ENRICH-01's wrong-book risk applies per book; ENRICH-03 only *selects* books that already carry an ISBN and delegates the lookup to the deterministic ENRICH-01 path. |
| Enriching books **without** a usable ISBN | Such a book has no Open-Library key (ENRICH-01 LOOKUP-02). ENRICH-03 excludes it from the candidate set up front — it would only ever return `found:false`, so processing it wastes a slot. Reported via `candidate_count` semantics, not as a per-book error. |
| A persistent HTTP cache / token-bucket rate limiter | Still single-user, low volume. The **default cap + offset paging** is the agreed bound (the ENRICH-01 deferral resolved here); a true limiter remains a later concern only if real usage hits the wall. |
| New enrichable fields (`series`/`languages`/`tags`) | Same named gap fields as ENRICH-01 (`comments`/`publisher`/`pubdate`); no scope creep. |
| Parallel / concurrent lookups | Sequential keeps the outbound surface simple and rate-limit-friendly; a bounded batch of ~25 sequential GETs is well within budget. Concurrency is a later optimization, not MVP. |

---

## Assumptions & Open Questions

Every ambiguity is resolved or recorded here. The first three rows were **confirmed with the user at
Specify time** (the batch/rate-limit dimensions AGENTS.md treats as macro decisions).

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Candidate filter | **Missing *any* enrichable field (`comments` OR `publisher` OR `pubdate`-placeholder) AND a normalizable ISBN** | Broader gap-fill per pass than comments-only; still keyed on an ISBN so every candidate is actually lookuppable (no wasted slots). Reuses ENRICH-01's exact "missing" rule per field. | y |
| Batch cap / rate-limit guard | **Default cap of 25 candidates per call + optional `limit` override + `offset` for paging**, candidates ordered by `id` | Bounds the outbound volume ENRICH-01 deferred to here; mirrors the AD-020 cap precedent (BULK-02/03) and the `list_books` limit/offset convention; host pages the rest deterministically. | y |
| Partial failure | **Per-book isolation** — a book's `EnrichmentSourceError` becomes that item's `status:"error"` and the sweep continues; other proposals survive | One offline/timeout blip must not discard a shelf of good proposals; matches AD-020 best-effort "failed" bucketing. | y |
| Write policy | **Read-only, advisory** — no `calibredb` call, no backup, no confirmation token (AD-016) | ENRICH-03 is the batch twin of read-only ENRICH-01; the write is the host's per-book ENRICH-02 decision. | y (implied by scope) |
| Candidate selection source | A **reader SQL query** returning candidate ids (missing-field ∧ has-isbn), reusing the placeholder-pubdate rule already in `sqlite_reader` | One business rule for "missing", no drift (AGENTS.md); a targeted query avoids hydrating the whole library. | y (impl. decision) |
| Per-book lookup | **Reuse `enrich_from_identifier(book_id)` verbatim** — one call per candidate | Zero new network/proposal logic; the batch is a bounded loop over the proven ENRICH-01 path. | y (impl. decision) |
| `limit` bounds | `limit` must be a positive int; **rejected as `InvalidInputError` when ≤ 0 or absurdly large** (cap ceiling, e.g. > 100) before any network call | Guards against a caller asking for a thousand-call sweep; consistent with BULK-02/03 cap-rejection at the boundary. | y (impl. decision) |
| `offset` bounds | Non-negative int; an offset past the candidate count yields an **empty, non-error** result (`processed: 0`) | Paging off the end is a normal "nothing more to do", like `list_books`. | y (impl. decision) |
| Ordering | Candidates ordered by **`id` ascending**, deterministic | Stable paging across calls; the host sees the same window for the same offset. | y (impl. decision) |
| Tool naming | Specify-time note: capability = "propose enrichment for the enrichable-but-incomplete books"; concrete tool name decided at Design (candidate: `enrich_missing`) | Name is a Design-surface detail; the spec fixes behavior, not the identifier. | Design |

**Open questions:** none — all resolved or logged above.

---

## User Stories

### P1: Sweep the enrichable-but-incomplete books and return proposals to walk ⭐ MVP

**User Story**: As the library owner, I want one call that finds the books which have an ISBN and are
still missing description/publisher/pubdate, looks each one up, and hands me a proposal per book — so
I can review a whole curation batch at once and then approve each write myself, without the server
changing anything on its own.

**Why P1**: This is the whole feature and the close of the Phase-3 motivation — turn ENRICH-01's
single-book lookup into a shelf-wide review while keeping every write a per-book human decision.

**Acceptance Criteria**:

1. WHEN the batch entry point is called THEN the system SHALL select the books that carry a
   normalizable `isbn` **and** are missing at least one enrichable field (`comments`/`publisher`/
   `pubdate`-placeholder), ordered by `id`, look up **each** via the existing
   `enrich_from_identifier` path, and return a per-book `results` list plus an aggregate `summary` —
   **writing nothing** to the library (no `calibredb` call, no backup, no token). *(ENRICH3-01)*
2. WHEN a candidate lookup returns proposed values (and/or a cover) THEN that book's result SHALL
   carry `status:"proposed"` and the **verbatim** `enrich_from_identifier` payload (`proposed`,
   `skipped_present`, `cover`, `identifier_used`) so the host can feed it straight into the ENRICH-02
   chain; the batch SHALL add no new proposal shape. *(ENRICH3-02)*
3. WHEN a candidate has an ISBN and a record but Open Library offers **no value** for any missing
   field and no cover THEN that book's result SHALL carry `status:"no_new_data"` (found, but nothing
   to fill); WHEN Open Library has **no record** for the ISBN THEN `status:"no_record"`. *(ENRICH3-03)*
4. WHEN a candidate lookup raises `EnrichmentSourceError` (offline/timeout/HTTP/parse) THEN that
   book's result SHALL carry `status:"error"` with the mapped reason, and the sweep SHALL **continue**
   to the remaining candidates — one failure SHALL NOT abort the batch or lose the other results.
   *(ENRICH3-04)*
5. WHEN more candidates match the filter than are processed in this call THEN the result SHALL report
   the total `candidate_count`, the `processed` count, and the `limit`/`offset` used, so the host can
   tell that more remain and page the rest. *(ENRICH3-05)*
6. WHEN no book matches the filter (none missing-and-isbn, or `offset` past the end) THEN the system
   SHALL return an empty `results` with `candidate_count`/`processed` and a zeroed `summary` — a
   normal "nothing to enrich" result, **not** an error. *(ENRICH3-06)*

**Independent Test**: Seed a scratch library with: book A (isbn, no comments/publisher, placeholder
pubdate, no cover), book B (isbn, all three fields present but — to be a candidate — force one gap,
e.g. missing publisher), book C (isbn, all fields present → **not** a candidate), book D (only a
`google` identifier, missing comments → **not** a candidate, no ISBN), book E (isbn, missing comments
→ candidate whose injected lookup **raises** a transport error). Inject the HTTP seam so A returns a
record with publisher+description+cover, B returns a record with a publisher, E raises. Call the batch
with default limit: assert `results` covers A/B/E only (C and D excluded from candidates), A →
`status:"proposed"` with the verbatim ENRICH-01 payload (description as `comments`), B →
`status:"proposed"` (publisher only), E → `status:"error"` and the sweep still returned A and B,
`summary` = `{proposed:2, error:1, no_record:0, no_new_data:0}`, `candidate_count:3`, `processed:3`,
and the library was **not** written. Then: (a) `limit:1` → only A processed, `candidate_count:3`,
`processed:1`; (b) `offset:3` (past the 3 candidates) → empty `results`, `processed:0`, no error;
(c) a candidate whose record has no usable value and no cover → `status:"no_new_data"`; (d) a
candidate the fetcher reports no-record for → `status:"no_record"`.

---

### P2: Bound the sweep — never an unbounded outbound blast

**User Story**: As the library owner, I want the sweep to process a sane number of books per call and
to refuse an absurd request — so a batch can never fire hundreds of external calls or hang the server.

**Why P2**: The rate-limit concern ENRICH-01 explicitly deferred to ENRICH-03. A bounded default plus
a boundary-checked override is the agreed guard (no token-bucket needed for a single user).

**Acceptance Criteria**:

1. WHEN no `limit` is given THEN the system SHALL process at most the **default cap** (25) candidates;
   WHEN a positive `limit` ≤ the cap ceiling is given THEN it SHALL process at most that many.
   *(ENRICH3-07)*
2. WHEN `limit` ≤ 0, non-int, or above the cap ceiling (e.g. > 100), or `offset` is negative/non-int
   THEN the system SHALL raise `InvalidInputError` **before any network call** — a bad bound is
   rejected, never silently clamped into a huge sweep. *(ENRICH3-08)*
3. WHEN the batch processes candidates THEN it SHALL do so **sequentially** and each lookup SHALL
   carry ENRICH-01's own bounded timeout/retry (LOOKUP-10) — the batch adds no unbounded wait.
   *(ENRICH3-09)*

**Independent Test**: With 30 candidate books seeded and the seam returning cheap records, call with
no `limit` → assert exactly 25 processed and `candidate_count:30`. Call `limit:0` and `limit:1000` and
`offset:-1` → assert `InvalidInputError` each, and the injected fetcher was **never** called
(rejected before network). Spy the seam call order/count → assert sequential, one lookup per processed
candidate.

---

## Edge Cases

- WHEN a candidate's `isbn` is present but **not normalizable** (only non-alphanumerics) THEN it is
  **not** a candidate (the selection query requires a real isbn value; ENRICH-01's normalization is
  the same rule) — it never reaches a wasted lookup.
- WHEN a book is missing a field the record also lacks (e.g. missing publisher, record has none) but
  the record **does** have another proposable value or a cover THEN `status:"proposed"` (there is
  something to fill), with only the available fields in `proposed`.
- WHEN a candidate already has a cover but is missing a text field THEN it is still a candidate;
  `cover` follows ENRICH-01's rule (`null` when the book already has one).
- WHEN the same offset/limit window is requested twice with no library change THEN the same candidate
  set is processed (deterministic `id` ordering) — safe to retry a page.
- WHEN `limit` equals the cap ceiling exactly THEN it is accepted (boundary inclusive); one above is
  rejected (mirrors BULK-02/03 boundary cap tests).
- WHEN a non-int `book`-selection parameter is passed THEN `InvalidInputError` before any network call
  (reuses the existing `_require_int` discipline).

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| ENRICH3-01 | P1: Sweep and return proposals | Execute | Verified |
| ENRICH3-02 | P1: Sweep and return proposals | Execute | Verified |
| ENRICH3-03 | P1: Sweep and return proposals | Execute | Verified |
| ENRICH3-04 | P1: Sweep and return proposals | Execute | Verified |
| ENRICH3-05 | P1: Sweep and return proposals | Execute | Verified |
| ENRICH3-06 | P1: Sweep and return proposals | Execute | Verified |
| ENRICH3-07 | P2: Bound the sweep | Execute | Verified |
| ENRICH3-08 | P2: Bound the sweep | Execute | Verified |
| ENRICH3-09 | P2: Bound the sweep | Execute | Verified |

**ID format:** `ENRICH3-[NUMBER]`.

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 9 total; design coverage produced at the Design step, task mapping at the Tasks step.
**Prerequisites:** ENRICH-01's `enrich_from_identifier` facade + `EnrichmentSourceError` taxonomy
(reused verbatim per candidate) and `sqlite_reader`'s placeholder-pubdate rule (reused for candidate
selection) — both already Shipped & Verified.

---

## Success Criteria

How we know the feature is successful:

- [ ] One call selects the enrichable-but-incomplete books (has ISBN ∧ missing a field) and returns a
      proposal per book — with the server writing nothing and never bulk-applying.
- [ ] Each proposed item carries ENRICH-01's verbatim payload, feeding straight into the ENRICH-02
      chain — the batch invents no new proposal shape.
- [ ] The sweep is bounded: a default cap, a boundary-checked `limit`/`offset` override, and rejection
      of absurd bounds before any network call — the ENRICH-01 rate-limit deferral is resolved.
- [ ] A single book's transport failure is isolated to that book; the rest of the proposals survive.
- [ ] The host can tell more candidates remain (`candidate_count` vs `processed`) and page them.
- [ ] The whole feature is tested with **zero** real network calls (the injected ENRICH-01 HTTP seam)
      and **zero** real-library writes (the `scratch_library` fixture) — both safety rules hold.
