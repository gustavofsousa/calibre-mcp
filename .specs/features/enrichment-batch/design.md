# ENRICH-03 (Batch Enrichment Review Mode) — Design

**Feature:** `enrichment-batch` · **Prefix:** `ENRICH3` · **Spec:** `./spec.md`
**Sizing:** Large (reader query + library facade + server tool + integration/unit tests + new AD).

## Design Intent

ENRICH-03 is a **bounded, read-only loop over the proven ENRICH-01 path** — it adds *selection* and
*aggregation*, not new network or proposal logic. Three moving parts, each a thin layer over what
already exists:

1. **Selection (reader):** one SQL query returns the ids of books that carry an ISBN **and** are
   missing an enrichable field, ordered by `id`, plus the total count for paging.
2. **Sweep (library facade):** validate the bounds, pull the candidate page, call the **existing**
   `enrich_from_identifier(book_id)` per id (isolating each `EnrichmentSourceError`), classify each
   outcome into a status bucket, and assemble the per-book results + summary. Writes nothing.
3. **Surface (server tool):** one new `@mcp.tool()` wrapping the facade with the standard
   `_map_errors` + `_jsonify`, documented as read-only/advisory and never-bulk-apply.

The whole batch invents **no new proposal shape**: a `status:"proposed"` item carries ENRICH-01's
verbatim payload so the host feeds it straight into the ENRICH-02 chain (`update_metadata` +
`set_cover`), per book, through the gates that already exist.

## Component Map

| Layer | Change | Why |
| --- | --- | --- |
| `sqlite_reader.py` | **New** `enrichable_candidates(limit, offset) -> tuple[int, list[int]]` | Targeted selection (missing-field ∧ has-isbn) without hydrating the whole library; returns `(total_count, page_ids)` from one connection. Mirrors the `books_by_*` id-discovery + `list_books` limit/offset conventions. |
| `library.py` | **New** `enrich_missing(limit=None, offset=0) -> dict` + module constants `ENRICH_BATCH_DEFAULT` (25) / `ENRICH_BATCH_MAX` (100) + a private `_classify_enrichment(result)` helper | The sweep: bound-check → select → per-candidate `enrich_from_identifier` with per-book isolation → bucketed result. Reuses `enrich_from_identifier`, `_field_missing`'s rule (embodied in the SQL), `EnrichmentSourceError`. |
| `server.py` | **New** `@mcp.tool() enrich_missing(limit=None, offset=0)` (`_map_errors` + `_jsonify`) | The MCP surface; sibling of `enrich_from_identifier`, read-only/advisory docstring. |
| `.specs/STATE.md` | **New AD-027** | Batch outbound policy: bounded sweep (cap + offset paging), per-book failure isolation, read-only advisory — resolves the rate-limit question ENRICH-01 (AD-026) deferred. |

No new module: ENRICH-03 is selection + aggregation over ENRICH-01, so it lives beside it in
`library.py`/`sqlite_reader.py` — no new external-I/O kind (AD-026's `openlibrary_client.py` stays the
sole outbound site; the batch calls it only *through* `enrich_from_identifier`).

## Data Models

### Candidate selection query (reader)

```sql
-- page ids
SELECT b.id
FROM books b
WHERE EXISTS (SELECT 1 FROM identifiers i
              WHERE i.book = b.id AND i.type = 'isbn' AND trim(i.val) != '')
  AND (
        NOT EXISTS (SELECT 1 FROM comments c WHERE c.book = b.id AND trim(c.text) != '')
     OR NOT EXISTS (SELECT 1 FROM books_publishers_link p WHERE p.book = b.id)
     OR b.pubdate IS NULL OR b.pubdate LIKE '0101-01-01%'
      )
ORDER BY b.id
LIMIT ? OFFSET ?;
-- total_count: the same WHERE wrapped in SELECT COUNT(*) (no LIMIT/OFFSET)
```

The three `missing` sub-conditions are the **exact** rules already in `sqlite_reader`: `comments`
missing = no non-blank row (`_stats_completeness`), `publisher` missing = no `books_publishers_link`
row, `pubdate` missing = NULL or `LIKE '0101-01-01%'` (`_PLACEHOLDER_PUBDATE_PREFIX`, LOOKUP-05). The
ISBN guard mirrors `identifiers` with `type='isbn'` and a non-blank value. One business rule for
"missing", no drift.

### Batch result shape (facade output)

```python
{
  "candidate_count": int,   # total books matching the filter (COUNT, before limit/offset)
  "processed": int,         # == len(results) == number looked up this call
  "limit": int,             # effective cap applied (<= ENRICH_BATCH_MAX)
  "offset": int,
  "results": [              # one per processed candidate, in id order
    # status "proposed" | "no_new_data" | "no_record": ENRICH-01 payload + status
    {"book_id": 12, "status": "proposed", "found": True, "source": "openlibrary",
     "identifier_used": {...}, "proposed": {...}, "skipped_present": [...], "cover": {...}|None},
    # status "error": the lookup raised; no ENRICH-01 payload, a reason instead
    {"book_id": 34, "status": "error", "reason": "<mapped EnrichmentSourceError message>"},
  ],
  "summary": {"proposed": int, "no_new_data": int, "no_record": int, "error": int},
}
```

`summary` counts sum to `processed`. `candidate_count > offset + processed` tells the host more remain.

### Status classification (`_classify_enrichment`)

Derived purely from what `enrich_from_identifier` returned (or raised) — no second network call:

| Outcome of `enrich_from_identifier(id)` | status |
| --- | --- |
| raised `EnrichmentSourceError` | `"error"` |
| `found is False` (no record at source; or the rare non-normalizable-ISBN) | `"no_record"` |
| `found is True` **and** (`proposed` non-empty **or** `cover` is not None) | `"proposed"` |
| `found is True` **and** `proposed` empty **and** `cover` is None | `"no_new_data"` |

The `found:false` bucket folds ENRICH-01's two negatives ("no record at source" and the residual
"isbn present but normalizes to empty") into `no_record`: both mean *nothing came back to fill*, which
is what the host acts on. The candidate SQL's `trim(val) != ''` guard makes the second case rare, and
classifying it as `no_record` is correct-enough (it is, factually, no usable record). Documented as a
minor SPEC note, not a deviation.

## Control Flow (`enrich_missing`)

```
1. Validate bounds (ENRICH3-08) — BEFORE any reader/network work:
     - offset: int (not bool), >= 0                    else InvalidInputError
     - limit:  None -> effective = ENRICH_BATCH_DEFAULT (25)
               else int (not bool), 1 <= limit <= ENRICH_BATCH_MAX (100), effective = limit
               (<=0, >MAX, non-int  -> InvalidInputError)
2. total_count, page_ids = reader.enrichable_candidates(effective_limit, offset)  # read-only
3. results = []; summary = {proposed:0, no_new_data:0, no_record:0, error:0}
   for book_id in page_ids:                            # sequential (ENRICH3-09)
       try:
           payload = self.enrich_from_identifier(book_id)   # reuse ENRICH-01 verbatim
           status  = _classify_enrichment(payload)
           results.append({**payload, "status": status})
       except EnrichmentSourceError as exc:                 # per-book isolation (ENRICH3-04)
           status = "error"
           results.append({"book_id": book_id, "status": "error", "reason": str(exc)})
       summary[status] += 1
4. return {candidate_count: total_count, processed: len(results),
           limit: effective_limit, offset, results, summary}
```

`bool` is rejected as a non-int (Python `bool` is an `int` subclass — the existing `_require_int`
discipline already guards this; the facade uses the same `isinstance(x, bool)` exclusion).

## Requirement Coverage

| Req | Where satisfied |
| --- | --- |
| ENRICH3-01 | `enrich_missing` selects via `enrichable_candidates`, loops `enrich_from_identifier`, returns `results`+`summary`; no `calibredb`/backup/token in the path. |
| ENRICH3-02 | `"proposed"` items spread the verbatim `enrich_from_identifier` payload (`proposed`/`skipped_present`/`cover`/`identifier_used`) + a `status` key. |
| ENRICH3-03 | `_classify_enrichment`: `found:false → no_record`; `found:true` with nothing to fill → `no_new_data`. |
| ENRICH3-04 | `try/except EnrichmentSourceError` per candidate → `status:"error"`, loop continues. |
| ENRICH3-05 | Result carries `candidate_count`, `processed`, `limit`, `offset`. |
| ENRICH3-06 | Empty candidate set / offset past end → empty `results`, zeroed `summary`, not an error. |
| ENRICH3-07 | Effective limit = default 25 when absent, else `min`-bounded by validated `limit`. |
| ENRICH3-08 | Bound validation raises `InvalidInputError` before `enrichable_candidates`/network. |
| ENRICH3-09 | Sequential `for` loop; each `enrich_from_identifier` carries LOOKUP-10's own timeout/retry. |

## Testing Strategy

Two safety rules hold together for the first time in one feature: **no real network** (inject
ENRICH-01's HTTP seam) **and** **no real-library write** (the `scratch_library` fixture).

- **Reader unit** (`tests/unit/…`): seed books exercising each selection branch (has-isbn+missing-comments,
  +missing-publisher, +placeholder-pubdate, complete→excluded, no-isbn→excluded); assert
  `enrichable_candidates` returns the right ids in `id` order and the right `total_count`; assert
  `limit`/`offset` page correctly.
- **Batch integration** (`tests/integration/test_enrichment_batch.py`): drive `enrich_missing`
  end-to-end with the injected HTTP seam, covering the P1 independent test (A proposed / B proposed /
  C,D excluded / E error, summary+counts, no library write), `limit:1`, `offset` past end,
  `no_new_data`, `no_record`; and the P2 tests (default-25 of 30 candidates, `limit` 0/1000 and
  negative `offset` rejected before any seam call, sequential one-call-per-candidate).
- **Discrimination sensors the Verifier will inject:** flip a candidate `WHERE` clause (drop the isbn
  guard → a no-isbn book leaks in), turn `except EnrichmentSourceError` into a re-raise (batch aborts
  → ENRICH3-04 test fails), off-by-one the cap (26 processed → ENRICH3-07 fails), mis-classify
  `no_new_data` as `proposed`.

## Risks & Mitigations

| Risk | Mitigation |
| --- | --- |
| A large real library × the batch = many outbound calls | Default cap 25 + hard ceiling 100 + `offset` paging (ENRICH3-07/08); sequential, each with ENRICH-01's bounded timeout. |
| Selection SQL drifts from ENRICH-01's "missing" definition | Reuse the identical rules (`0101-01-01%`, non-blank comments, publisher-link presence) — verified against `_stats_completeness`; a reader unit test pins each branch. |
| A book vanishes between selection and lookup (race) | Single-user local library; not a real scenario. Only `EnrichmentSourceError` is isolated per spec; a `BookNotFoundError` mid-sweep would propagate (documented, not handled). |
| Host mistakes the batch for an apply | Docstring states read-only/advisory + "never bulk-applies"; result has no token and no `applied`/`written` field — nothing suggests a write happened. |

## Decisions to record

**AD-027 — Batch outbound policy: a bounded, read-only sweep, never a bulk apply.** ENRICH-03 resolves
the rate-limit question AD-026 (ENRICH-01) explicitly deferred: outbound volume is bounded by a default
cap (25) + hard ceiling (100) + `offset` paging rather than a token-bucket limiter (still single-user,
low volume). The batch is **read-only advisory** (AD-016) — no `calibredb`, no backup, no token — and
**per-book isolated** (AD-020 best-effort bucketing): one candidate's `EnrichmentSourceError` is that
item's `status:"error"`, never an aborted batch. It adds **no new outbound site** — the sole HTTP
module (AD-026) is reached only through `enrich_from_identifier`. Tool naming: `enrich_missing`
(sibling of `enrich_from_identifier`).
