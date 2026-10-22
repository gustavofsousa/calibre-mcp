"""Unit tests for the batch status of one enrichment result (ENRICH3-02/03).

A result is ``proposed`` only when it has something the host can apply: a
non-empty ``proposed`` or a downloaded cover. A cover whose download failed has
``local_path: null`` and ``set_cover`` cannot take it.
"""

from __future__ import annotations

import pytest

from calibre_mcp.library import CalibreLibrary


@pytest.mark.unit
def test_failed_cover_download_alone_is_no_new_data() -> None:
    payload = {
        "found": True,
        "proposed": {},
        "cover": {"url": "https://covers.openlibrary.org/b/id/1-L.jpg",
                  "local_path": None, "error": "HTTP 503"},
    }
    assert CalibreLibrary._classify_enrichment(payload) == "no_new_data"


@pytest.mark.unit
def test_downloaded_cover_alone_is_proposed() -> None:
    payload = {
        "found": True,
        "proposed": {},
        "cover": {"url": "https://covers.openlibrary.org/b/id/1-L.jpg",
                  "local_path": "/tmp/calibre-mcp-enrich-1.jpg"},
    }
    assert CalibreLibrary._classify_enrichment(payload) == "proposed"


@pytest.mark.unit
def test_fields_with_failed_cover_are_proposed() -> None:
    payload = {
        "found": True,
        "proposed": {"publisher": "Pub"},
        "cover": {"url": "https://covers.openlibrary.org/b/id/1-L.jpg",
                  "local_path": None, "error": "HTTP 503"},
    }
    assert CalibreLibrary._classify_enrichment(payload) == "proposed"
