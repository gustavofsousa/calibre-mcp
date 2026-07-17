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

## Quarantined (failed when applied — ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
