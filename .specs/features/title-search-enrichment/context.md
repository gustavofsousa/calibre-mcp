# Title/Author Search Enrichment Context

**Gathered:** 2026-10-01
**Spec:** `.specs/features/title-search-enrichment/spec.md`
**Status:** Ready for design

---

## Feature Boundary

Books without a usable ISBN get Open Library enrichment proposals by title/author search, through
the existing `enrich_from_identifier` / `enrich_missing` tools — proposals only, high confidence only.

## Implementation Decisions

### How a match reaches the user
- **Automatic best match** inside `enrich_from_identifier` (no candidate-picking tool). Only a
  `high`-confidence match becomes a proposal; lower ones are reported (with what matched) but not proposed.

### Batch
- `enrich_missing` includes ISBN-less books; only `high` matches are `proposed`.

### Fields a search match may propose
- **Description (→ `comments`) and cover only** — work-level, edition-independent. No publisher/pubdate.

### ISBN
- **Not proposed** now (would need `identifiers` editable in `update_metadata`).

### Agent's Discretion
- Confidence formula and thresholds, normalization, search breadth/retry, candidate selection
  (recorded as assumptions A3–A8 in the spec for PR review).

## Specific References

- Probe of 2026-10-01 (143 ISBN-less books): 52 with any result; 14 high / 32 medium / 6 low under the
  chosen rule (the 14 high all spot-checked correct). Known false friend: "Biografia papa Francisco" (author "Vaticano") → a different
  author's book — must not be `high`.

## Deferred Ideas

- Propose the match's ISBN as an identifier (needs editable identifiers) — BACKLOG.
- Let the user pick among the top-N candidates for medium matches — BACKLOG.
