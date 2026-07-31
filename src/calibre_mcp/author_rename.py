"""Pure author-list resolution for renaming an author (ORGN-01, ARENAME-07).

Thin re-export of the generalized :func:`resolve_renamed_values`
(``rename_resolve``): the swap/dedupe rule is identical for authors and tags,
so it is centralized in one place. Kept as ``resolve_renamed_authors`` for the
ORGN-01 call site and its tests, which read as author-specific.
"""

from __future__ import annotations

from .rename_resolve import resolve_renamed_values

# Author rename is the value-rename rule applied to the ``authors`` list.
resolve_renamed_authors = resolve_renamed_values

__all__ = ["resolve_renamed_authors"]
