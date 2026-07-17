"""Unit tests for the plan->confirm token gate — derived from EDIT-01/03, REM-01/05.

EDIT-01/REM-01: a plan returns a deterministic confirmation_token for that exact
                change (same input -> same token).
EDIT-03/REM-05: a token that does not match the requested change is refused.
Normalization: the token is independent of payload key order.
"""

from __future__ import annotations

import pytest

from calibre_mcp.confirmation import plan_token, verify
from calibre_mcp.errors import ConfirmationError


@pytest.mark.unit
def test_same_input_produces_same_token():
    # EDIT-01: deterministic — the apply call can recompute the exact token.
    payload = {"tags": ["scifi"], "rating": 8}
    assert plan_token("update", 42, payload) == plan_token("update", 42, payload)


@pytest.mark.unit
def test_payload_change_produces_different_token():
    # EDIT-03: a different change must not verify under the old token.
    base = plan_token("update", 42, {"tags": ["scifi"]})
    changed = plan_token("update", 42, {"tags": ["fantasy"]})
    assert base != changed


@pytest.mark.unit
def test_op_or_book_id_change_produces_different_token():
    payload = {"tags": ["scifi"]}
    assert plan_token("update", 42, payload) != plan_token("remove", 42, payload)
    assert plan_token("update", 42, payload) != plan_token("update", 43, payload)


@pytest.mark.unit
def test_token_is_key_order_independent():
    # Logically-equal payloads (any key order) yield the same token.
    a = plan_token("update", 1, {"tags": ["a"], "rating": 6})
    b = plan_token("update", 1, {"rating": 6, "tags": ["a"]})
    assert a == b


@pytest.mark.unit
def test_verify_passes_for_matching_token():
    payload = {"series": "Dune", "series_index": 2}
    token = plan_token("update", 7, payload)
    assert verify("update", 7, payload, token) is None  # no raise


@pytest.mark.unit
def test_verify_raises_for_mismatched_token():
    # EDIT-03/REM-05: wrong token -> refuse to apply.
    payload = {"series": "Dune"}
    token = plan_token("update", 7, payload)
    with pytest.raises(ConfirmationError):
        verify("update", 7, {"series": "Foundation"}, token)


@pytest.mark.unit
def test_verify_raises_when_token_is_garbage():
    payload = {"tags": ["x"]}
    with pytest.raises(ConfirmationError):
        verify("update", 7, payload, "not-a-real-token")
