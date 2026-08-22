"""Unit tests for the pure list-mode set algebra (BULK-01, BEDIT-08/09).

Derived from spec ACs, asserting spec-defined outcomes. No fixture / no library —
the record is duck-typed via ``SimpleNamespace`` (mirrors ``resolve_fields``'
``getattr`` access), so these prove the union / difference logic in isolation.

BEDIT-08 AC1: add   -> union of current with supplied (existing preserved).
BEDIT-08 AC2: remove -> current minus supplied (missing values ignored).
BEDIT-08 AC3: replace -> overwrite with exactly the supplied values.
BEDIT-08 AC4: resolve_fields is the single source for plan diff AND write.
BEDIT-09:     add of a present value / remove of an absent value is a no-op.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from calibre_mcp.bulk_edit import (
    LIST_FIELDS,
    LIST_MODES,
    apply_list_mode,
    resolve_fields,
)


@pytest.mark.unit
def test_constants_are_the_spec_defined_sets():
    # The list-valued editable fields and the three broadcast modes.
    assert LIST_FIELDS == frozenset({"authors", "tags", "languages"})
    assert LIST_MODES == frozenset({"replace", "add", "remove"})


@pytest.mark.unit
def test_add_unions_and_dedupes_preserving_order():
    # BEDIT-08 AC1 + BEDIT-09: [a,b] add [b,c] -> [a,b,c] (b not duplicated).
    assert apply_list_mode(["a", "b"], ["b", "c"], "add") == ["a", "b", "c"]


@pytest.mark.unit
def test_add_of_only_present_values_is_a_noop():
    # BEDIT-09: adding values a book already has changes nothing (idempotent).
    assert apply_list_mode(["a", "b"], ["a", "b"], "add") == ["a", "b"]


@pytest.mark.unit
def test_remove_subtracts_and_ignores_missing():
    # BEDIT-08 AC2 + BEDIT-09: [a,b,c] remove [a,z] -> [b,c] (z absent, no error).
    assert apply_list_mode(["a", "b", "c"], ["a", "z"], "remove") == ["b", "c"]


@pytest.mark.unit
def test_remove_can_resolve_to_empty():
    # Spec edge case: remove that empties the field yields [] (the diff shows []).
    assert apply_list_mode(["a"], ["a"], "remove") == []


@pytest.mark.unit
def test_replace_returns_supplied_as_is():
    # BEDIT-08 AC3: replace overwrites with exactly the supplied values.
    assert apply_list_mode(["a", "b"], ["x", "y"], "replace") == ["x", "y"]


@pytest.mark.unit
def test_resolve_fields_applies_mode_to_list_field_against_current():
    # BEDIT-08 AC4: proposed set is resolved against the book's current values.
    book = SimpleNamespace(tags=["a", "b"], authors=["A"], languages=["eng"])
    resolved = resolve_fields(book, {"tags": ["b", "c"]}, "add")
    assert resolved == {"tags": ["a", "b", "c"]}


@pytest.mark.unit
def test_resolve_fields_passes_scalar_fields_through_under_list_mode():
    # A non-list field is passed through unchanged even under add/remove.
    book = SimpleNamespace(tags=["a"], authors=["A"], languages=["eng"])
    resolved = resolve_fields(book, {"tags": ["b"], "series": "Dune"}, "add")
    assert resolved == {"tags": ["a", "b"], "series": "Dune"}


@pytest.mark.unit
def test_resolve_fields_replace_mode_passes_everything_through_unresolved():
    # Under replace, list fields are NOT unioned — supplied values overwrite.
    book = SimpleNamespace(tags=["a", "b"], authors=["A"], languages=["eng"])
    resolved = resolve_fields(book, {"tags": ["x"]}, "replace")
    assert resolved == {"tags": ["x"]}


@pytest.mark.unit
def test_resolve_fields_missing_current_attribute_treated_as_empty():
    # A book lacking the attribute resolves against [] (add starts from empty).
    book = SimpleNamespace(tags=["a"])
    resolved = resolve_fields(book, {"authors": ["A"]}, "add")
    assert resolved == {"authors": ["A"]}
