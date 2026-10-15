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
import struct
import subprocess
import tempfile
import zlib
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


def write_cover_png(path: Path, width: int = 100, height: int = 150) -> Path:
    """Write a real WxH PNG (stdlib only) usable as a Calibre cover.

    Calibre's Qt rejects a degenerate 1x1 image ("Image is empty"), so this
    emits a proper white image.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return path
