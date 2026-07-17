"""Integration tests for CalibreLibrary facade P2 additions (T7-T9).

Derived from spec ACs (CONV-01, ORG-01, EMAIL-01), asserting spec-defined
outcomes. ALL writes go to a per-test ``scratch_library`` (temp dir) — they
NEVER touch the real library (the non-negotiable test-safety rule).

ORG-01 AC-1/2/3: find_duplicates groups (>=2) by normalized (title, author);
  read-only, never mutates; no duplicates -> empty group set.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
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
