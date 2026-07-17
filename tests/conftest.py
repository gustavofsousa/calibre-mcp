"""Shared pytest fixtures.

Test-safety rule (non-negotiable): writes must NEVER touch the user's real
library. Write tests use the ``scratch_library`` fixture, which bootstraps an
empty Calibre library in a temp dir. Read-only tests may use ``real_library``,
which points at the real library and skips cleanly when it is absent.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REAL_LIBRARY_PATH = Path("/home/gustavo/Documents/BibliotecaCalibre")


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
    """Point at the real Calibre library, read-only; skip cleanly if absent."""
    if shutil.which("calibredb") is None:
        pytest.skip("calibredb not on PATH")
    if not (REAL_LIBRARY_PATH / "metadata.db").exists():
        pytest.skip(f"real library not found at {REAL_LIBRARY_PATH}")
    return REAL_LIBRARY_PATH
