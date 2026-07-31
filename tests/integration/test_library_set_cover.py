"""Integration tests for the CalibreLibrary facade — set_cover (COVER-02, T1).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library.

SCOVER-01: plan (no token) -> current_has_cover, new_cover, token; no write.
SCOVER-02: missing/not-a-file image_path -> InvalidInputError before backup.
SCOVER-03: non-image extension -> InvalidInputError before backup.
SCOVER-04: unknown book_id -> BookNotFoundError before backup.
SCOVER-05: apply -> one backup before write, cover set, re-read demonstrates.
SCOVER-06: token mismatch -> ConfirmationError, no write.
SCOVER-07: book already has a cover -> plan current_has_cover True, apply replaces.
L-001:     backup runs before the calibredb write (monkeypatch call-order proof).

SPEC_DEVIATION: design.md's Risks table assumes an "undecodable image" apply
would have calibredb silently no-op (re-read reporting has_cover: false).
Empirically verified 2026-07-31 (probed directly against calibredb): a file
with a valid extension but content calibredb cannot decode (garbage bytes, or
a zero-byte file) makes calibredb crash with a non-zero exit -- it raises,
it does not silently no-op. Only a MISSING path (SCOVER-02, guarded before
any calibredb call) is silent. So the accurate "no fake success" proof for a
decode failure is that CalibredbError propagates -- see
test_set_cover_calibredb_decode_failure_propagates_not_a_fake_success below,
which replaces the design's assumed has_cover:false scenario with the real
one (an even stronger guarantee: a loud failure, never a silent wrong result).
"""

from __future__ import annotations

import re
import struct
import subprocess
import zlib
from pathlib import Path

import pytest

from calibre_mcp import library as library_module
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import (
    BookNotFoundError,
    CalibredbError,
    ConfirmationError,
    InvalidInputError,
)
from calibre_mcp.library import CalibreLibrary


def _valid_cover_png(path: Path, width: int = 100, height: int = 150) -> Path:
    """Write a real, multi-pixel PNG using only stdlib zlib/struct."""

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


def _snapshots(backup_root: Path) -> list[Path]:
    if not backup_root.exists():
        return []
    return list(backup_root.glob("metadata-*.db"))


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


# ---------------------------------------------------------------- SCOVER-01


@pytest.mark.integration
def test_set_cover_plan_returns_current_false_and_token_without_writing(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # SCOVER-01: no token -> plan with current_has_cover False + resolved
    # new_cover + token; nothing written, no backup.
    book_id = _seed_empty_book(scratch_library)
    image = _valid_cover_png(tmp_path / "cover.png")

    plan = facade.set_cover(book_id, str(image))

    assert plan == {
        "status": "plan",
        "book_id": book_id,
        "current_has_cover": False,
        "new_cover": str(image),
        "confirmation_token": plan["confirmation_token"],
    }
    assert plan["confirmation_token"]
    assert facade.read_cover(book_id)["has_cover"] is False
    assert _snapshots(backup_root) == []


# ---------------------------------------------------------------- SCOVER-05


@pytest.mark.integration
def test_set_cover_apply_round_trip_sets_cover_with_one_backup(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # SCOVER-05: apply with the matching token -> has_cover flips True,
    # cover_path is the on-disk cover.jpg, exactly one metadata.db backup.
    book_id = _seed_empty_book(scratch_library)
    image = _valid_cover_png(tmp_path / "cover.png")
    plan = facade.set_cover(book_id, str(image))

    applied = facade.set_cover(
        book_id, str(image), token=plan["confirmation_token"]
    )

    assert applied["status"] == "applied"
    assert applied["book_id"] == book_id
    assert applied["has_cover"] is True
    assert applied["cover_path"] is not None
    assert Path(applied["cover_path"]).name == "cover.jpg"
    assert Path(applied["cover_path"]).is_file()
    assert len(_snapshots(backup_root)) == 1
    assert applied["backup"] == str(_snapshots(backup_root)[0])


# ---------------------------------------------------------------- SCOVER-02


@pytest.mark.integration
def test_set_cover_missing_path_rejected_before_backup(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # SCOVER-02: a nonexistent image_path is rejected BEFORE any backup --
    # calibredb would otherwise silently no-op on it (design footgun).
    book_id = _seed_empty_book(scratch_library)
    missing = tmp_path / "does-not-exist.png"

    with pytest.raises(InvalidInputError):
        facade.set_cover(book_id, str(missing))

    assert _snapshots(backup_root) == []
    assert facade.read_cover(book_id)["has_cover"] is False


# ---------------------------------------------------------------- SCOVER-03


@pytest.mark.integration
def test_set_cover_non_image_extension_rejected_before_backup(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # SCOVER-03: an existing file with an unsupported extension is rejected
    # before any backup/write.
    book_id = _seed_empty_book(scratch_library)
    not_an_image = tmp_path / "notes.txt"
    not_an_image.write_text("not an image")

    with pytest.raises(InvalidInputError):
        facade.set_cover(book_id, str(not_an_image))

    assert _snapshots(backup_root) == []
    assert facade.read_cover(book_id)["has_cover"] is False


# ---------------------------------------------------------------- SCOVER-04


@pytest.mark.integration
def test_set_cover_unknown_book_id_raises_not_found(
    facade: CalibreLibrary, tmp_path: Path
):
    # SCOVER-04: an unknown book id is rejected before any backup/write.
    image = _valid_cover_png(tmp_path / "cover.png")

    with pytest.raises(BookNotFoundError) as excinfo:
        facade.set_cover(999999, str(image))

    assert excinfo.value.book_id == 999999


# ---------------------------------------------------------------- SCOVER-06


@pytest.mark.integration
def test_set_cover_token_mismatch_refused_no_write(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # SCOVER-06: a wrong token is refused; nothing is written.
    book_id = _seed_empty_book(scratch_library)
    image = _valid_cover_png(tmp_path / "cover.png")
    facade.set_cover(book_id, str(image))  # establish a real plan/token exists

    with pytest.raises(ConfirmationError):
        facade.set_cover(book_id, str(image), token="wrong-token")

    assert _snapshots(backup_root) == []
    assert facade.read_cover(book_id)["has_cover"] is False


# ---------------------------------------------------------------- SCOVER-07


@pytest.mark.integration
def test_set_cover_replace_existing_cover_plan_true_apply_overwrites(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # SCOVER-07: a book that already has a cover -> plan shows
    # current_has_cover True; apply proceeds (replace), not rejected.
    book_id = _seed_covered_book(scratch_library, tmp_path)
    old_cover_bytes = (
        Path(facade.read_cover(book_id)["cover_path"]).read_bytes()
    )
    new_image = _valid_cover_png(tmp_path / "replacement.png", width=60, height=90)

    plan = facade.set_cover(book_id, str(new_image))
    assert plan["current_has_cover"] is True

    applied = facade.set_cover(
        book_id, str(new_image), token=plan["confirmation_token"]
    )

    assert applied["has_cover"] is True
    new_cover_bytes = Path(applied["cover_path"]).read_bytes()
    assert new_cover_bytes != old_cover_bytes  # actually overwritten


# ------------------------------------------------------------------- L-001


@pytest.mark.integration
def test_set_cover_backup_runs_before_calibredb_write(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path, monkeypatch
):
    # L-001: if the backup step fails, the calibredb write must never run --
    # proves backup-before-write ordering, mirroring the sibling mutations.
    book_id = _seed_empty_book(scratch_library)
    image = _valid_cover_png(tmp_path / "cover.png")
    plan = facade.set_cover(book_id, str(image))

    def _must_not_run(*_a, **_k):
        raise AssertionError("calibredb set_metadata ran despite backup failure")

    def _backup_fails(*_a, **_k):
        raise OSError("cannot back up metadata.db; write aborted")

    monkeypatch.setattr(facade._runner, "set_metadata", _must_not_run)
    monkeypatch.setattr(library_module, "backup_metadata_db", _backup_fails)

    with pytest.raises(OSError):
        facade.set_cover(book_id, str(image), token=plan["confirmation_token"])

    assert facade.read_cover(book_id)["has_cover"] is False  # unchanged


# --------------------------------------------------------- decode-failure


@pytest.mark.integration
def test_set_cover_calibredb_decode_failure_propagates_not_a_fake_success(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # SEE module SPEC_DEVIATION docstring: a file that passes is_file() +
    # extension validation but calibredb cannot decode makes calibredb crash
    # (non-zero exit) rather than silently no-op -- CalibredbError propagates,
    # and the cover state is left unchanged. Never a false "applied" success.
    book_id = _seed_empty_book(scratch_library)
    undecodable = tmp_path / "garbage.png"
    undecodable.write_bytes(b"not a real png file, just garbage bytes")
    plan = facade.set_cover(book_id, str(undecodable))

    with pytest.raises(CalibredbError):
        facade.set_cover(book_id, str(undecodable), token=plan["confirmation_token"])

    assert facade.read_cover(book_id)["has_cover"] is False  # no fake success
