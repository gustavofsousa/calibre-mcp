"""Shared pytest fixtures.

Test-safety rule (non-negotiable): writes must NEVER touch the user's real
library. Write tests use the ``scratch_library`` fixture, which bootstraps an
empty Calibre library in a temp dir. Read-only tests may use ``real_library``,
an opt-in pointer at a real library (``CALIBRE_MCP_TEST_REAL_LIBRARY``) that
skips cleanly when unset or absent.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REAL_LIBRARY_ENV = "CALIBRE_MCP_TEST_REAL_LIBRARY"


@pytest.fixture
def scratch_library(tmp_path: Path) -> Path:
    """Bootstrap an EMPTY Calibre library in a temp dir and yield its path.

    Running any ``calibredb`` command with ``--with-library <empty-dir>``
    creates a fresh ``metadata.db``. The temp dir is removed by pytest's
    ``tmp_path`` teardown, guaranteeing writes never reach the real library.
    """
    library_path = Path(tmp_path) / "scratch-library"
    library_path.mkdir()

    result = subprocess.run(
        ["calibredb", "list", "--with-library", str(library_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"could not bootstrap scratch library: {result.stderr.strip()}")

    if not (library_path / "metadata.db").exists():
        pytest.skip("calibredb did not create metadata.db in the scratch library")

    return library_path


@pytest.fixture
def real_library() -> Path:
    """Point at a real Calibre library, read-only; skip cleanly if absent.

    Opt-in via ``CALIBRE_MCP_TEST_REAL_LIBRARY`` rather than a hard-coded path:
    a personal path silently skips these tests for every other contributor and
    in CI, and goes stale the moment the library moves.
    """
    if shutil.which("calibredb") is None:
        pytest.skip("calibredb not on PATH")
    raw_path = os.environ.get(REAL_LIBRARY_ENV)
    if not raw_path:
        pytest.skip(f"{REAL_LIBRARY_ENV} is unset")
    library_path = Path(raw_path)
    if not (library_path / "metadata.db").exists():
        pytest.skip(f"real library not found at {library_path}")
    return library_path
