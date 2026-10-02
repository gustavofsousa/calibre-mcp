# Title/Author Search Enrichment Specification (ENRICH-04)

**Phase:** 3 — Covers & Metadata Enrichment (ROADMAP.md, v0.4 gate) · **Scope:** Large
**Context:** `.specs/features/title-search-enrichment/context.md` (user decisions, 2026-10-01)

## Problem Statement

Enrichment is keyed on the ISBN (ENRICH-01..03), and only 51 of 194 real books carry one: the live
run found 7 enrichment candidates in the whole library, so the v0.4 completeness gate can't move.
A read-only probe of Open Library's search API over the 143 ISBN-less books (2026-10-01) found a
result for 52 of them; under the confidence rule below, 14 are `high` (all 14 spot-checked as the
right book), 32 `medium`, 6 `low`. Fuzzy matching is the risk: a
wrong-book match that reaches `update_metadata` becomes a silent bad write behind a "confirmed"
token — so the match must be scored, and only a confident one may become a proposal.

## Goals

- [ ] An ISBN-less book with a confident Open Library match gets the same kind of advisory proposal
      an ISBN book gets (description + cover), through the same tools.
- [ ] A non-confident match never becomes a proposal, and the user can see *what* was matched.

## Out of Scope

| Feature | Reason |
| --- | --- |
| Proposing `publisher` / `pubdate` from a search match | They vary by edition (a PT translation vs. the original); a work-level match can't pick the edition (user decision). |
| Proposing the match's ISBN as an identifier | Needs `identifiers` editable in `update_metadata` + edition choice — backlog (user decision). |
| A candidate-picking tool (user chooses among N) | User chose automatic best match, high confidence only. |
| Falling back to search when a book HAS an ISBN but Open Library has no record for it | An ISBN is an exact key; a miss is information, not a cue to guess (assumption A3). |
| Throttling / caching Open Library calls | Same bounded-sweep policy as ENRICH-03 (AD-027); backlog. |

---

## Assumptions & Open Questions

| # | Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- | --- |
| A1 | Surface | `enrich_from_identifier` falls back to search when the book has no usable ISBN; same tool, same output shape + a `match` block | User decision ("melhor match automático") | **y (user)** |
| A2 | Batch | `enrich_missing` also sweeps ISBN-less books; only `high` matches become `proposed` | User decision | **y (user)** |
| A3 | ISBN present but no record at source | stays `found:false, "no record at source"` — no search fallback | Exact key respected; keeps ENRICH-01 behavior unchanged for ISBN books | y (agent default, PR review) |
| A4 | Confidence rule | normalized-title similarity ≥ 0.90 **and** author similarity ≥ 0.85 → `high`; title ≥ 0.60 → `medium`; else `low` (see TSEARCH-02) | Calibrated on the 2026-10-01 probe: conservative on purpose (a real wrong match, "Biografia papa Francisco" → another author's book, scores medium) | y (agent default, PR review) |
| A5 | Book author blank or `Unknown` | author can't be compared → never `high` (capped at `medium`) | Title-only agreement is exactly the wrong-book risk | y (agent default) |
| A6 | Which candidate is "best" | highest confidence rank, ties broken by `title_similarity + author_similarity`, then Open Library's own order | Deterministic and explainable | y (agent default) |
| A7 | Search breadth | title + primary author, at most 5 results; if that returns nothing and an author was sent, retry once with title only | Probe: author spelling differs across catalogs ("Papa Francisco" vs "Pope Francis") | y (agent default) |
| A8 | ISBN-less batch candidates | non-blank title AND (missing `comments` OR no cover) — only what search can propose | Avoids network calls that can only end in `no_new_data` | y (agent default) |
| A9 | "Usable ISBN" when the stored value is junk (e.g. `---`) | Single book: the facade normalizes it to empty → search fallback. Batch selection treats any non-blank `isbn` as the ISBN path: such a book is swept only if it lacks comments/publisher/pubdate, and then folds into `no_record` (the residual AD-027 already documents); it is never re-routed to search, and with complete text fields it is not swept at all | Rare data error; keeping the SQL rule identical to `_stats_completeness`/AD-027 beats a second normalization in SQL. *[added after Verifier round 1]* | y (agent default) |

**Superseded requirements (explicit, per user decision A1/A2):** `LOOKUP-02` ("no ISBN → no network
call") is **revised** to "no ISBN **and** no usable title → no network call"; `ENRICH3-01`
("candidates carry an ISBN") is **revised** by TSEARCH-09. Their existing tests are revised to the
new outcomes, not deleted.

**Open questions:** none.

---

## User Stories

### P1: Confident title/author match becomes a proposal ⭐ MVP

**User Story**: As the host curating a library where most books have no ISBN, I want
`enrich_from_identifier` to find the book on Open Library by title and author and propose its
description and cover — but only when the match is confident — so the completeness gaps can close
without risking a wrong-book write.

#### TSEARCH-01: Search fallback when there is no usable ISBN
- **Scenario:** a book with no usable `isbn` identifier and a non-blank title.
- **Action:** `enrich_from_identifier(book_id)`.
- **Expected:** Open Library search is queried with the title and the primary author (author
  omitted when blank/`Unknown`), at most 5 results; if it returns none *and* an author was sent, one
  retry with the title only.
- **Must not:** query search for a book that has a usable ISBN (the ISBN path runs unchanged).
- **Verification:** integration test with a fake enricher recording the search calls.
- **Priority:** Required.

#### TSEARCH-02: Each candidate gets a deterministic confidence
- **Scenario:** search returned candidates.
- **Action:** score each against the book.
- **Expected:** both titles normalized (Unicode-decomposed with accents dropped, case-folded, cut at
  the first `:` or `(` so subtitles don't count, non-alphanumerics → spaces, whitespace collapsed);
  `title_similarity` = `difflib.SequenceMatcher` ratio of the normalized titles; `author_similarity`
  = best ratio between the book's primary author and any candidate author, comparing normalized names
  with their tokens sorted (so "Bach, James" ≡ "James Bach"), or `null` when the book author is
  blank/`Unknown`. Confidence: `high` iff title ≥ 0.90 and author ≥ 0.85; else `medium` iff title ≥
  0.60; else `low`. Similarities are reported rounded to 2 decimals.
- **Must not:** produce `high` when `author_similarity` is `null`.
- **Verification:** unit tests on the pure scorer (accents, subtitle, case, token order, Unknown author, thresholds at the boundaries).
- **Priority:** Required.

#### TSEARCH-03: A `high` best match proposes description + cover only
- **Scenario:** the best candidate is `high`.
- **Action:** `enrich_from_identifier(book_id)`.
- **Expected:** `{book_id, found: true, source: "openlibrary", identifier_used: null, match: {method:
  "search", confidence: "high", title, authors, work_key, title_similarity, author_similarity},
  proposed, skipped_present, cover}` where `proposed` holds `comments` (the work's description) only
  if the book lacks comments; `cover` follows the ENRICH-01 rule (downloaded only when the book has no
  cover and the match has one).
- **Must not:** propose `publisher` or `pubdate`; write anything to the library.
- **Verification:** integration test (exact payload + `metadata.db` digest unchanged).
- **Priority:** Required.

#### TSEARCH-04: A non-`high` best match is shown, never proposed
- **Scenario:** the best candidate is `medium` or `low`.
- **Expected:** `{book_id, found: false, reason: "no confident match", match: {…best candidate,
  its confidence…}}` — no `proposed`, no cover download.
- **Must not:** download a cover or fetch a description for it.
- **Verification:** integration test (payload + zero cover/description calls).
- **Priority:** Required.

#### TSEARCH-05: No result at all
- **Expected:** `{book_id, found: false, reason: "no record at source", match: null}`.
- **Verification:** integration test. **Priority:** Required.

#### TSEARCH-06: Nothing usable to search with (LOOKUP-02, revised)
- **Scenario:** no usable ISBN and no usable title — blank or Calibre's own placeholder
  `Unknown` (Calibre stores `Unknown` when a book has no title) *[revised before Execute]*.
- **Expected:** `{book_id, found: false, reason: "no usable identifier (ISBN) or title"}`, **no
  network call**.
- **Verification:** integration test (enricher never called). **Priority:** Required.

#### TSEARCH-07: Source failures
- **Expected:** a transport/parse failure of the *search* request raises `EnrichmentSourceError`
  (tool error, as the ISBN path); a failure fetching the work *description* is non-fatal — the result
  is built without it.
- **Verification:** unit (client) + integration tests. **Priority:** Required.

#### TSEARCH-08: Read-only
- **Expected:** no `calibredb` call, no backup, no confirmation token in any outcome above; the
  `proposed` keys are accepted verbatim by `update_metadata`.
- **Verification:** `metadata.db` digest unchanged; e2e test applies a `proposed` through
  `update_metadata` plan→confirm. **Priority:** Required.

**Independent Test**: an ISBN-less book "The Hobbit" by "J. R. R. Tolkien" with a fake source
returning that work → `found: true`, `match.confidence: "high"`, `proposed.comments` = the work
description; the same book with author "Unknown" → `found: false, "no confident match"`.

### P1: The batch sweep covers ISBN-less books

#### TSEARCH-09: `enrich_missing` candidates and buckets (ENRICH3-01, revised)
- **Scenario:** a library mixing ISBN and ISBN-less incomplete books.
- **Action:** `enrich_missing(limit, offset)`.
- **Expected:** candidates = (ISBN books missing comments/publisher/pubdate — unchanged) ∪ (books
  without a usable ISBN, with a non-blank title, missing comments OR without a cover), ordered by id,
  same caps/paging (AD-027). "Non-blank title" excludes Calibre's `Unknown` placeholder (TSEARCH-06). Each result is exactly what `enrich_from_identifier` returns for that
  book plus a `status`; a `found:false, "no confident match"` result has `status:
  "no_confident_match"`; `summary` gains that bucket (`{proposed, no_new_data, no_record,
  no_confident_match, error}`).
- **Must not:** turn a non-`high` match into `proposed`; write anything.
- **Verification:** integration tests (selection, bucket, paging unaffected) + e2e through FastMCP.
- **Priority:** Required.

---

## Edge Cases

- WHEN the book title has accents/case/subtitle differences from the catalog title THEN the
  normalized similarity SHALL still reach `high` (TSEARCH-02).
- WHEN the catalog lists several authors THEN the best author ratio across them SHALL be used.
- WHEN the candidate has no author at all THEN `author_similarity` SHALL be `0.0` (never `high`).
- WHEN the work has no description and the book already has a cover THEN a `high` match SHALL return
  `found: true` with an empty `proposed` (→ `no_new_data` in the batch).

## Risk Review (implicit-requirement dimensions)

| Dimension | Resolution |
| --- | --- |
| Input validation & bounds | Book id validated before any network (existing LOOKUP-03); search limited to 5 results; batch caps unchanged (AD-027). |
| Failure / partial failure | TSEARCH-07; batch isolates per-book failures (existing ENRICH3-04). |
| Idempotency / retry | Read-only; transport retry = existing `_fetch` (1 retry). |
| Auth / rate limits | No auth; no new throttling (A-out-of-scope; AD-027 bound). |
| Concurrency / ordering | N/A — sequential, read-only. |
| Data lifecycle | Downloaded covers are temp files owned by the caller (existing LOOKUP-09). |
| Observability | N/A beyond existing stderr logging. |
| External-dependency failure | TSEARCH-07. |
| State transitions | N/A — no state written. **Rollback AC:** N/A (applying goes through `update_metadata`, which backs up first). |

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| TSEARCH-01 | P1 single-book | Execute | Verified |
| TSEARCH-02 | P1 single-book | Execute | Verified |
| TSEARCH-03 | P1 single-book | Execute | Verified |
| TSEARCH-04 | P1 single-book | Execute | Verified |
| TSEARCH-05 | P1 single-book | Execute | Verified |
| TSEARCH-06 | P1 single-book (revises LOOKUP-02) | Execute | Verified |
| TSEARCH-07 | P1 single-book | Execute | Verified |
| TSEARCH-08 | P1 single-book | Execute | Verified |
| TSEARCH-09 | P1 batch (revises ENRICH3-01) | Execute | Verified |

**Coverage:** 9 total, 9 Verified (independent Verifier PASS round 2, 20/20 mutants killed — `validation.md`).

## Success Criteria

- [x] A dry run of `enrich_missing` over the real library (read-only, 2026-10-01) reports more
      `proposed` results than the ISBN-only baseline of 2: **4** (3 ISBN + 1 search), with 13
      `no_new_data` (10 of them confident search matches whose Open Library work has no
      description) — met, but far from moving the v0.4 KPI (see `ROADMAP.md`).
- [x] No non-`high` match appears as `proposed` anywhere (38 `no_confident_match` in the dry run).
