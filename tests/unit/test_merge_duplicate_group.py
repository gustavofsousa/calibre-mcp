"""Unit tests for ``plan_loser_formats`` (ORGN-03, MERGE-01/07).

Derived from spec ACs, asserting spec-defined outcomes. No fixture / no
library — pure function, so these prove the format-split logic in isolation.

MERGE-01: plan lists, per loser, formats to add vs. already present.
MERGE-07: a format already on the survivor is not duplicated (reported, not
          added) — the split this function computes.
"""

from __future__ import annotations

import pytest

from calibre_mcp.library import plan_loser_formats


@pytest.mark.unit
def test_no_overlap_all_formats_to_add():
    to_add, already_present = plan_loser_formats(["PDF", "MOBI"], ["EPUB"])

    assert to_add == ["MOBI", "PDF"]
    assert already_present == []


@pytest.mark.unit
def test_full_overlap_nothing_to_add():
    to_add, already_present = plan_loser_formats(["EPUB"], ["EPUB", "PDF"])

    assert to_add == []
    assert already_present == ["EPUB"]


@pytest.mark.unit
def test_partial_overlap_splits_correctly():
    # MERGE-07: EPUB overlaps (already present), PDF is unique (to add).
    to_add, already_present = plan_loser_formats(["EPUB", "PDF"], ["EPUB"])

    assert to_add == ["PDF"]
    assert already_present == ["EPUB"]


@pytest.mark.unit
def test_loser_with_no_formats_yields_empty_split():
    to_add, already_present = plan_loser_formats([], ["EPUB"])

    assert to_add == []
    assert already_present == []
