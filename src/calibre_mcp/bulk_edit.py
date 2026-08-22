"""Pure list-mode set algebra for bulk edits (BULK-01, BEDIT-08/09).

The only genuinely new logic in ``update_metadata_bulk``: resolving a broadcast
``fields`` map into the exact per-book field map to write, applying ``add`` /
``remove`` / ``replace`` semantics to the list-valued fields. Kept pure (no I/O,
no ``Book`` import — the record is duck-typed via ``getattr``) so the union /
difference edge cases are unit-testable without a scratch library.

The SAME ``resolve_fields`` output feeds both the plan diff and the write, so the
review always reflects exactly what will be written (BEDIT-08 AC-4). Matching is
exact-string; any case-folding / dedup Calibre applies on write is downstream and
surfaces in the re-read, not here.
"""

from __future__ import annotations

from typing import Any

# List-valued editable fields a ``list_mode`` can apply to — the fields
# ``calibredb set_metadata`` comma-joins (design §Components).
LIST_FIELDS = frozenset({"authors", "tags", "languages"})

# The three broadcast list modes (spec P1: list-field add/remove/replace).
LIST_MODES = frozenset({"replace", "add", "remove"})


def apply_list_mode(current: list[str], supplied: list[str], mode: str) -> list[str]:
    """Resolve one list field's final value under ``mode`` (BEDIT-08/09).

    - ``add``: order-preserving union of ``current`` with the ``supplied`` values
      not already present — idempotent, no duplicates (BEDIT-09).
    - ``remove``: ``current`` minus ``supplied``; values absent from ``current``
      are ignored, order preserved (BEDIT-09). May resolve to ``[]``.
    - ``replace`` (default): ``supplied`` as-is (today's ``set_metadata``
      overwrite semantics).
    """
    if mode == "add":
        return list(current) + [v for v in supplied if v not in current]
    if mode == "remove":
        removed = set(supplied)
        return [v for v in current if v not in removed]
    return list(supplied)


def resolve_fields(
    current: object, fields: dict[str, Any], mode: str
) -> dict[str, Any]:
    """Return the exact field map to write for one book under ``mode``.

    List fields (``LIST_FIELDS``) under a non-``replace`` mode are resolved
    against the book's current values via ``apply_list_mode``; every other field
    — scalars and any list field under ``replace`` — is passed through unchanged.
    This single output is consumed by both the plan diff and the write, so the
    reviewed ``proposed`` set is exactly what gets written (BEDIT-08 AC-4).
    """
    if mode == "replace":
        return dict(fields)

    resolved: dict[str, Any] = {}
    for name, value in fields.items():
        if name in LIST_FIELDS:
            existing = getattr(current, name, None) or []
            resolved[name] = apply_list_mode(existing, value, mode)
        else:
            resolved[name] = value
    return resolved
