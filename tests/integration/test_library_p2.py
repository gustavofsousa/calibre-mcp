"""Integration tests for CalibreLibrary facade P2 additions (T7-T9).

Derived from spec ACs (CONV-01, ORG-01, EMAIL-01), asserting spec-defined
outcomes. ALL writes go to a per-test ``scratch_library`` (temp dir) — they
NEVER touch the real library (the non-negotiable test-safety rule).

ORG-01 AC-1/2/3: find_duplicates groups (>=2) by normalized (title, author);
  read-only, never mutates; no duplicates -> empty group set.
CONV-01 AC-1/2: convert_book converts and adds the new format, keeping the old.
CONV-01 AC-3:   refuses (no overwrite) when the target format already exists.
CONV-01 AC-4:   refuses before converting when the book has no source file.
CONV-01 AC-5/6: a convert failure surfaces stderr, adds nothing, and the
  backup happens BEFORE add_format.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import EbookConvertError, InvalidInputError
from calibre_mcp.library import CalibreLibrary

REAL_LIBRARY = Path("/home/gustavo/Documents/BibliotecaCalibre")


def _sample_epub(tmp_path: Path, name: str = "sample.epub", index: int = 0) -> Path:
    """Copy one real .epub into a temp path (reading the real library is safe)."""
    sources = list(REAL_LIBRARY.glob("**/*.epub"))
    if len(sources) <= index:
        pytest.skip("not enough distinct sample .epub files in the real library")
    dest = tmp_path / name
    shutil.copy2(sources[index], dest)
    return dest


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


def _seed_book(
    scratch_library: Path, tmp_path: Path, name: str = "seed.epub", index: int = 0
) -> int:
    """Add a book directly via the runner (no facade backup) and return its id."""
    result = CalibredbRunner(scratch_library).add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# ------------------------------------------------------------- find_duplicates


@pytest.mark.integration
def test_find_duplicates_groups_same_title_and_author(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # ORG-01 AC-1: two books with the same (title, primary author) -> one group.
    id1 = _seed_book(scratch_library, tmp_path, "one.epub", index=0)
    id2 = _seed_book(scratch_library, tmp_path, "two.epub", index=1)
    facade._runner.set_metadata(
        id1, {"title": "Same Title", "authors": ["Same Author"]}
    )
    facade._runner.set_metadata(
        id2, {"title": "Same Title", "authors": ["Same Author"]}
    )

    result = facade.find_duplicates()

    assert result["group_count"] == 1
    group = result["groups"][0]
    assert group["key"] == {"title": "Same Title", "author": "Same Author"}
    assert {b["id"] for b in group["books"]} == {id1, id2}


@pytest.mark.integration
def test_find_duplicates_no_duplicates_returns_empty_group_set(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path, backup_root: Path
):
    # ORG-01 AC-3: distinct books -> zero groups (not an error); read-only.
    id1 = _seed_book(scratch_library, tmp_path, "one.epub", index=0)
    id2 = _seed_book(scratch_library, tmp_path, "two.epub", index=1)
    facade._runner.set_metadata(id1, {"title": "Title One", "authors": ["Author One"]})
    facade._runner.set_metadata(id2, {"title": "Title Two", "authors": ["Author Two"]})

    result = facade.find_duplicates()

    assert result == {"group_count": 0, "groups": []}
    # ORG-01 AC-2: read-only, library unchanged, nothing backed up.
    assert facade.get_book(id1).title == "Title One"
    assert facade.get_book(id2).title == "Title Two"
    assert _snapshots(backup_root) == []


# --------------------------------------------------------------- convert_book


@pytest.mark.integration
def test_convert_book_adds_new_format_keeps_old(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # CONV-01 AC-1/AC-2: convert epub -> pdf; both formats present afterward.
    book_id = _seed_book(scratch_library, tmp_path)

    result = facade.convert_book(book_id, "pdf")

    assert result["status"] == "converted"
    assert set(result["book"].formats) == {"EPUB", "PDF"}
    assert set(facade.get_book(book_id).formats) == {"EPUB", "PDF"}
    assert len(_snapshots(backup_root)) == 1  # CONV-01 AC-6: backed up before write


@pytest.mark.integration
def test_convert_book_refuses_when_target_format_already_exists(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # CONV-01 AC-3: refuse (no overwrite) instead of replacing the existing file.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError) as excinfo:
        facade.convert_book(book_id, "epub")

    assert "EPUB" in str(excinfo.value)
    assert _snapshots(backup_root) == []  # refused before any write


@pytest.mark.integration
def test_convert_book_no_source_file_refuses_before_convert(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path,
    monkeypatch,
):
    # CONV-01 AC-4: no convertible source -> refuse before running ebook-convert.
    book_id = _seed_book(scratch_library, tmp_path)
    monkeypatch.setattr(facade._reader, "format_files", lambda _id: {})

    def _must_not_run(*_a, **_k):
        raise AssertionError("ebook-convert ran despite no source file")

    monkeypatch.setattr(facade._converter, "convert", _must_not_run)

    with pytest.raises(InvalidInputError) as excinfo:
        facade.convert_book(book_id, "pdf")

    assert "no file to convert from" in str(excinfo.value)
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_convert_book_bogus_source_surfaces_error_and_adds_nothing(
    facade: CalibreLibrary, scratch_library: Path, backup_root: Path, tmp_path: Path
):
    # CONV-01 AC-5: a corrupt source surfaces the convert error; no format added,
    # no false success.
    book_id = _seed_book(scratch_library, tmp_path)
    book = facade.get_book(book_id)
    epub_path = next(iter(facade._reader.format_files(book_id).values()))
    epub_path.write_bytes(b"not a real epub")

    with pytest.raises(EbookConvertError):
        facade.convert_book(book_id, "pdf")

    assert facade.get_book(book_id).formats == book.formats  # nothing added
    assert _snapshots(backup_root) == []  # no add_format ran, no backup taken


@pytest.mark.integration
def test_convert_book_unsupported_target_format_rejected(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # CONV-01: an unsupported target format is rejected before any subprocess.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError) as excinfo:
        facade.convert_book(book_id, "bogus")

    assert "bogus" in str(excinfo.value)
