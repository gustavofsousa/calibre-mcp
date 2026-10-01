"""Integration tests for EbookConvertRunner — derived from spec CONV-01.

Uses the real ``ebook-convert`` binary (Calibre 8.2 on PATH) against a small
sample file. No calibredb/library involvement — this runner only converts a
file on disk.

CONV-01 AC-1/AC-5: convert produces the target file on success; a bogus/empty
source surfaces the failure via EbookConvertError and never a false success.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp.ebook_convert_runner import EbookConvertRunner
from calibre_mcp.errors import EbookConvertError, EbookConvertNotFoundError
from sample_books import sample_epub_sources


def _sample_epub(tmp_path: Path) -> Path:
    sources = sample_epub_sources()
    smallest = min(sources, key=lambda p: p.stat().st_size)
    dest = tmp_path / "sample.epub"
    shutil.copy2(smallest, dest)
    return dest


@pytest.fixture
def runner() -> EbookConvertRunner:
    return EbookConvertRunner()


@pytest.mark.integration
def test_convert_epub_to_pdf_produces_the_file(runner: EbookConvertRunner, tmp_path):
    source = _sample_epub(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    produced = runner.convert(source, "pdf", out_dir)

    assert produced == out_dir / "sample.pdf"
    assert produced.is_file()
    assert produced.stat().st_size > 0


@pytest.mark.integration
def test_convert_bogus_source_raises_ebook_convert_error(
    runner: EbookConvertRunner, tmp_path
):
    bogus = tmp_path / "bogus.epub"
    bogus.write_bytes(b"not a real epub")
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(EbookConvertError) as excinfo:
        runner.convert(bogus, "pdf", out_dir)

    assert excinfo.value.exit_code != 0
    assert not (out_dir / "bogus.pdf").exists()


@pytest.mark.integration
def test_missing_binary_raises_not_found_error(tmp_path):
    runner = EbookConvertRunner(binary="ebook-convert-does-not-exist")
    source = _sample_epub(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    with pytest.raises(EbookConvertNotFoundError):
        runner.convert(source, "pdf", out_dir)
