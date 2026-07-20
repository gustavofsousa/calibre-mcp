"""Unit tests for ``_map_resource_errors`` (STATS-01-04).

Calls the decorator directly (bypassing FastMCP's ``read_resource``, which
already wraps any exception into a generic ``ResourceError`` one layer up) so
the decorator's own exception-mapping branches are proven independently,
rather than only observed through FastMCP's outer catch-all.
"""

from __future__ import annotations

import sqlite3

import pytest
from mcp.server.fastmcp.exceptions import ResourceError

from calibre_mcp.errors import ConfigError
from calibre_mcp.server import _map_resource_errors


@pytest.mark.unit
def test_map_resource_errors_wraps_calibre_mcp_error():
    @_map_resource_errors
    def raises_config_error() -> dict:
        raise ConfigError("bad path")

    with pytest.raises(ResourceError) as excinfo:
        raises_config_error()

    assert "bad path" in str(excinfo.value)


@pytest.mark.unit
def test_map_resource_errors_wraps_sqlite_error():
    @_map_resource_errors
    def raises_sqlite_error() -> dict:
        raise sqlite3.OperationalError("unable to open database file")

    with pytest.raises(ResourceError) as excinfo:
        raises_sqlite_error()

    assert "unable to open database file" in str(excinfo.value)


@pytest.mark.unit
def test_map_resource_errors_wraps_os_error():
    @_map_resource_errors
    def raises_os_error() -> dict:
        raise OSError("permission denied")

    with pytest.raises(ResourceError) as excinfo:
        raises_os_error()

    assert "permission denied" in str(excinfo.value)


@pytest.mark.unit
def test_map_resource_errors_passes_through_success():
    @_map_resource_errors
    def returns_dict() -> dict:
        return {"ok": True}

    assert returns_dict() == {"ok": True}
