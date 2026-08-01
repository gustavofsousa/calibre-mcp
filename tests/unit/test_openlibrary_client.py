"""Unit tests for the Open Library client's transport + retry seam (ENRICH-01, T2).

Derived from spec.md P1-network ACs (LOOKUP-08/10) and the T2 "Done when"
criteria, asserting spec-defined outcomes. No network: every test drives an
injected ``http_get`` seam scripted to raise/return (spec test-safety rule).

LOOKUP-10: a request retries at most once, and the configured timeout is passed
           through to the transport.
LOOKUP-08: when the transport keeps failing, an ``EnrichmentSourceError`` is
           raised — never a silent failure.
"""

from __future__ import annotations

import pytest

from calibre_mcp.errors import EnrichmentSourceError
from calibre_mcp.openlibrary_client import OpenLibraryClient


class _Spy:
    """A scripted ``http_get`` seam: records every call, raises/returns per step."""

    def __init__(self, outcomes: list[object]) -> None:
        self.calls: list[tuple[str, float]] = []
        self._outcomes = list(outcomes)

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append((url, timeout))
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, bytes)
        return outcome


@pytest.mark.unit
def test_fetch_retries_once_then_succeeds() -> None:
    # LOOKUP-10: one failure -> exactly one retry -> success (call count == 2).
    spy = _Spy([EnrichmentSourceError("boom"), b"ok"])
    client = OpenLibraryClient(http_get=spy)

    assert client._fetch("https://openlibrary.org/x") == b"ok"
    assert len(spy.calls) == 2


@pytest.mark.unit
def test_fetch_raising_always_surfaces_enrichment_error() -> None:
    # LOOKUP-08: transport keeps failing -> EnrichmentSourceError, no crash, and
    # the client gives up after 1 attempt + 1 retry (call count == 2).
    spy = _Spy([EnrichmentSourceError("down"), EnrichmentSourceError("down")])
    client = OpenLibraryClient(http_get=spy)

    with pytest.raises(EnrichmentSourceError):
        client._fetch("https://openlibrary.org/x")
    assert len(spy.calls) == 2


@pytest.mark.unit
def test_fetch_passes_configured_timeout_through_to_seam() -> None:
    # LOOKUP-10: the bounded timeout the client was built with reaches the transport.
    spy = _Spy([b"ok"])
    client = OpenLibraryClient(http_get=spy, timeout=3.5)

    client._fetch("https://openlibrary.org/x")
    assert spy.calls[0][1] == 3.5


@pytest.mark.unit
def test_retries_zero_makes_no_retry() -> None:
    # LOOKUP-10 boundary: retries=0 -> a single attempt, no retry (call count == 1).
    spy = _Spy([EnrichmentSourceError("down")])
    client = OpenLibraryClient(http_get=spy, retries=0)

    with pytest.raises(EnrichmentSourceError):
        client._fetch("https://openlibrary.org/x")
    assert len(spy.calls) == 1
