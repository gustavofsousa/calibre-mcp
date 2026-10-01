"""Integration tests for ``CalibreLibrary.import_folder`` (BULK-03, T3).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Source ebooks are copied from the real
library (read-only) into a scratch SOURCE tree that is scanned/imported.

BIMPORT-01: recursive discover, whitelist, silently ignore non-ebook/hidden.
BIMPORT-02: reject non-dir / missing / over-500-candidate before any backup.
BIMPORT-03: exactly one backup before the loop, no confirmation token.
BIMPORT-04: a per-file failure lands in ``failed``, batch continues.
BIMPORT-05: a duplicate is surfaced, never re-added, never a fake id.
BIMPORT-06: an added file gets its real new id + re-read metadata.
BIMPORT-07: added + duplicate + failed == candidate count.
Edge cases: zero-candidate no-op; same content twice in one batch; the
500/501 boundary; an unreadable directory surfaces as invalid input.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp import library as library_module
from calibre_mcp.config import Config
from calibre_mcp.errors import CalibredbError, InvalidInputError
from calibre_mcp.library import CalibreLibrary
from sample_books import sample_epub_sources


def _sample_epub(tmp_path: Path, name: str, index: int = 0) -> Path:
    # ``index`` picks a distinct source file so seeded books are never
    # byte-identical unless the test wants that (calibredb flags a
    # byte-identical add as a duplicate).
    sources = sample_epub_sources()
    dest = tmp_path / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(sources[index], dest)
    return dest


@pytest.fixture
def backup_root(tmp_path: Path) -> Path:
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


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# ------------------------------------------------------------------ BIMPORT-02


@pytest.mark.integration
def test_rejects_missing_path_before_scan_backup(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path
):
    with pytest.raises(InvalidInputError):
        facade.import_folder(tmp_path / "does-not-exist")

    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_rejects_file_path_before_scan_backup(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path
):
    a_file = _sample_epub(tmp_path, "not-a-dir.epub")

    with pytest.raises(InvalidInputError):
        facade.import_folder(a_file)

    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_unreadable_directory_surfaces_as_invalid_input(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path, monkeypatch
):
    # AD-021: a raw OSError from the scan is converted to InvalidInputError,
    # not left to escape unmapped.
    def _boom(_root):
        raise OSError("permission denied")

    monkeypatch.setattr(library_module, "scan_ebook_files", _boom)

    with pytest.raises(InvalidInputError):
        facade.import_folder(tmp_path)

    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_501_candidates_rejected_before_backup(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path, monkeypatch
):
    fake_candidates = [Path(f"/fake/book{i}.epub") for i in range(501)]
    monkeypatch.setattr(
        library_module, "scan_ebook_files", lambda _root: fake_candidates
    )

    with pytest.raises(InvalidInputError) as excinfo:
        facade.import_folder(tmp_path)

    assert "500" in str(excinfo.value)
    assert _snapshots(backup_root) == []


# ------------------------------------------------------------------ BIMPORT-03


@pytest.mark.integration
def test_500_candidates_accepted_takes_one_backup(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path, monkeypatch
):
    # Boundary: exactly 500 is accepted -> passes the cap and reaches the loop.
    # The per-file import itself is stubbed so the test proves the cap logic,
    # not 500 real subprocess calls (mirrors BCONV-06's validator-level test).
    fake_candidates = [Path(f"/fake/book{i}.epub") for i in range(500)]
    monkeypatch.setattr(
        library_module, "scan_ebook_files", lambda _root: fake_candidates
    )
    monkeypatch.setattr(
        facade, "_import_one", lambda _p: {"duplicate": True, "book_id": None}
    )

    result = facade.import_folder(tmp_path)

    assert len(result["duplicate"]) == 500
    assert result["added"] == []
    assert result["failed"] == []
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_zero_candidate_folder_is_noop_with_one_backup(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path
):
    # Spec edge case: an empty/no-candidate folder is valid, not an error.
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()

    result = facade.import_folder(empty_dir)

    assert result["status"] == "imported"
    assert result["added"] == result["duplicate"] == result["failed"] == []
    assert len(_snapshots(backup_root)) == 1
    assert result["backup"] == str(_snapshots(backup_root)[0])


# --------------------------------------------------------- BIMPORT-01/06/07


@pytest.mark.integration
def test_imports_recursive_tree_ignoring_non_ebook_and_hidden_files(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path
):
    # Independent Test: 2 ebooks (one nested) + a non-ebook + a dotfile.
    source = tmp_path / "src"
    book1 = _sample_epub(source, "book1.epub", index=0)
    book2 = _sample_epub(source, "nested/book2.epub", index=1)
    (source / "readme.txt").write_text("not an ebook")
    (source / ".hidden.epub").write_bytes(b"not scanned")

    result = facade.import_folder(source)

    assert result["status"] == "imported"
    added_paths = {a["path"] for a in result["added"]}
    assert added_paths == {str(book1), str(book2)}
    for entry in result["added"]:
        assert isinstance(entry["book_id"], int)  # BIMPORT-06: real id
        assert entry["book"].id == entry["book_id"]  # re-read metadata
    assert result["duplicate"] == []
    assert result["failed"] == []
    assert (
        len(result["added"]) + len(result["duplicate"]) + len(result["failed"]) == 2
    )  # BIMPORT-07
    assert len(_snapshots(backup_root)) == 1


# --------------------------------------------------------------- BIMPORT-05


@pytest.mark.integration
def test_rerun_same_import_surfaces_duplicates_not_fake_adds(
    facade: CalibreLibrary, backup_root: Path, tmp_path: Path
):
    source = tmp_path / "src"
    epub = _sample_epub(source, "book1.epub", index=0)
    first = facade.import_folder(source)
    assert len(first["added"]) == 1

    second = facade.import_folder(source)

    assert second["added"] == []
    assert second["duplicate"] == [{"path": str(epub)}]  # BIMPORT-05: no fake id
    assert len(_snapshots(backup_root)) == 2  # one backup per call


@pytest.mark.integration
def test_same_content_file_twice_in_batch_second_is_duplicate(
    facade: CalibreLibrary, tmp_path: Path
):
    # Spec edge case: identical file content under two subfolders -> the
    # first (sorted) path is added, the second is a duplicate, never a
    # second fake add.
    source = tmp_path / "src"
    first_path = _sample_epub(source, "a/book.epub", index=0)
    second_path = source / "b" / "book_copy.epub"
    second_path.parent.mkdir(parents=True)
    shutil.copy2(first_path, second_path)

    result = facade.import_folder(source)

    assert len(result["added"]) == 1
    assert result["added"][0]["path"] == str(first_path)
    assert len(result["duplicate"]) == 1
    assert result["duplicate"][0]["path"] == str(second_path)
    assert (
        len(result["added"]) + len(result["duplicate"]) + len(result["failed"]) == 2
    )


# --------------------------------------------------------------- BIMPORT-04


@pytest.mark.integration
def test_per_file_failure_lands_in_failed_batch_continues(
    facade: CalibreLibrary, tmp_path: Path, monkeypatch
):
    source = tmp_path / "src"
    good = _sample_epub(source, "good.epub", index=0)
    bogus = _sample_epub(source, "bogus.epub", index=1)
    original_add = facade._runner.add

    def _flaky_add(path: Path):
        if path.name == "bogus.epub":
            raise CalibredbError(["add"], 1, "calibredb boom: unsupported file")
        return original_add(path)

    monkeypatch.setattr(facade._runner, "add", _flaky_add)

    result = facade.import_folder(source)

    assert {f["path"] for f in result["failed"]} == {str(bogus)}
    assert {a["path"] for a in result["added"]} == {str(good)}
    assert result["duplicate"] == []
    assert (
        len(result["added"]) + len(result["duplicate"]) + len(result["failed"]) == 2
    )
