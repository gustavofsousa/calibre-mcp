# ENRICH-03 — Tasks

Atomic tasks, one commit each. Gate = named tests pass + full suite no-regression + mypy + ruff clean.
Tests derive from spec ACs (ENRICH3-01..09), assert spec-defined outcomes, never mirror impl.

**Status:** T1 ✅ (`0cec3d6`) · T2 ✅ (`1e56ddd`) · T3 ✅ (`6b77862`) · T4 ✅ (this commit).
Verifier PASS (`validation.md`), 9/9 ACs, 4/4 sensor mutants killed, 387 passed. ENRICH3-07
end-to-end cap test added post-Verifier (`6ef64c7`) to close its one caveat.

## T1 — Reader candidate selection (`enrichable_candidates`)
- Add `enrichable_candidates(limit, offset) -> tuple[int, list[int]]` to `sqlite_reader.py`:
  `(total_count, page_ids)`, ids in `id` order, filter = has-isbn ∧ (missing comments OR publisher OR
  placeholder/NULL pubdate) — the design SQL, reusing the exact `_stats_completeness` rules.
- **Tests** (unit): seed books for each branch (missing-comments+isbn, missing-publisher+isbn,
  placeholder-pubdate+isbn, complete→excluded, no-isbn+missing→excluded, blank-comments-row→missing);
  assert selected ids + `total_count`; assert `limit`/`offset` paging.
- **Covers:** ENRICH3-01 (selection), part of 05/06/07. **Gate:** unit tests pass.

## T2 — Library batch facade (`enrich_missing`)
- Add constants `ENRICH_BATCH_DEFAULT = 25`, `ENRICH_BATCH_MAX = 100`.
- Add `_classify_enrichment(payload) -> str` (proposed | no_new_data | no_record) per design table.
- Add `enrich_missing(limit=None, offset=0) -> dict`: bound-validate (InvalidInputError, incl. bool
  exclusion, before any reader/network) → `enrichable_candidates` → sequential
  `enrich_from_identifier` per id with `except EnrichmentSourceError` isolation → bucketed
  `results`+`summary`+`candidate_count`/`processed`/`limit`/`offset`. Writes nothing.
- **Tests** (`tests/integration/test_enrichment_batch.py`, injected HTTP seam + scratch_library):
  P1 independent test (A/B proposed, C/D excluded, E error, summary+counts, no write), `limit:1`,
  `offset` past end, `no_new_data`, `no_record`; P2 (default-25 of 30, `limit` 0/1000 & negative
  `offset` rejected before any seam call, sequential one-call-per-candidate via a spy).
- **Covers:** ENRICH3-01..09. **Gate:** new tests + full suite pass; mypy + ruff.

## T3 — Server tool surface
- Add `@mcp.tool() @_map_errors enrich_missing(limit: int | None = None, offset: int = 0) -> dict`
  returning `_jsonify(_get_library().enrich_missing(...))`; docstring: read-only/advisory, never
  bulk-applies, per-book apply via ENRICH-02 chain.
- **Tests:** extend the server tool-surface test (tool registered / delegates / maps errors), matching
  how `enrich_from_identifier` is covered.
- **Covers:** ENRICH3-01 surface. **Gate:** server tests + full suite pass.

## T4 — Decision + traceability (docs)
- Record **AD-027** in `.specs/STATE.md` (batch outbound policy) + update the Handoff/Next snapshot.
- Mark ENRICH3-01..09 Verified in `spec.md` traceability after the Verifier PASS; note the feature in
  STATE's feature list; tick ROADMAP ENRICH-03.
- **Gate:** docs consistent; no code change.

## Order & dependencies
T1 → T2 (facade needs the reader query) → T3 (tool needs the facade) → T4 (docs after Verifier).
Verifier runs automatically after T3's commit (author ≠ verifier); T4 records its PASS.
