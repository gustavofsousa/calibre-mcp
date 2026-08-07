# Enrichment Apply (ENRICH-02) Specification

## Problem Statement

`enrich_from_identifier` (ENRICH-01, Shipped & Verified) proposes gap-filling values
(`comments`/`publisher`/`pubdate` + a downloaded cover) but writes nothing — it's advisory only.
Nothing today proves, end to end, that a proposal can actually be *applied* through the project's
existing safety machinery. ENRICH-02 closes that loop: no new mutation path, just evidence and
tests that the proposal flows cleanly through `update_metadata`'s plan→confirm gate (AD-012) and,
for the cover, through `set_cover`'s (AD-025).

## Goals

- [ ] Prove `enrich_from_identifier`'s `proposed` dict is accepted as-is by `update_metadata` — same
      keys, same values reflected in the plan diff, applied unchanged.
- [ ] Prove the cover proposal (`proposed.cover.local_path`) is accepted as-is by `set_cover` as a
      second, separate call.
- [ ] Document the two-step host flow (lookup → apply fields → apply cover) so this is a known,
      supported pattern, not an accidental side effect of two independently-shipped tools.

## Out of Scope

| Feature | Reason |
| --- | --- |
| A new orchestrating tool (e.g. `enrich_and_apply`) | User-decided (2026-08-07): the existing chain (`enrich_from_identifier` → `update_metadata` → `set_cover`) already satisfies "route through the plan→confirm gate"; no new server API needed. |
| Changing `enrich_from_identifier`'s return contract (e.g. embedding a token) | Would reopen the Shipped & Verified ENRICH-01 spec for no functional gain — `update_metadata`'s own plan step already computes the token. |
| Batch/multi-book enrichment apply | That's ENRICH-03 (Phase 3 candidate), a separate feature. |
| Auto-applying without host/user review | Contradicts AD-012 (every mutation is plan→confirm); enrichment is not exempt. |

---

## Assumptions & Open Questions

| Assumption / decision | Chosen default | Rationale | Confirmed? |
| --- | --- | --- | --- |
| Scope: chaining vs new tool | No new tool; ENRICH-02 = tested/documented chaining of existing tools | User-decided | y |
| Cover handling | Included as a documented second step (`update_metadata` for fields, `set_cover` for cover) | User-decided | y |
| Empty `proposed` (nothing missing, or `found: false`) | Host SHALL NOT call `update_metadata` with an empty `fields` dict; treat empty `proposed` as "nothing to apply" | Empirically verified: `update_metadata({})`'s plan step succeeds (empty diff) but its apply step raises `CalibredbError` (`calibredb` rejects a zero-field `set_metadata` call) — not the originally-assumed harmless no-op. The rule is now "don't call it" *because it fails*, not because it's merely wasteful. | y |
| `pubdate` value fidelity after apply | Re-read `pubdate` is `calibredb`'s normalized ISO form, not the proposed string verbatim | Empirically verified: `calibredb set_metadata --field pubdate:"April 2009"` writes `"2009-04-15 00:00:00+00:00"` — pre-existing `calibredb` date-parsing behavior (unrelated to ENRICH-02), so the AC targets calibredb's normalized output, not string equality with `proposed["pubdate"]` | y |
| Cover `local_path: null` (download failed, LOOKUP-09) | Host SHALL NOT call `set_cover` when `local_path` is `null` | `set_cover` requires an existing file (SCOVER-02); a null path has no valid interpretation | y |
| Field name collision between enrich and edit whitelist | No new mapping needed | Verified: `_ENRICH_FIELDS` keys (`comments`, `publisher`, `pubdate`) are already a strict subset of `ALLOWED_EDIT_FIELDS` (library.py:58-67) — the two tools already speak the same field vocabulary | y |

**Open questions:** none — all resolved above.

---

## User Stories

### P1: Apply enriched text fields through the existing gate ⭐ MVP

**User Story**: As the host (Claude), I want to pass `enrich_from_identifier`'s `proposed` dict
straight into `update_metadata` so I can review a diff and get user approval before writing
enrichment data to the library.

**Why P1**: This is the actual "close the loop" requirement from the roadmap — ENRICH-01 without
this is read-only trivia.

**Acceptance Criteria**:

1. WHEN `enrich_from_identifier` returns `found: true` with a non-empty `proposed` dict THEN
   `update_metadata(book_id, fields=proposed)` (plan step, no token) SHALL succeed and its
   `diff[field].proposed` SHALL equal `proposed[field]` for every field in `proposed`.
2. WHEN that plan's `confirmation_token` is passed back to `update_metadata(book_id, fields=proposed, token=...)`
   THEN the apply step SHALL succeed and the re-read `book` SHALL reflect every field in `proposed`
   — `comments`/`publisher` byte-for-byte, `pubdate` as `calibredb`'s own normalization of the
   proposed value (verified empirically: `calibredb set_metadata` parses a partial date string like
   `"April 2009"` into a full ISO datetime, e.g. `"2009-04-15 00:00:00+00:00"` — pre-existing
   `calibredb` behavior, not something ENRICH-02 introduces or must preserve verbatim).
3. WHEN `proposed` is empty (either `found: false`, or `found: true` with every target field already
   present — `LOOKUP-05`) THEN the host SHALL NOT call `update_metadata` — verified empirically that
   this is NOT a harmless no-op: `calibredb set_metadata` with zero fields exits non-zero
   (`"You must specify either a field or an OPF file"`), so `update_metadata`'s apply step raises
   `CalibredbError` (the plan step still succeeds with an empty diff). This corrects the original
   assumption that an empty apply was merely wasteful — it is a guaranteed failure, one more reason
   the empty-`proposed` guard belongs on the host side before calling apply.
4. WHEN a field in `proposed` collides with a book's current value (re-running enrichment after a
   partial apply, or the source returning the same value already on the book) THEN `update_metadata`'s
   existing diff behavior applies unchanged (no ENRICH-02-specific handling) — proven by reusing
   `update_metadata`'s own EDIT-01..07 contract, not re-implementing it.

**Independent Test**: Seed a scratch-library book missing `comments`/`publisher`/`pubdate`, stub the
enrichment source, call `enrich_from_identifier` then feed its `proposed` straight into
`update_metadata` plan → confirm, and assert the final `get_book` matches the proposed values.

---

### P2: Apply the enriched cover through its existing gate

**User Story**: As the host, I want to pass `enrich_from_identifier`'s downloaded cover path into
`set_cover` as a second call, so a book that lacked a cover ends up with one, still under human
review.

**Why P2**: Cover isn't part of `update_metadata`'s field whitelist (AD-025 — it's a dedicated,
path-typed tool), so it's a separate call, not a blocker for the P1 text-field loop.

**Acceptance Criteria**:

1. WHEN `enrich_from_identifier` returns `cover.local_path` non-null THEN
   `set_cover(book_id, image_path=cover.local_path)` (plan step) SHALL succeed and report
   `current_has_cover: false` (ENRICH-01 only ever proposes a cover when the book has none —
   `_propose_cover`).
2. WHEN that plan's `confirmation_token` is passed back to `set_cover` THEN the apply step SHALL
   succeed and the re-read `has_cover` SHALL be `true` with `cover_path` pointing at a copy of the
   downloaded image.
3. WHEN `cover` is `null` (no cover at source) or `cover.local_path` is `null` (download failed,
   `LOOKUP-09`) THEN the host SHALL NOT call `set_cover` — documented usage rule, no new server
   validation (existing `SCOVER-02` already rejects a non-existent path if this rule is skipped).

**Independent Test**: Seed a scratch-library book with no cover, stub the enrichment source to
return a cover URL, call `enrich_from_identifier`, feed `cover.local_path` into `set_cover` plan →
confirm, and assert `read_cover` reports `has_cover: true` afterward.

---

## Edge Cases

- WHEN the book was mutated between the `enrich_from_identifier` call and the `update_metadata`
  plan call (e.g. another edit landed in between) THEN `update_metadata`'s diff SHALL reflect the
  book's *current* state at plan time (unchanged `EDIT` behavior — no staleness check is added by
  this feature).
- WHEN `proposed` contains a field whose value is an empty string (should not happen per
  `_gap_proposal`'s `value is not None` guard, but documented for completeness) THEN
  `update_metadata`'s existing field validation applies unchanged.
- WHEN the confirmation token from a stale/mismatched `proposed` dict is replayed THEN
  `update_metadata`/`set_cover` SHALL raise their existing token-mismatch error (`EDIT-03`/`SCOVER-06`)
  — unchanged.

---

## Requirement Traceability

| Requirement ID | Story | Phase | Status |
| --- | --- | --- | --- |
| ENRICH2-01 | P1: Apply enriched text fields | Execute | Pending |
| ENRICH2-02 | P1: Apply enriched text fields | Execute | Pending |
| ENRICH2-03 | P1: Apply enriched text fields (empty-proposed rule) | Execute | Pending |
| ENRICH2-04 | P1: Apply enriched text fields (collision reuse) | Execute | Pending |
| ENRICH2-05 | P2: Apply enriched cover | Execute | Pending |
| ENRICH2-06 | P2: Apply enriched cover | Execute | Pending |
| ENRICH2-07 | P2: Apply enriched cover (null-path rule) | Execute | Pending |

**ID format:** `ENRICH2-NN`

**Status values:** Pending → In Design → In Tasks → Implementing → Verified

**Coverage:** 7 total, 7 mapped to Execute (no Design/Tasks phase — Medium scope, pure integration
proof over existing, already-Verified primitives), 0 unmapped.

---

## Success Criteria

- [ ] An integration test proves `enrich_from_identifier`'s `proposed` dict round-trips through
      `update_metadata` plan → confirm unchanged.
- [ ] An integration test proves `enrich_from_identifier`'s `cover.local_path` round-trips through
      `set_cover` plan → confirm unchanged.
- [ ] `enrich_from_identifier`'s docstring documents the two-step apply flow (fields via
      `update_metadata`, cover via `set_cover`) and the "don't call with empty/null" usage rules.
- [ ] Full build gate (pytest + mypy + ruff) stays green; zero production-code behavior change to
      `update_metadata`/`set_cover` (this feature adds tests + docs only).
