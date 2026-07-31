"""Unit tests for the pure folder-scan discovery module (BULK-03, BIMPORT-01).

Derived from spec.md ACs and listed edge cases, asserting spec-defined outcomes.
No fixture / no library — pure ``tmp_path`` filesystem trees, mirroring
``test_bulk_edit.py``'s pure-module style.

BIMPORT-01: recursive discover, case-insensitive whitelist match, silently
            ignore non-ebook files, exclude hidden/dotfiles, never follow
            symlinks.
Edge cases: empty tree -> []; sorted ascending path order (BIMPORT-07 ordering).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from calibre_mcp.folder_scan import EBOOK_EXTENSIONS, scan_ebook_files


@pytest.mark.unit
def test_extensions_are_the_spec_defined_whitelist():
    assert EBOOK_EXTENSIONS == frozenset(
        {
            ".epub",
            ".mobi",
            ".azw",
            ".azw3",
            ".azw4",
            ".kfx",
            ".fb2",
            ".fbz",
            ".pdf",
            ".djvu",
            ".cbz",
            ".cbr",
            ".cbc",
            ".lit",
            ".lrf",
            ".pdb",
            ".prc",
            ".snb",
            ".tcr",
        }
    )


@pytest.mark.unit
def test_discovers_ebook_in_nested_subfolder(tmp_path: Path):
    # BIMPORT-01 + spec edge case: recursion finds a file in a subfolder.
    nested = tmp_path / "sub" / "deeper"
    nested.mkdir(parents=True)
    ebook = nested / "book.epub"
    ebook.write_bytes(b"x")

    assert scan_ebook_files(tmp_path) == [ebook]


@pytest.mark.unit
def test_extension_match_is_case_insensitive(tmp_path: Path):
    # Spec edge case: "Book.EPUB" is still recognized as an ebook candidate.
    ebook = tmp_path / "Book.EPUB"
    ebook.write_bytes(b"x")

    assert scan_ebook_files(tmp_path) == [ebook]


@pytest.mark.unit
def test_non_ebook_file_is_silently_excluded(tmp_path: Path):
    # BIMPORT-01: files outside the whitelist are ignored, not returned.
    (tmp_path / "readme.txt").write_text("notes")
    ebook = tmp_path / "book.epub"
    ebook.write_bytes(b"x")

    assert scan_ebook_files(tmp_path) == [ebook]


@pytest.mark.unit
def test_dotfile_is_excluded(tmp_path: Path):
    # BIMPORT-01: hidden files (dotfiles) are excluded from the scan.
    (tmp_path / ".hidden.epub").write_bytes(b"x")
    ebook = tmp_path / "book.epub"
    ebook.write_bytes(b"x")

    assert scan_ebook_files(tmp_path) == [ebook]


@pytest.mark.unit
def test_hidden_directory_is_pruned_entirely(tmp_path: Path):
    # BIMPORT-01: an entire hidden subtree is skipped, not just its top file.
    hidden_dir = tmp_path / ".git"
    hidden_dir.mkdir()
    (hidden_dir / "inside.epub").write_bytes(b"x")
    ebook = tmp_path / "book.epub"
    ebook.write_bytes(b"x")

    assert scan_ebook_files(tmp_path) == [ebook]


@pytest.mark.unit
def test_symlinked_directory_is_not_followed(tmp_path: Path):
    # BIMPORT-01: symlinks are never followed — a symlinked subtree with ebooks
    # is not scanned.
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "external.epub").write_bytes(b"x")
    target = tmp_path / "target"
    target.mkdir()
    os.symlink(outside, target / "link_to_outside", target_is_directory=True)

    assert scan_ebook_files(target) == []


@pytest.mark.unit
def test_empty_tree_returns_empty_list(tmp_path: Path):
    # Spec edge case: an empty folder is valid, not an error -> [].
    assert scan_ebook_files(tmp_path) == []


@pytest.mark.unit
def test_result_is_sorted_by_path_string(tmp_path: Path):
    # BIMPORT-07 ordering: ascending sorted path, deterministic regardless of
    # filesystem creation order.
    (tmp_path / "z.epub").write_bytes(b"x")
    (tmp_path / "a.epub").write_bytes(b"x")
    sub = tmp_path / "m"
    sub.mkdir()
    (sub / "b.epub").write_bytes(b"x")

    result = scan_ebook_files(tmp_path)

    assert result == sorted(result, key=str)
    assert [p.name for p in result] == ["a.epub", "b.epub", "z.epub"]
