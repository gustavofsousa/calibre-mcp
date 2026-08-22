"""Pure value-list resolution for renaming one entry across a list field.

Computes a book's post-rename list for any flat multi-valued field (authors,
tags, ...): replace only ``old`` with ``new``, preserving every other value and
the original order, with an in-book order-preserving dedupe (so a list already
containing both ``old`` and ``new`` merges to a single ``new``). Kept pure (no
I/O) so the swap/merge edge cases are unit-testable without a scratch library.

The rule is identical for authors (ORGN-01) and tags (ORGN-02) — a single set
operation centralized here rather than duplicated per field (a shared business
rule drifts if it lives in two places). ``author_rename.resolve_renamed_authors``
re-exports this for backward compatibility.
"""

from __future__ import annotations


def resolve_renamed_values(values: list[str], old: str, new: str) -> list[str]:
    """Return ``values`` with ``old`` replaced by ``new``, deduped in order.

    - Every occurrence of ``old`` becomes ``new``; every other value is
      unchanged, in its original position (co-value-safe swap).
    - If the resulting list would contain ``new`` more than once (the list
      already held both, or ``old`` appeared more than once), only the first
      occurrence is kept (order-preserving dedupe / merge).
    - A list containing ``old`` always yields at least one value.
    """
    result: list[str] = []
    for value in values:
        replacement = new if value == old else value
        if replacement not in result:
            result.append(replacement)
    return result
