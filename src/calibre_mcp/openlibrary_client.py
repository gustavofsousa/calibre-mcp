"""The single outbound-HTTP call site — Open Library enrichment (ENRICH-01, AD-026).

Confines all network I/O + cover download for identifier-based metadata lookup to
one sibling module, the way ``calibredb_runner``/``folder_scan`` confine their own
I/O kinds (AD-014/AD-021): the facade orchestrates, this module performs the GETs.
Every transport/HTTP/parse failure maps to ``EnrichmentSourceError`` (LOOKUP-08),
and every request is bounded by a timeout + at most one retry (LOOKUP-10).
"""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from .errors import EnrichmentSourceError

# Descriptive User-Agent so Open Library can attribute traffic (LOOKUP-10).
_DEFAULT_UA = "calibre-mcp/enrich (+https://github.com/gustavofsousa/calibre-mcp)"

# The injectable transport seam: url + timeout -> raw bytes. Tests feed a fake so
# no test ever touches the real network (spec test-safety rule).
HttpGet = Callable[[str, float], bytes]


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


class OpenLibraryClient:
    """Fetches metadata + covers from Open Library over a bounded, retrying seam."""

    def __init__(
        self,
        *,
        http_get: HttpGet | None = None,
        timeout: float = 10.0,
        retries: int = 1,
        user_agent: str = _DEFAULT_UA,
    ) -> None:
        self._timeout = timeout
        self._retries = retries
        self._user_agent = user_agent
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
        recent error is re-raised (never a silent failure).
        """
        last_error: EnrichmentSourceError | None = None
        for _ in range(self._retries + 1):
            try:
                return self._http_get(url, self._timeout)
            except EnrichmentSourceError as exc:
                last_error = exc
        assert last_error is not None  # the loop body always runs at least once
        raise last_error
