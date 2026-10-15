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
from calibre_mcp.openlibrary_client import (
    OpenLibraryClient,
    OpenLibraryRecord,
    SearchCandidate,
)


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


class _RoutingFake:
    """A URL-routing ``http_get`` seam: matches a URL substring to an outcome.

    Order-independent (routes by URL, not call sequence) so each test states only
    the endpoints it exercises; ``calls`` records every URL for follow-up-count
    assertions. An unrouted URL fails loudly rather than silently returning junk.
    """

    def __init__(self, routes: list[tuple[str, object]]) -> None:
        self.calls: list[str] = []
        self._routes = routes

    def __call__(self, url: str, timeout: float) -> bytes:
        self.calls.append(url)
        for substring, outcome in self._routes:
            if substring in url:
                if isinstance(outcome, Exception):
                    raise outcome
                assert isinstance(outcome, bytes)
                return outcome
        raise AssertionError(f"unexpected url: {url}")


_ISBN = "9780553293357"
_COVER_L = "https://covers.openlibrary.org/b/id/12345-L.jpg"
_BOOKS_NO_DESC = (
    b'{"ISBN:9780553293357": {"publishers": [{"name": "Bantam"}], '
    b'"publish_date": "April 2009", '
    b'"cover": {"small": "https://covers.openlibrary.org/b/id/12345-S.jpg", '
    b'"medium": "https://covers.openlibrary.org/b/id/12345-M.jpg", '
    b'"large": "https://covers.openlibrary.org/b/id/12345-L.jpg"}}}'
)
_EDITION = b'{"works": [{"key": "/works/OL456W"}]}'


@pytest.mark.unit
def test_fetch_record_happy_books_plus_work_follow_up() -> None:
    # LOOKUP-04: Books API (no description) -> edition -> work supplies the
    # description; the whole record is returned with every field populated.
    fake = _RoutingFake(
        [
            ("api/books", _BOOKS_NO_DESC),
            ("/isbn/", _EDITION),
            ("/works/", b'{"description": "A sprawling space opera."}'),
        ]
    )
    record = OpenLibraryClient(http_get=fake).fetch_record(_ISBN)

    assert record == OpenLibraryRecord(
        publisher="Bantam",
        pubdate="April 2009",
        description="A sprawling space opera.",
        cover_url=_COVER_L,
    )


@pytest.mark.unit
def test_fetch_record_flattens_object_form_description() -> None:
    # LOOKUP-04 edge: the work description in the {"type","value"} object form is
    # flattened to its string.
    fake = _RoutingFake(
        [
            ("api/books", _BOOKS_NO_DESC),
            ("/isbn/", _EDITION),
            ("/works/", b'{"description": {"type": "t", "value": "Object desc."}}'),
        ]
    )
    record = OpenLibraryClient(http_get=fake).fetch_record(_ISBN)

    assert record is not None
    assert record.description == "Object desc."


@pytest.mark.unit
def test_fetch_record_no_follow_up_when_description_present_in_structured() -> None:
    # Description already on the structured record -> NO edition/work follow-up
    # (exactly one GET made).
    books_with_desc = (
        b'{"ISBN:9780553293357": {"publishers": [{"name": "Bantam"}], '
        b'"publish_date": "2009", "description": "Inline desc."}}'
    )
    fake = _RoutingFake([("api/books", books_with_desc)])
    record = OpenLibraryClient(http_get=fake).fetch_record(_ISBN)

    assert record is not None
    assert record.description == "Inline desc."
    assert len(fake.calls) == 1


@pytest.mark.unit
def test_fetch_record_clean_not_found_returns_none() -> None:
    # LOOKUP-07: an empty Books API body (unknown ISBN) is a normal negative -> None.
    fake = _RoutingFake([("api/books", b"{}")])
    assert OpenLibraryClient(http_get=fake).fetch_record(_ISBN) is None


@pytest.mark.unit
def test_fetch_record_unparseable_body_raises_enrichment_error() -> None:
    # LOOKUP-08: a non-JSON Books API body is a source failure, not a silent None.
    fake = _RoutingFake([("api/books", b"<html>oops</html>")])
    with pytest.raises(EnrichmentSourceError):
        OpenLibraryClient(http_get=fake).fetch_record(_ISBN)


@pytest.mark.unit
def test_fetch_record_failed_description_follow_up_is_non_fatal() -> None:
    # LOOKUP-04 non-fatal: the description hop failing leaves description None but
    # still returns the publisher/pubdate already fetched.
    fake = _RoutingFake(
        [
            ("api/books", _BOOKS_NO_DESC),
            ("/isbn/", EnrichmentSourceError("edition unreachable")),
        ]
    )
    record = OpenLibraryClient(http_get=fake).fetch_record(_ISBN)

    assert record is not None
    assert record.description is None
    assert record.publisher == "Bantam"
    assert record.pubdate == "April 2009"


@pytest.mark.unit
def test_fetch_record_cover_falls_back_to_smaller_when_large_absent() -> None:
    # cover-id URL is the "largest available": with only a small present, use it.
    books = (
        b'{"ISBN:9780553293357": {"publishers": [{"name": "Bantam"}], '
        b'"publish_date": "2009", "description": "d", '
        b'"cover": {"small": "https://covers.openlibrary.org/b/id/9-S.jpg"}}}'
    )
    fake = _RoutingFake([("api/books", books)])
    record = OpenLibraryClient(http_get=fake).fetch_record(_ISBN)

    assert record is not None
    assert record.cover_url == "https://covers.openlibrary.org/b/id/9-S.jpg"


_IMAGE_BYTES = b"\x89PNG\r\n\x1a\n-fake-cover-bytes-"


@pytest.mark.unit
def test_download_cover_writes_surviving_file_with_exact_bytes(tmp_path) -> None:
    # LOOKUP-06: the fetched bytes land on disk, the file survives the call, and
    # the name carries the enrich prefix.
    fake = _RoutingFake([("id/12345-L.jpg", _IMAGE_BYTES)])
    path = OpenLibraryClient(http_get=fake).download_cover(_COVER_L, dest_dir=tmp_path)

    assert path.exists()  # survives past the method return
    assert path.read_bytes() == _IMAGE_BYTES
    assert path.name.startswith("calibre-mcp-enrich-")


@pytest.mark.unit
def test_download_cover_failure_raises_and_leaves_no_file(tmp_path) -> None:
    # LOOKUP-09: a fetch failure raises EnrichmentSourceError and leaves no
    # partial/zero-byte file behind.
    fake = _RoutingFake([("id/12345-L.jpg", EnrichmentSourceError("cover 500"))])
    with pytest.raises(EnrichmentSourceError):
        OpenLibraryClient(http_get=fake).download_cover(_COVER_L, dest_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


@pytest.mark.unit
def test_download_cover_honors_custom_dest_dir(tmp_path) -> None:
    # dest_dir is respected: the file is written under the given directory.
    fake = _RoutingFake([("id/12345-L.jpg", _IMAGE_BYTES)])
    path = OpenLibraryClient(http_get=fake).download_cover(_COVER_L, dest_dir=tmp_path)

    assert path.parent == tmp_path


class _FakeResponse:
    """Minimal context-manager response for a monkeypatched urlopen."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._data


@pytest.mark.unit
def test_urllib_get_sets_user_agent_and_default_timeout(monkeypatch) -> None:
    # LOOKUP-10: the real transport identifies itself with a descriptive User-Agent
    # and applies the bounded default 10s timeout. Drives the default _urllib_get
    # (no injected seam) against a fake urlopen.
    from calibre_mcp.openlibrary_client import _DEFAULT_UA

    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        captured["ua"] = request.get_header("User-agent")
        captured["timeout"] = timeout
        return _FakeResponse(b"payload")

    monkeypatch.setattr(
        "calibre_mcp.openlibrary_client.urllib.request.urlopen", fake_urlopen
    )
    result = OpenLibraryClient()._fetch("https://openlibrary.org/thing")

    assert result == b"payload"
    assert captured["ua"] == _DEFAULT_UA
    assert captured["timeout"] == 10.0


@pytest.mark.unit
def test_urllib_get_wraps_urlerror_as_enrichment_error(monkeypatch) -> None:
    # LOOKUP-08: a transport (URLError) failure in the real call site becomes an
    # EnrichmentSourceError, not a raw urllib error. retries=0 keeps it to one call.
    import urllib.error

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        raise urllib.error.URLError("unreachable")

    monkeypatch.setattr(
        "calibre_mcp.openlibrary_client.urllib.request.urlopen", fake_urlopen
    )
    with pytest.raises(EnrichmentSourceError):
        OpenLibraryClient(retries=0)._fetch("https://openlibrary.org/thing")


@pytest.mark.unit
def test_urllib_get_wraps_httperror_with_status_code(monkeypatch) -> None:
    # LOOKUP-08: an HTTP >= 400 becomes an EnrichmentSourceError naming the status.
    import urllib.error

    def fake_urlopen(request, timeout):  # type: ignore[no-untyped-def]
        raise urllib.error.HTTPError(
            "https://openlibrary.org/thing", 503, "Service Unavailable", {}, None
        )

    monkeypatch.setattr(
        "calibre_mcp.openlibrary_client.urllib.request.urlopen", fake_urlopen
    )
    with pytest.raises(EnrichmentSourceError) as excinfo:
        OpenLibraryClient(retries=0)._fetch("https://openlibrary.org/thing")
    assert "503" in str(excinfo.value)


# ------------------------------------------------- ENRICH-04: title/author search


def _search_body(*docs: dict[str, object]) -> bytes:
    import json

    return json.dumps({"numFound": len(docs), "docs": list(docs)}).encode()


def _query(url: str) -> dict[str, list[str]]:
    from urllib.parse import parse_qs, urlparse

    parsed = urlparse(url)
    assert parsed.netloc == "openlibrary.org"
    assert parsed.path == "/search.json"
    return parse_qs(parsed.query)


@pytest.mark.unit
def test_search_sends_title_author_limit_and_fields() -> None:
    # TSEARCH-01: title + primary author, at most 5 results, only used fields.
    spy = _Spy([_search_body()])
    client = OpenLibraryClient(http_get=spy, retries=0)

    client.search_works("The Hobbit", None)

    query = _query(spy.calls[0][0])
    assert query["title"] == ["The Hobbit"]
    assert "author" not in query
    assert query["limit"] == ["5"]
    assert query["fields"] == ["key,title,author_name,cover_i"]


_HOBBIT = {
    "key": "/works/OL262758W",
    "title": "The Hobbit",
    "author_name": ["J.R.R. Tolkien"],
    "cover_i": 14627509,
}


@pytest.mark.unit
def test_search_maps_docs_to_candidates_with_id_cover_url() -> None:
    # TSEARCH-03 input: work key, title, authors and the id-form cover URL.
    spy = _Spy([_search_body(_HOBBIT, {"key": "/works/OL2W", "title": "Other"})])
    client = OpenLibraryClient(http_get=spy)

    candidates = client.search_works("The Hobbit", "J. R. R. Tolkien")

    assert candidates == [
        SearchCandidate(
            work_key="/works/OL262758W",
            title="The Hobbit",
            authors=["J.R.R. Tolkien"],
            cover_url="https://covers.openlibrary.org/b/id/14627509-L.jpg",
        ),
        SearchCandidate(
            work_key="/works/OL2W", title="Other", authors=[], cover_url=None
        ),
    ]
    assert _query(spy.calls[0][0])["author"] == ["J. R. R. Tolkien"]


@pytest.mark.unit
def test_search_retries_title_only_when_author_query_finds_nothing() -> None:
    # TSEARCH-01 / A7: no result with the author -> one retry without it.
    spy = _Spy([_search_body(), _search_body(_HOBBIT)])
    client = OpenLibraryClient(http_get=spy)

    candidates = client.search_works("The Hobbit", "Tolkien")

    assert [c.work_key for c in candidates] == ["/works/OL262758W"]
    assert len(spy.calls) == 2
    assert "author" in _query(spy.calls[0][0])
    assert "author" not in _query(spy.calls[1][0])


@pytest.mark.unit
def test_search_without_author_never_retries() -> None:
    # TSEARCH-01: the title-only retry exists only when an author was sent.
    spy = _Spy([_search_body()])
    client = OpenLibraryClient(http_get=spy)

    assert client.search_works("Nothing Here", None) == []
    assert len(spy.calls) == 1


@pytest.mark.unit
def test_search_unparseable_body_raises_source_error() -> None:
    # TSEARCH-07: a search transport/parse failure is a source error.
    spy = _Spy([b"<html>not json</html>"])
    client = OpenLibraryClient(http_get=spy)

    with pytest.raises(EnrichmentSourceError):
        client.search_works("The Hobbit", None)


@pytest.mark.unit
def test_fetch_work_description_flattens_value_object() -> None:
    # TSEARCH-03 input: the work's description (string-or-{value} shape).
    spy = _Spy([b'{"description": {"type": "/type/text", "value": "A hobbit."}}'])
    client = OpenLibraryClient(http_get=spy)

    assert client.fetch_work_description("/works/OL262758W") == "A hobbit."
    assert spy.calls[0][0] == "https://openlibrary.org/works/OL262758W.json"


@pytest.mark.unit
def test_fetch_work_description_failure_is_none_not_an_error() -> None:
    # TSEARCH-07: a failed description fetch is non-fatal.
    spy = _Spy([EnrichmentSourceError("down"), EnrichmentSourceError("down")])
    client = OpenLibraryClient(http_get=spy)

    assert client.fetch_work_description("/works/OL1W") is None


# ---------------------------------------------- AD-032: request pacing (1 req/s)


class _FakeClock:
    """A controllable monotonic clock; ``sleep`` advances it and records waits."""

    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(round(seconds, 6))
        self.now += seconds


@pytest.mark.unit
def test_pacing_first_request_never_waits() -> None:
    time = _FakeClock()
    client = OpenLibraryClient(
        http_get=_Spy([b"{}"]), min_interval=1.0, sleep=time.sleep, clock=time.clock
    )

    client._fetch("https://openlibrary.org/a")

    assert time.slept == []


@pytest.mark.unit
def test_pacing_waits_only_the_remainder_of_the_interval() -> None:
    # Open Library documents 1 request/second for unidentified clients.
    time = _FakeClock()
    client = OpenLibraryClient(
        http_get=_Spy([b"{}", b"{}"]),
        min_interval=1.0,
        sleep=time.sleep,
        clock=time.clock,
    )

    client._fetch("https://openlibrary.org/a")
    time.now += 0.3
    client._fetch("https://openlibrary.org/b")

    assert time.slept == [0.7]


@pytest.mark.unit
def test_pacing_no_wait_once_the_interval_has_passed() -> None:
    time = _FakeClock()
    client = OpenLibraryClient(
        http_get=_Spy([b"{}", b"{}"]),
        min_interval=1.0,
        sleep=time.sleep,
        clock=time.clock,
    )

    client._fetch("https://openlibrary.org/a")
    time.now += 2.0
    client._fetch("https://openlibrary.org/b")

    assert time.slept == []


@pytest.mark.unit
def test_pacing_applies_to_retries_too() -> None:
    # A retry is a request: it must not burst right after the failed attempt.
    time = _FakeClock()
    client = OpenLibraryClient(
        http_get=_Spy([EnrichmentSourceError("blip"), b"{}"]),
        min_interval=1.0,
        sleep=time.sleep,
        clock=time.clock,
    )

    client._fetch("https://openlibrary.org/a")

    assert time.slept == [1.0]


@pytest.mark.unit
def test_pacing_defaults_to_one_second_for_the_real_transport() -> None:
    assert OpenLibraryClient()._min_interval == 1.0
    assert OpenLibraryClient(http_get=_Spy([]))._min_interval == 0.0
