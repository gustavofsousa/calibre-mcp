# LESSONS — auto-maintained by scripts/lessons.py

> Machine-owned. Do NOT hand-edit. Changes are overwritten on the next `lessons.py` write.
> Canonical state lives in `.specs/lessons.json`. Edit lessons only via the script.
> promote_threshold=2 distinct features · window_days=45 · quarantine_threshold=2

## Confirmed (load these at Specify/Design)

Corroborated across multiple features. Safe to apply as guidance.

_none_

## Candidates (under observation — do NOT load as guidance yet)

Seen once or not yet corroborated. Tracked, not trusted.

### L-009 — When a value crosses an external-CLI boundary, add a write-then-reread round-trip test per field whose unit could differ (scale, encoding, separator) — range validation alone cannot catch a unit mismatch.
- signal: `ac_gap` · recurrence: 1 feature(s) · scope: `runner-boundary` · harmful: 0
- features: calibre-management
- evidence: AD-030; tests/integration/test_calibredb_runner.py rating round-trip (runner-boundary)
- last seen: 2026-10-01T22:01:50Z

### L-010 — Never source test fixtures from an absolute personal path — generate them, and fail rather than skip when they're missing, because a skip keeps the gate green while the path under test silently stops running.
- signal: `gate_fail` · recurrence: 1 feature(s) · scope: `test-infrastructure` · harmful: 0
- features: calibre-management
- evidence: AD-029; tests/sample_books.py (test-infrastructure)
- last seen: 2026-10-01T22:01:50Z

## Quarantined (failed when applied — ignore)

A confirmed lesson that recurred alongside failure. Kept for the maintainer to review.

_none_
