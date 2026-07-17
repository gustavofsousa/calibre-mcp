# Library Baseline Stats (STATS-01) Specification

## Problem Statement

The host (Claude Desktop/Code) currently only learns the shape of the library by paging
`list_books`, which is slow, context-heavy, and has already hidden real structure (e.g. a
duplicate title spanning ids 61 and 132 was missed by paginated listing and only found by an
ad-hoc direct read of `metadata.db`). Now that calibre-mcp is post-P1/P2 and in Product mode
(traction confirmed, per `.specs/STATE.md`), the deferred STATS-01 backlog item is unblocked:
the server should surface an aggregate baseline profile of the library — totals, format/language
mix, metadata completeness, identifier types, author/tag distribution, and data-quality flags —
so the host knows the library's shape without an expensive full-listing pass.

## Goals

- [ ] Host can learn the library's aggregate shape (totals, formats, languages, completeness,
      identifiers, top authors/tags, data-quality flags) in one read, without paging `list_books`.
- [ ] The profile is auto-knowable on connect (no explicit tool call required by the host) via an
      MCP resource.
- [ ] Computation reuses the existing read layer (`SqliteReader` behind `CalibreLibrary`) — no new
      SQL in the tool/resource layer, no new invariant violations (AD-001, stderr-only logging).

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
| --- | --- |
| Exposing stats as a `library_stats` tool (Option B) | User confirmed Option A (MCP resource) only for this feature; a tool wrapper is a separate, deferred idea if a host without resource support shows up. |
| Caching / persisted snapshot (e.g. writing `.library-profile.json`) | Recommendation locked in AD (compute-on-read, `metadata.db` is small); persistence adds staleness and a write path this feature doesn't need. |
| Historical trend tracking (stats over time) | No requirement surfaced; adds state this read-only feature doesn't need. |
| Configurable top-N / configurable thresholds | Fixed defaults (see AC) keep the feature read-only and parameter-free, matching a resource (no request params). Revisit only if a real host need appears. |
| Any write/mutation path | STATS-01 is read-only by definition (backlog scope guard); would violate the additive-only intent of this feature. |
| Full per-book completeness detail (beyond the aggregate flags) | `get_book`/`list_books` already expose per-book detail; STATS-01 is aggregate-only. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Resource vs. tool exposure | MCP resource only (`calibre://library/stats`), Option A | User explicitly chose Option A when asked; matches the AD recommendation already on record in STATE.md. | y |
| Freshness / caching | Compute on every resource read, no cache, no persisted file | Matches the AD recommendation: `metadata.db` is small, `SqliteReader` is already read-only/lock-independent; avoids a staleness bug class. | n (declined implicitly — no caching gray area raised; logging as assumption per closure gate) |
| Top-N size for authors/tags | 10 each | Matches the validated ad-hoc prototype (`.library-profile.json`), which already proved useful at this size. | n (not raised as a discussion point; default carried from prototype) |
| Duplicate-group detection algorithm | Reuse `SqliteReader.find_duplicate_groups()` (normalized casefold title + primary author, group size ≥ 2) | Already implemented and tested for ORG-01 (`find_duplicates`); STATS-01 only needs the *count* of groups, not a second implementation. | n (technical reuse decision, not user-facing) |
| Behavior on an empty library (0 books) | Return a valid, zeroed/empty profile — never an error | Consistent with `list_books`/`find_duplicates` precedent: empty result sets are not error states in this codebase. | n (edge case, no valid alternative reading) |
| Behavior when `metadata.db` is locked/unreadable | Same lock-independent guarantee as `get_book`/`list_books` (AD-010): pure SQLite read, so it should still succeed under a Calibre-GUI lock; a genuine read failure surfaces as a clear resource error | Inherits `SqliteReader`'s existing contract; no new failure mode to invent. | n (inherited, not a new decision) |
| Resource identity | Single fixed URI `calibre://library/stats`, no URI parameters | Matches the AD-recorded URI; a parameter-free resource fits "known without a tool call" and keeps the feature read-only/stateless. | y (URI itself confirmed in STATE.md; no params — no discussion raised, logging as assumption) |

**Open questions:** none — all resolved above or logged as assumptions with rationale.

---

## User Stories

### P1: Auto-known library shape on connect ⭐ MVP

**User Story**: As the host (Claude Desktop/Code) connecting to calibre-mcp, I want to read an
aggregate library-shape profile without calling a tool, so that the assistant orchestrating the
session already knows the library's size, composition, and data-quality issues before the user
asks anything.

**Why P1**: This is the entire feature — STATS-01 has no smaller demonstrable slice; the value is
specifically "known without a tool call."

**Acceptance Criteria**:

1. WHEN the host issues `resources/read` for `calibre://library/stats` THEN the server SHALL
   return a single JSON object containing: `totals` (book count, min/max id, count of gapped/
   deleted ids, next-id hint), `formats` (count per format), `languages` (count per language code,
   including an `unset` bucket for books with no language recorded), `metadata_completeness` (per
   field in `{comments, publisher, tags, identifiers, languages, real_pubdate, series, rating}`:
   filled count + percentage of total books), `identifier_types` (count per identifier type across
   the library), `authors` (distinct author count + top 10 authors by book count), `tags` (distinct
   tag count + top 10 tags by book count), and `data_quality_flags` (`unknown_author_books` count,
   `placeholder_pubdate_0101` count — pubdates equal to Calibre's `0101-01-01` placeholder,
   `series_unused`/`rating_unused` booleans — true when zero books have that field set, and
   `duplicate_title_groups` — the list of duplicate groups from `find_duplicate_groups()`, each
   with its normalized key and member book ids/titles).
2. WHEN the resource is read on a library with zero books THEN the server SHALL return the same
   object shape with all counts at zero and all list fields empty — never an error.
3. WHEN `metadata.db` is reachable (including while the Calibre GUI holds its lock, per AD-010)
   THEN the read SHALL succeed exactly like `get_book`/`list_books` do today.
4. WHEN `metadata.db` cannot be read at all (e.g. missing/corrupt file) THEN the server SHALL
   surface a clear resource-read error naming the failure — never a silent empty or wrong profile.
5. WHEN the resource is read twice in a row with no library changes in between THEN both reads
   SHALL return identical values (deterministic, pure function of current DB state — no hidden
   cache to go stale, no non-determinism).
6. WHEN computing the profile THEN the server SHALL do so entirely through `SqliteReader` methods
   behind the `CalibreLibrary` facade (reusing `find_duplicate_groups()` for the duplicate flag) —
   no new raw SQL introduced outside the read layer, and no subprocess/`calibredb` call involved
   (pure read, AD-001).

**Independent Test**: Point the server at the real test library (or a scratch library fixture),
call `resources/read` on `calibre://library/stats`, and assert the returned object's `totals.books`
matches `SqliteReader.count_books()` and at least one known data-quality fact (e.g. the real
library's "A fé explicada" duplicate at ids 68/132) appears in `duplicate_title_groups`.

---

## Edge Cases

- WHEN a book has no language recorded THEN it SHALL be counted under an explicit `unset` bucket
  in `languages`, not silently dropped from the total.
- WHEN a book has multiple authors THEN only its first-listed (primary) author participates in
  duplicate-group keying and the top-authors count credits every author on the book (matching
  existing `find_duplicate_groups`/author-listing semantics, not a new rule).
  Assumption: "top authors by book count" counts one credit per author per book they appear on
  (not per-book-primary-only) — matches the ad-hoc prototype's counting and is the most intuitive
  reading of "author X has N books."
- WHEN two or more distinct duplicate-title groups exist THEN all of them SHALL appear in
  `duplicate_title_groups`, not just the first found.
- WHEN a book's `pubdate` is an actual valid date (not the `0101-01-01` placeholder) THEN it counts
  toward `real_pubdate` completeness, not `placeholder_pubdate_0101`.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| STATS-01-01 | P1: Auto-known library shape on connect | Design | Pending |
| STATS-01-02 | P1: Auto-known library shape on connect | Design | Pending |
| STATS-01-03 | P1: Auto-known library shape on connect | Design | Pending |
| STATS-01-04 | P1: Auto-known library shape on connect | Design | Pending |
| STATS-01-05 | P1: Auto-known library shape on connect | Design | Pending |
| STATS-01-06 | P1: Auto-known library shape on connect | Design | Pending |

**ID format:** `STATS-01-NN` (maps 1:1 to the six ACs of the P1 story above).

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 6 total, 0 mapped to tasks (pre-Design), 0 unmapped ⚠️

---

## Success Criteria

- [ ] `resources/read` on `calibre://library/stats` returns a well-formed profile matching AC-1's
      shape against the real test library, with the known "A fé explicada" duplicate present.
- [ ] Zero new raw SQL in `server.py`/`library.py` — the resource handler calls one new
      `CalibreLibrary.library_stats()` method, which composes existing/new `SqliteReader` queries.
- [ ] Empty-library and locked-DB paths both behave per AC-2/AC-3/AC-4 (verified via scratch
      library fixtures, never the real library, per the existing test-safety rule).
