"""Unit tests for ``resolve_renamed_values`` (shared rule; ORGN-01 + ORGN-02).

Derived from spec ACs, asserting spec-defined outcomes. No fixture / no
library — pure function, so these prove the swap/dedupe logic in isolation.

The rule (TRENAME-07 for tags, ARENAME-07 for authors):
- replace only ``old`` with ``new``, preserving every other value and order;
- a list holding both ``old`` and ``new`` collapses to a single ``new``
  (order-preserving in-book dedupe / merge);
- every occurrence of ``old`` is replaced and deduped;
- a list containing ``old`` always yields >= 1 value.
"""

from __future__ import annotations

import pytest

from calibre_mcp.author_rename import resolve_renamed_authors
from calibre_mcp.rename_resolve import resolve_renamed_values


@pytest.mark.unit
def test_single_value_renamed():
    # [old] -> [new].
    assert resolve_renamed_values(["old"], "old", "new") == ["new"]


@pytest.mark.unit
def test_other_value_preserved_in_original_position_and_order():
    # AC1: ["a", "old", "b"] -> ["a", "new", "b"].
    assert resolve_renamed_values(["a", "old", "b"], "old", "new") == [
        "a",
        "new",
        "b",
    ]


@pytest.mark.unit
def test_values_untouched_when_old_not_present():
    # Baseline: no occurrence of ``old`` leaves the list unchanged.
    assert resolve_renamed_values(["x", "y"], "old", "new") == ["x", "y"]


@pytest.mark.unit
def test_list_holding_both_old_and_new_merges_at_olds_position():
    # AC2: ["old", "new"] -> ["new"] (single, deduped).
    assert resolve_renamed_values(["old", "new"], "old", "new") == ["new"]


@pytest.mark.unit
def test_list_holding_new_then_old_merges_keeping_first_position():
    # ["new", "old"] -> ["new"] (dedupe keeps new's earlier slot).
    assert resolve_renamed_values(["new", "old"], "old", "new") == ["new"]


@pytest.mark.unit
def test_duplicate_old_occurrences_collapse_to_single_new():
    # A list holding ``old`` more than once -- every occurrence replaced and
    # deduped to a single ``new``.
    assert resolve_renamed_values(["old", "old"], "old", "new") == ["new"]


@pytest.mark.unit
def test_list_containing_old_never_yields_empty():
    # Invariant: a list containing ``old`` always yields >= 1 value.
    assert len(resolve_renamed_values(["old"], "old", "new")) >= 1


@pytest.mark.unit
def test_author_alias_delegates_to_shared_resolver():
    # Regression: the ORGN-01 alias stays behavior-identical to the generic.
    assert resolve_renamed_authors is resolve_renamed_values
    assert resolve_renamed_authors(["A", "Old", "B"], "Old", "New") == [
        "A",
        "New",
        "B",
    ]
