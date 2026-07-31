"""Pure author-list resolution for renaming an author (ORGN-01, ARENAME-07).

Computes one book's post-rename author list: replace only ``old`` with ``new``,
preserving every co-author and the original order, with an in-book
order-preserving dedupe (so a book already crediting both ``old`` and ``new``
merges to a single ``new``). Kept pure (no I/O) so the swap/merge edge cases
are unit-testable without a scratch library — mirrors ``bulk_edit.py``.
"""

from __future__ import annotations


def resolve_renamed_authors(authors: list[str], old: str, new: str) -> list[str]:
    """Return ``authors`` with ``old`` replaced by ``new``, deduped in order.

    - Every occurrence of ``old`` becomes ``new``; every other author is
      unchanged, in its original position (co-author-safe swap).
    - If the resulting list would contain ``new`` more than once (the book
      already credited both, or ``old`` appeared more than once), only the
      first occurrence is kept (order-preserving dedupe / merge).
    - A book crediting ``old`` always yields at least one author.
    """
    result: list[str] = []
    for author in authors:
        replacement = new if author == old else author
        if replacement not in result:
            result.append(replacement)
    return result
