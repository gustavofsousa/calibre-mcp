# Cover Coverage in Library Stats Specification (STATS-02)

**Phase:** 3 — Covers & Metadata Enrichment (ROADMAP.md, v0.4 gate) · **Scope:** Medium

## Problem Statement

The v0.4 phase gate says "every book has a viewable cover", but `calibre://library/stats` reports
nothing about covers — the gate can't be measured, and the host can't find which books lack one
without paging every `get_book`/`read_cover`. Measured directly on 2026-10-01: 192 of 194 real
books have a cover, so the remaining work is two books the host has no way to locate.

## Goals

- [ ] One stats read answers "what fraction of books have a cover, and which ones don't".

## Out of Scope

| Feature | Reason |
| --- | --- |
| Checking `cover.jpg` exists on disk for every book | A metadata↔disk mismatch is an integrity check (MAINT-01); `read_cover` already surfaces it per book. |
| Cover quality/resolution | Backlog (covers → Mature). |
| Fetching covers for the missing books | Already covered by ENRICH-01/04 + `set_cover`. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Source of truth for "has a cover" | `books.has_cover` (Calibre's own flag) | Same flag `read_cover` uses; pure SQL, lock-independent like the rest of STATS-01. | y (agent default, reviewed in PR) |
| How many missing ids to list | First 50 by ascending id; the count is in `metadata_completeness.cover` | Bounded payload on large libraries, still enough to act on a personal one. | y (agent default) |

**Open questions:** none.

---

## User Stories

### P1: Measure cover coverage ⭐ MVP

**User Story**: As the host curating a library, I want cover coverage in the stats snapshot so that
I can tell whether the "every book has a cover" gate holds and act on the books that don't.

**Acceptance Criteria** (Quick Capture):

1. **COVCOV-01** — WHEN `library_stats` is read THEN `metadata_completeness.cover` SHALL be
   `{"filled": <books with has_cover = 1>, "pct": round(100 * filled / books, 1)}`.
   *Verification:* integration test on a scratch library with covered + uncovered books. *Priority:* Required.
2. **COVCOV-02** — WHEN some books have no cover THEN `data_quality.missing_cover_ids` SHALL list
   their ids in ascending order, at most 50 of them. *Verification:* integration test (exact list;
   cap asserted with 51+ uncovered books). *Priority:* Required.
3. **COVCOV-03** — WHEN the library is empty THEN `cover` SHALL be `{"filled": 0, "pct": 0.0}` and
   `missing_cover_ids` SHALL be `[]` (no error). *Verification:* integration test. *Priority:* Required.
4. **COVCOV-04** — WHEN the `calibre://library/stats` resource is read THEN the payload SHALL carry
   both new keys. *Verification:* e2e test through FastMCP. *Priority:* Required.

**Independent Test**: seed 2 books, give one a cover, read the resource: `cover.filled == 1`,
`missing_cover_ids == [<uncovered id>]`.

Remaining implicit-requirement dimensions N/A for this scope (pure read, no state change, no
external call).

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| COVCOV-01 | P1 | Execute | Implementing |
| COVCOV-02 | P1 | Execute | Implementing |
| COVCOV-03 | P1 | Execute | Implementing |
| COVCOV-04 | P1 | Execute | Implementing |

**Coverage:** 4 total.

## Success Criteria

- [ ] On the real library, the stats resource reports 192/194 covered and lists the 2 missing ids.
