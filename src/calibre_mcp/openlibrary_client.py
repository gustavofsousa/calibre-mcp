"""The single outbound-HTTP call site — Open Library enrichment (ENRICH-01, AD-026).

Confines all network I/O + cover download for identifier-based metadata lookup to
one sibling module, the way ``calibredb_runner``/``folder_scan`` confine their own
I/O kinds (AD-014/AD-021): the facade orchestrates, this module performs the GETs.
Every transport/HTTP/parse failure maps to ``EnrichmentSourceError`` (LOOKUP-08),
and every request is bounded by a timeout + at most one retry (LOOKUP-10).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import EnrichmentSourceError

# Open Library endpoints (verified live 2026-07-31, design §Research notes):
# the structured Books API for publisher/pubdate/cover, then the edition->work
# hop for the description (the 71%-gap field the Books API omits, LOOKUP-04).
_BOOKS_API = "https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
_EDITION_URL = "https://openlibrary.org/isbn/{isbn}.json"
_WORK_URL = "https://openlibrary.org{work_key}.json"
# Title/author search (ENRICH-04): only the fields the matcher and the proposal
# use, so responses stay cheap (the docs warn `fields=*` is expensive).
_SEARCH_URL = "https://openlibrary.org/search.json?{query}"
_SEARCH_FIELDS = "key,title,author_name,cover_i"
_SEARCH_LIMIT = 5
_COVER_ID_URL = "https://covers.openlibrary.org/b/id/{cover_id}-L.jpg"

# SECURITY: the cover URL and the work key come from Open Library's response, so
# every fetched URL must be HTTPS on one of these hosts. Without the check a
# ``file://`` cover URL reads a local file, and a work key like ``@host/x`` sends
# the request to another host.
_ALLOWED_HOSTS = frozenset({"openlibrary.org", "covers.openlibrary.org"})

# Descriptive User-Agent so Open Library can attribute traffic (LOOKUP-10).
_DEFAULT_UA = "calibre-mcp/enrich (+https://github.com/gustavofsousa/calibre-mcp)"

# The injectable transport seam: url + timeout -> raw bytes. Tests feed a fake so
# no test ever touches the real network (spec test-safety rule).
HttpGet = Callable[[str, float], bytes]

# Open Library's documented limit for unidentified clients is 1 request/second
# (https://openlibrary.org/developers/api); a batch sweep must not burst past it.
_REAL_TRANSPORT_MIN_INTERVAL = 1.0


@dataclass(frozen=True)
class OpenLibraryRecord:
    """One Open Library record's enrichment-relevant fields (design §Data Models).

    ``pubdate`` is the raw ``publish_date`` string (no coercion — that is the apply
    step, ENRICH-02); ``description`` comes from the work record (LOOKUP-04);
    ``cover_url`` is the non-rate-limited cover-id URL (design Research notes).
    """

    publisher: str | None
    pubdate: str | None
    description: str | None
    cover_url: str | None


@dataclass(frozen=True)
class SearchCandidate:
    """One work returned by Open Library's title/author search (ENRICH-04).

    Work-level only: ``work_key`` (``/works/OL…W``) leads to the description,
    ``cover_url`` is the id-form cover URL (not rate-limited, AD-026).
    """

    work_key: str
    title: str
    authors: list[str]
    cover_url: str | None


class OpenLibraryClient:
    """Fetches metadata + covers from Open Library over a bounded, retrying seam."""

    def __init__(
        self,
        *,
        http_get: HttpGet | None = None,
        timeout: float = 10.0,
        retries: int = 1,
        user_agent: str = _DEFAULT_UA,
        min_interval: float | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._timeout = timeout
        self._retries = retries
        self._user_agent = user_agent
        # Pacing protects the real API; an injected transport (tests) has no
        # remote to protect, so it is unpaced unless a test asks for pacing.
        if min_interval is None:
            min_interval = _REAL_TRANSPORT_MIN_INTERVAL if http_get is None else 0.0
        self._min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last_request_at: float | None = None
        # Default to the real urllib transport; the None sentinel lets that default
        # bind to this instance's user_agent while keeping the seam 2-arg.
        self._http_get: HttpGet = http_get if http_get is not None else self._urllib_get

    def _urllib_get(self, url: str, timeout: float) -> bytes:
        """The only real ``urllib.request.urlopen`` call site (LOOKUP-08/10).

        Sets a descriptive ``User-Agent`` and wraps every transport failure —
        HTTP >= 400, unreachable host, or timeout — into ``EnrichmentSourceError``
        so no raw ``urllib`` error escapes this module. (In Python 3.10+
        ``socket.timeout`` is an alias of ``TimeoutError``.)
        """
        request = urllib.request.Request(url, headers={"User-Agent": self._user_agent})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data: bytes = response.read()
                return data
        except urllib.error.HTTPError as exc:
            raise EnrichmentSourceError(f"HTTP {exc.code}", url) from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            raise EnrichmentSourceError(str(reason), url) from exc

    def _fetch(self, url: str) -> bytes:
        """GET ``url`` via the seam, retrying at most ``retries`` times (LOOKUP-10).

        Retries only on ``EnrichmentSourceError``; after the last attempt the most
        recent error is re-raised (never a silent failure). A URL off the Open
        Library hosts is refused before any request.
        """
        self._require_allowed_url(url)
        last_error: EnrichmentSourceError | None = None
        for _ in range(self._retries + 1):
            self._wait_for_turn()
            try:
                return self._http_get(url, self._timeout)
            except EnrichmentSourceError as exc:
                last_error = exc
        assert last_error is not None  # the loop body always runs at least once
        raise last_error

    def fetch_record(self, isbn: str) -> OpenLibraryRecord | None:
        """Fetch Open Library metadata for ``isbn`` (LOOKUP-04/07/08).

        One GET to the Books API for publisher / raw ``publish_date`` / cover-id
        URL; when that structured record carries no description, a best-effort
        edition->work follow-up supplies it (LOOKUP-04). A clean empty response
        (the ISBN is unknown) returns ``None`` (LOOKUP-07); an unparseable Books
        API body raises ``EnrichmentSourceError`` (LOOKUP-08). A failed
        description follow-up is non-fatal: publisher/pubdate are still returned.
        """
        books_url = _BOOKS_API.format(isbn=isbn)
        entry = self._parse_json(self._fetch(books_url), books_url).get(f"ISBN:{isbn}")
        if not entry:
            return None  # clean not-found (LOOKUP-07)

        description = self._flatten_description(entry.get("description"))
        if description is None:
            description = self._fetch_work_description(isbn)  # non-fatal (LOOKUP-04)
        return OpenLibraryRecord(
            publisher=self._first_publisher(entry),
            pubdate=entry.get("publish_date"),
            description=description,
            cover_url=self._cover_id_url(entry),
        )

    def download_cover(self, cover_url: str, dest_dir: Path | None = None) -> Path:
        """Download the cover image to a surviving temp file (LOOKUP-06/09).

        The bytes are fetched first, so a transport failure raises
        ``EnrichmentSourceError`` before any file is created — never a partial or
        zero-byte file left as a valid result. On success the bytes are written to
        a uniquely-named file (prefix ``calibre-mcp-enrich-``) under ``dest_dir``
        (or the system temp dir); the file is NOT auto-cleaned, so it survives the
        call for COVER-02 to consume. The caller owns the returned path.
        """
        data = self._fetch(cover_url)  # raises before any file exists (LOOKUP-09)
        suffix = Path(urllib.parse.urlparse(cover_url).path).suffix
        directory = str(dest_dir) if dest_dir is not None else None
        fd, temp_path = tempfile.mkstemp(
            prefix="calibre-mcp-enrich-", suffix=suffix, dir=directory
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
        except OSError as exc:
            os.unlink(temp_path)  # never leave a partial file behind
            reason = f"could not write cover: {exc}"
            raise EnrichmentSourceError(reason, cover_url) from exc
        return Path(temp_path)

    def _wait_for_turn(self) -> None:
        """Sleep just long enough to keep >= ``min_interval`` between requests."""
        now = self._clock()
        if self._last_request_at is not None:
            remaining = self._min_interval - (now - self._last_request_at)
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._last_request_at = now

    def search_works(self, title: str, author: str | None) -> list[SearchCandidate]:
        """Search Open Library works by title (+ author) (ENRICH-04, TSEARCH-01).

        At most ``_SEARCH_LIMIT`` candidates, in Open Library's own order. When
        a query that included ``author`` finds nothing, one retry with the title
        alone: catalogs spell authors differently ("Papa Francisco" vs "Pope
        Francis"), and the matcher still checks the author afterwards. A
        transport/parse failure raises ``EnrichmentSourceError`` (TSEARCH-07).
        """
        candidates = self._search(title, author)
        if not candidates and author is not None:
            candidates = self._search(title, None)
        return candidates

    def fetch_work_description(self, work_key: str) -> str | None:
        """The work's description, or ``None`` on any failure (best-effort).

        A failed description must never lose the rest of a proposal (TSEARCH-07,
        LOOKUP-04), so transport, parse and shape problems all yield ``None``.
        """
        try:
            work = self._parse_json(
                self._fetch(_WORK_URL.format(work_key=work_key)), ""
            )
        except EnrichmentSourceError:
            return None
        return self._flatten_description(work.get("description"))

    def _search(self, title: str, author: str | None) -> list[SearchCandidate]:
        params = {"title": title}
        if author is not None:
            params["author"] = author
        params["limit"] = str(_SEARCH_LIMIT)
        params["fields"] = _SEARCH_FIELDS
        url = _SEARCH_URL.format(query=urllib.parse.urlencode(params))
        docs = self._parse_json(self._fetch(url), url).get("docs")
        if not isinstance(docs, list):
            return []
        return [
            candidate
            for doc in docs[:_SEARCH_LIMIT]
            if (candidate := self._to_candidate(doc)) is not None
        ]

    @staticmethod
    def _to_candidate(doc: object) -> SearchCandidate | None:
        if not isinstance(doc, dict):
            return None
        key, title = doc.get("key"), doc.get("title")
        if not isinstance(key, str) or not key or not isinstance(title, str):
            return None
        names = doc.get("author_name")
        authors = (
            [n for n in names if isinstance(n, str)] if isinstance(names, list) else []
        )
        cover_id = doc.get("cover_i")
        cover_url = (
            _COVER_ID_URL.format(cover_id=cover_id)
            if isinstance(cover_id, int)
            else None
        )
        return SearchCandidate(
            work_key=key, title=title, authors=authors, cover_url=cover_url
        )

    def _fetch_work_description(self, isbn: str) -> str | None:
        """Follow edition->work for the description; any failure -> ``None``.

        Best-effort by design (a failed description follow-up must not lose the
        core metadata proposal): a transport, parse, or shape problem anywhere
        along the hop simply yields ``None``.
        """
        try:
            edition = self._parse_json(self._fetch(_EDITION_URL.format(isbn=isbn)), "")
        except EnrichmentSourceError:
            return None
        works = edition.get("works")
        if not isinstance(works, list) or not works:
            return None
        work_key = works[0].get("key") if isinstance(works[0], dict) else None
        if not isinstance(work_key, str) or not work_key:
            return None
        return self.fetch_work_description(work_key)

    @staticmethod
    def _require_allowed_url(url: str) -> None:
        """Refuse a URL that is not HTTPS on an Open Library host."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_HOSTS:
            raise EnrichmentSourceError("refused URL outside Open Library", url)

    @staticmethod
    def _parse_json(raw: bytes, url: str) -> dict[str, Any]:
        """Decode a JSON object; a non-object/undecodable body is a source error."""
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise EnrichmentSourceError(f"unparseable response: {exc}", url) from exc
        if not isinstance(value, dict):
            raise EnrichmentSourceError("unexpected non-object response", url)
        return value

    @staticmethod
    def _flatten_description(description: object) -> str | None:
        """Normalize Open Library's string-or-``{"value": ...}`` description shape."""
        if isinstance(description, str):
            return description or None
        if isinstance(description, dict):
            value = description.get("value")
            return value if isinstance(value, str) and value else None
        return None

    @staticmethod
    def _first_publisher(entry: dict[str, Any]) -> str | None:
        """First publisher name from the Books API ``publishers:[{name}]`` list."""
        publishers = entry.get("publishers")
        if isinstance(publishers, list) and publishers:
            first = publishers[0]
            name = first.get("name") if isinstance(first, dict) else None
            return name if isinstance(name, str) and name else None
        return None

    @staticmethod
    def _cover_id_url(entry: dict[str, Any]) -> str | None:
        """Largest available cover URL from the Books API ``cover`` object.

        Those URLs are the cover-**id** form (``.../b/id/<id>-<S|M|L>.jpg``),
        which is not rate-limited (design Research notes) — prefer the largest.
        """
        cover = entry.get("cover")
        if not isinstance(cover, dict):
            return None
        for size in ("large", "medium", "small"):
            url = cover.get(size)
            if isinstance(url, str) and url:
                return url
        return None
