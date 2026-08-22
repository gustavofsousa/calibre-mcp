"""Unit tests for ``resolve_renamed_authors`` (ORGN-01, ARENAME-07).

Derived from spec ACs, asserting spec-defined outcomes. No fixture / no
library — pure function, so these prove the swap/dedupe logic in isolation.

ARENAME-07 AC1: replace only ``old`` with ``new``, preserving co-authors and
                order (e.g. ["A", "Old", "B"] -> ["A", "New", "B"]).
ARENAME-07 AC2: a book crediting both ``old`` and ``new`` collapses to a
                single ``new``, in ``old``'s former position (order-preserving
                in-book dedupe/merge).
ARENAME-07 AC3 (design cases): [Old] -> [New]; [Old,Old] -> [New] (data
                anomaly, every occurrence replaced and deduped); [New,Old] ->
                [New] (dedupe keeps the first occurrence's position).
"""

from __future__ import annotations

import pytest

from calibre_mcp.author_rename import resolve_renamed_authors


@pytest.mark.unit
def test_single_author_book_renamed():
    # Design case: [Old] -> [New].
    assert resolve_renamed_authors(["Old"], "Old", "New") == ["New"]


@pytest.mark.unit
def test_co_author_preserved_in_original_position_and_order():
    # ARENAME-07 AC1: ["A", "Old", "B"] -> ["A", "New", "B"].
    assert resolve_renamed_authors(["A", "Old", "B"], "Old", "New") == [
        "A",
        "New",
        "B",
    ]


@pytest.mark.unit
def test_other_authors_untouched_when_old_not_present():
    # Baseline: no occurrence of ``old`` leaves the list unchanged.
    assert resolve_renamed_authors(["X", "Y"], "Old", "New") == ["X", "Y"]


@pytest.mark.unit
def test_book_crediting_both_old_and_new_merges_at_olds_position():
    # ARENAME-07 AC2: ["Old", "New"] -> ["New"] (single, deduped).
    assert resolve_renamed_authors(["Old", "New"], "Old", "New") == ["New"]


@pytest.mark.unit
def test_book_crediting_new_then_old_merges_keeping_first_position():
    # Design case: ["New", "Old"] -> ["New"] (dedupe keeps New's earlier slot).
    assert resolve_renamed_authors(["New", "Old"], "Old", "New") == ["New"]


@pytest.mark.unit
def test_duplicate_old_occurrences_collapse_to_single_new():
    # Edge case (spec): a book listing ``old`` more than once -- every
    # occurrence replaced and deduped to a single ``new``.
    assert resolve_renamed_authors(["Old", "Old"], "Old", "New") == ["New"]


@pytest.mark.unit
def test_renamed_book_never_yields_empty_author_list():
    # Design invariant: a book credited to ``old`` always yields >= 1 author.
    result = resolve_renamed_authors(["Old"], "Old", "New")
    assert len(result) >= 1
