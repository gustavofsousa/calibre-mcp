"""Integration tests for the CalibreLibrary facade — read_cover (COVER-01, T2).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library.

RCOVER-01: covered book -> {has_cover: True, cover_path: <str>}.
RCOVER-02: uncovered book -> {has_cover: False, cover_path: None}, not an error.
RCOVER-03: unknown id -> BookNotFoundError naming the id.
RCOVER-05: read_cover never writes -- no metadata.db backup, under any outcome.
"""

from __future__ import annotations

import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import BookNotFoundError
from calibre_mcp.library import CalibreLibrary


def _valid_cover_png(path: Path, width: int = 100, height: int = 150) -> Path:
    """Write a real, multi-pixel PNG using only stdlib zlib/struct.

    Calibre re-encodes any valid input image to ``cover.jpg`` on
    ``set_metadata --field cover:``. A degenerate 1x1 PNG is rejected by Qt
    ("Image is empty"), so this emits a real WxH white image.
    """

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    row = b"\x00" + b"\xff\xff\xff" * width  # filter byte + white pixels
    idat = zlib.compress(row * height)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def _seed_empty_book(scratch_library: Path, title: str = "Empty") -> int:
    # calibredb add --empty has no CalibredbRunner wrapper (adds no format /
    # embedded cover) -- needed so an "uncovered" book is deterministic.
    result = subprocess.run(
        [
            "calibredb",
            "add",
            "--empty",
            "--title",
            title,
            "--with-library",
            str(scratch_library),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    match = re.search(
        r"Added book ids:\s*([\d,]+)", f"{result.stdout}\n{result.stderr}"
    )
    assert match is not None
    return int(match.group(1).split(",")[0])


def _seed_covered_book(scratch_library: Path, tmp_path: Path) -> int:
    book_id = _seed_empty_book(scratch_library, "Covered")
    cover_png = _valid_cover_png(tmp_path / "cover-source.png")
    CalibredbRunner(scratch_library).set_metadata(book_id, {"cover": str(cover_png)})
    return book_id


@pytest.fixture
def backup_root(tmp_path: Path) -> Path:
    # A backup root OUTSIDE the library dir so it starts empty and is isolated.
    return tmp_path / "backups"


@pytest.fixture
def config(scratch_library: Path, backup_root: Path) -> Config:
    return Config(
        library_path=scratch_library,
        db_path=scratch_library / "metadata.db",
        backup_root=backup_root,
    )


@pytest.fixture
def facade(config: Config) -> CalibreLibrary:
    return CalibreLibrary(config)


@pytest.mark.integration
def test_read_cover_covered_book_returns_has_cover_true_and_path(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # RCOVER-01: cover present -> has_cover True + a resolved cover_path string.
    book_id = _seed_covered_book(scratch_library, tmp_path)

    result = facade.read_cover(book_id)

    assert result == {
        "book_id": book_id,
        "has_cover": True,
        "cover_path": result["cover_path"],
    }
    assert result["cover_path"] is not None
    assert Path(result["cover_path"]).name == "cover.jpg"


@pytest.mark.integration
def test_read_cover_uncovered_book_returns_has_cover_false_and_null_path(
    facade: CalibreLibrary, scratch_library: Path
):
    # RCOVER-02: no cover -> a normal structured result, not an error.
    book_id = _seed_empty_book(scratch_library)

    result = facade.read_cover(book_id)

    assert result == {"book_id": book_id, "has_cover": False, "cover_path": None}


@pytest.mark.integration
def test_read_cover_unknown_book_raises_not_found(facade: CalibreLibrary):
    # RCOVER-03: unknown id -> BookNotFoundError naming the id.
    with pytest.raises(BookNotFoundError) as excinfo:
        facade.read_cover(999999)

    assert excinfo.value.book_id == 999999


@pytest.mark.integration
def test_read_cover_never_creates_a_metadata_db_backup(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # RCOVER-05: pure read -- no metadata.db backup under any outcome
    # (covered, uncovered, unknown id).
    covered_id = _seed_covered_book(scratch_library, tmp_path)
    uncovered_id = _seed_empty_book(scratch_library, "Uncovered")

    facade.read_cover(covered_id)
    facade.read_cover(uncovered_id)
    with pytest.raises(BookNotFoundError):
        facade.read_cover(999999)

    assert not backup_root.exists()
