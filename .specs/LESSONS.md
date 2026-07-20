# LESSONS — auto-maintained by scripts/lessons.py

> Machine-owned. Do NOT hand-edit. Changes are overwritten on the next `lessons.py` write.
> Canonical state lives in `.specs/lessons.json`. Edit lessons only via the script.
> promote_threshold=2 distinct features · window_days=45 · quarantine_threshold=2

## Confirmed (load these at Specify/Design)

Corroborated across multiple features. Safe to apply as guidance.

_none_

## Candidates (under observation — do NOT load as guidance yet)

Seen once or not yet corroborated. Tracked, not trusted.

### L-001 — When a facade method backs up before a write for AD-011 safety, add a call-order test (spy/monkeypatch recording invocation order), not just a post-hoc existence check on the backup file.
- signal: `surviving_mutant` · recurrence: 1 feature(s) · scope: `library-facade` · harmful: 0
- features: calibre-management-p2
- evidence: src/calibre_mcp/library.py:144-151 (mutant 4, validation.md) (library-facade)
- last seen: 2026-07-17T15:11:39Z

### L-002 — When an AC names two branches (explicit choice vs. default-preference fallback), write a passing-case test for each branch, not just the fallback success case and the explicit-choice failure case.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `test-coverage` · harmful: 0
- features: calibre-management-p2
- evidence: EMAIL-01 AC-3 (spec.md); tests/integration/test_library_p2.py (test-coverage)
- last seen: 2026-07-17T15:11:39Z

### L-003 — A spec claim of lock-independence for a read path needs a test that actually holds a lock during the read, not just reuse of a mode=ro connection pattern already used elsewhere.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `read-layer` · harmful: 0
- features: library-stats
- evidence: STATS-01-03, .specs/features/library-stats/validation.md (read-layer)
- last seen: 2026-07-20T17:20:25Z

### L-004 — When a framework already wraps all handler exceptions into a generic error type, test the app-level exception mapper directly (unit-level, bypassing the framework) rather than relying on an end-to-end assertion that the framework's catch-all can satisfy on its own.
- signal: `surviving_mutant` · recurrence: 1 feature(s) · scope: `server-errors` · harmful: 0
- features: library-stats
- evidence: src/calibre_mcp/server.py:87-89 (mutation #3), .specs/features/library-stats/validation.md (server-errors)
- last seen: 2026-07-20T17:20:25Z

### L-005 — Cover every spec Edge Case with an assertion on the specific value or multiplicity it calls out, not just a key-presence or single-instance check that would pass even if the edge-case logic were removed.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `spec-driven-tests` · harmful: 0
- features: library-stats
- evidence: spec.md Edge Cases (unset bucket, multiple duplicate groups, real_pubdate), .specs/features/library-stats/validation.md (spec-driven-tests)
- last seen: 2026-07-20T17:20:25Z

## Quarantined (failed when applied — ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
