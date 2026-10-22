"""Synthetic sample ebooks for tests that need a real file to import.

Built with Calibre's own ``ebook-convert`` — present wherever ``calibredb`` is,
including CI — so the write path is exercised without depending on anyone's
personal library. Before this existed, tests copied .epub files out of a
hard-coded personal library path; when that library moved (or in CI, where it
never existed) ~180 write-path tests skipped silently while the suite stayed
green.

Each sample has its own title, author and bytes, so seeding two of them never
trips calibredb's duplicate check.
"""

from __future__ import annotations

import atexit
import functools
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

SAMPLE_COUNT = 4


@functools.cache
def _samples_dir() -> Path:
    path = Path(tempfile.mkdtemp(prefix="calibre-mcp-samples-"))
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


@functools.cache
def _build_sample_epub(index: int) -> Path:
    source = _samples_dir() / f"sample-{index}.txt"
    source.write_text(
        f"Sample Book {index}\n\nThe only chapter of sample book {index}.\n",
        encoding="utf-8",
    )
    dest = _samples_dir() / f"sample-{index}.epub"
    result = subprocess.run(
        [
            "ebook-convert",
            str(source),
            str(dest),
            "--title",
            f"Sample Book {index}",
            "--authors",
            f"Sample Author {index}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(f"ebook-convert could not build a sample epub: {result.stderr}")
    return dest


def sample_epub_sources() -> list[Path]:
    """Return ``SAMPLE_COUNT`` distinct sample .epub files (built once per run).

    Skips the calling test when ``ebook-convert`` is not installed — the same
    environments where ``scratch_library`` already skips for lack of calibredb.
    """
    if shutil.which("ebook-convert") is None:
        pytest.skip("ebook-convert not on PATH")
    return [_build_sample_epub(index) for index in range(SAMPLE_COUNT)]
