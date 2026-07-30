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
EMAIL-01 AC-2:  plan (no token) sends nothing and returns a confirmation_token.
EMAIL-01 AC-1/3: apply (token) sends via calibre-smtp with the resolved format.
EMAIL-01 AC-5:  the SMTP password never appears in any returned dict.
EMAIL-01 AC-6:  missing SMTP env raises SmtpNotConfiguredError, no send.
EMAIL-01 AC-7:  no attachable format refuses before sending.
"""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest

from calibre_mcp.calibre_smtp_runner import CalibreSmtpRunner
from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import (
    SMTP_FROM_ENV,
    SMTP_PASSWORD_ENV,
    SMTP_RELAY_ENV,
    SMTP_USERNAME_ENV,
    Config,
)
from calibre_mcp.errors import (
    ConfirmationError,
    EbookConvertError,
    InvalidInputError,
    SmtpNotConfiguredError,
)
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
def test_convert_book_backs_up_before_add_format_not_after(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path, monkeypatch
):
    # CONV-01 AC-6 / AD-011: backup must happen BEFORE add_format, not merely
    # exist afterward — records call order via spies on both.
    book_id = _seed_book(scratch_library, tmp_path)
    calls: list[str] = []

    import calibre_mcp.library as library_module

    real_backup = library_module.backup_metadata_db

    def _spy_backup(*args, **kwargs):
        calls.append("backup")
        return real_backup(*args, **kwargs)

    real_add_format = facade._runner.add_format

    def _spy_add_format(*args, **kwargs):
        calls.append("add_format")
        return real_add_format(*args, **kwargs)

    monkeypatch.setattr(library_module, "backup_metadata_db", _spy_backup)
    monkeypatch.setattr(facade._runner, "add_format", _spy_add_format)

    facade.convert_book(book_id, "pdf")

    assert calls == ["backup", "add_format"]


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

    # CONV-01 AC-5: the convert error surfaces and NOTHING is added (add_format
    # never ran). The backup is taken before the (failed) convert now that the
    # single tool shares the bulk convert core — a pre-convert snapshot is
    # harmless under AD-011 rolling retention; AC-5 only requires "adds nothing".
    assert facade.get_book(book_id).formats == book.formats  # nothing added
    assert len(_snapshots(backup_root)) == 1  # backup-before-convert (shared core)


@pytest.mark.integration
def test_convert_book_unsupported_target_format_rejected(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # CONV-01: an unsupported target format is rejected before any subprocess.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError) as excinfo:
        facade.convert_book(book_id, "bogus")

    assert "bogus" in str(excinfo.value)


# ------------------------------------------------------- _classify_convert core
# BULK-02 T1: the shared convert core. _classify_convert returns a skip reason as
# DATA (not an exception) for benign no-ops, else ("ready", source_path) — the
# split that lets the bulk loop route skips vs failures without parsing errors.


@pytest.mark.integration
def test_classify_convert_ready_returns_source_path(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # Ready outcome: a convertible book -> ("ready", the resolved source path).
    book_id = _seed_book(scratch_library, tmp_path)
    book = facade.get_book(book_id)

    kind, info = facade._classify_convert(book, "pdf")

    assert kind == "ready"
    assert info == str(facade._reader.format_files(book_id)["EPUB"])


@pytest.mark.integration
def test_classify_convert_already_has_target_is_skip_naming_format(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # Skip outcome (already has target): reason names the format, no exception.
    book_id = _seed_book(scratch_library, tmp_path)
    book = facade.get_book(book_id)

    kind, reason = facade._classify_convert(book, "epub")

    assert kind == "skip"
    assert "EPUB" in reason


@pytest.mark.integration
def test_classify_convert_no_source_is_skip(
    facade: CalibreLibrary, scratch_library: Path, tmp_path: Path, monkeypatch
):
    # Skip outcome (no source file): benign no-op reason, no exception.
    book_id = _seed_book(scratch_library, tmp_path)
    book = facade.get_book(book_id)
    monkeypatch.setattr(facade._reader, "format_files", lambda _id: {})

    kind, reason = facade._classify_convert(book, "pdf")

    assert kind == "skip"
    assert "no file to convert from" in reason


# ----------------------------------------------------------------- email_book

_STUB_SMTP_SOURCE = '''#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["STUB_RECORD_FILE"], "w") as f:
    json.dump(sys.argv[1:], f)
sys.exit(0)
'''


@pytest.fixture
def smtp_stub(tmp_path: Path) -> Path:
    stub = tmp_path / "calibre-smtp-stub.py"
    stub.write_text(_STUB_SMTP_SOURCE)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


@pytest.fixture
def smtp_record(tmp_path: Path, monkeypatch) -> Path:
    record = tmp_path / "argv.json"
    monkeypatch.setenv("STUB_RECORD_FILE", str(record))
    return record


@pytest.fixture
def smtp_env(monkeypatch) -> None:
    monkeypatch.setenv(SMTP_RELAY_ENV, "smtp.example.com")
    monkeypatch.setenv(SMTP_USERNAME_ENV, "alice")
    monkeypatch.setenv(SMTP_PASSWORD_ENV, "s3cr3t-p4ss")
    monkeypatch.setenv(SMTP_FROM_ENV, "alice@example.com")


@pytest.fixture
def mailer_facade(facade: CalibreLibrary, smtp_stub: Path) -> CalibreLibrary:
    facade._mailer = CalibreSmtpRunner(binary=str(smtp_stub))
    return facade


@pytest.mark.integration
def test_email_book_plan_sends_nothing_and_returns_token(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
):
    # EMAIL-01 AC-2: no token -> plan (recipient/format/subject/file) + token,
    # nothing sent.
    book_id = _seed_book(scratch_library, tmp_path)

    plan = mailer_facade.email_book(book_id, "bob@example.com")

    assert plan["status"] == "plan"
    assert plan["recipient"] == "bob@example.com"
    assert plan["format"] == "EPUB"
    assert plan["file"]
    assert plan["confirmation_token"]
    assert not smtp_record.exists()  # nothing sent


@pytest.mark.integration
def test_email_book_apply_with_token_sends_via_calibre_smtp(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
    smtp_env: None,
):
    # EMAIL-01 AC-1/AC-3: matching token -> calibre-smtp invoked with the
    # resolved attachment.
    book_id = _seed_book(scratch_library, tmp_path)
    plan = mailer_facade.email_book(book_id, "bob@example.com")

    result = mailer_facade.email_book(
        book_id, "bob@example.com", token=plan["confirmation_token"]
    )

    assert result["status"] == "sent"
    argv = json.loads(smtp_record.read_text())
    assert "-a" in argv and argv[argv.index("-a") + 1] == plan["file"]
    assert "bob@example.com" in argv


@pytest.mark.integration
def test_email_book_token_mismatch_refuses_and_sends_nothing(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
    smtp_env: None,
):
    # plan->confirm integrity: a wrong token is refused, nothing sent.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(ConfirmationError):
        mailer_facade.email_book(book_id, "bob@example.com", token="deadbeefdeadbeef")

    assert not smtp_record.exists()


@pytest.mark.integration
def test_email_book_missing_smtp_env_raises_not_configured_no_send(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
    monkeypatch,
):
    # EMAIL-01 AC-6: SMTP unset -> SmtpNotConfiguredError naming the var, no send.
    monkeypatch.delenv(SMTP_RELAY_ENV, raising=False)
    book_id = _seed_book(scratch_library, tmp_path)
    plan = mailer_facade.email_book(book_id, "bob@example.com")

    with pytest.raises(SmtpNotConfiguredError) as excinfo:
        mailer_facade.email_book(
            book_id, "bob@example.com", token=plan["confirmation_token"]
        )

    assert SMTP_RELAY_ENV in str(excinfo.value)
    assert not smtp_record.exists()


@pytest.mark.integration
def test_email_book_no_attachable_format_refuses_before_sending(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
):
    # EMAIL-01 AC-7: an explicit format the book doesn't have refuses upfront.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError) as excinfo:
        mailer_facade.email_book(book_id, "bob@example.com", format="pdf")

    assert "PDF" in str(excinfo.value)
    assert not smtp_record.exists()


@pytest.mark.integration
def test_email_book_explicit_format_picks_that_file_not_the_default(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
):
    # EMAIL-01 AC-3: explicit format wins over the epub->azw3->mobi->pdf default
    # when the book has both — resolved format/file must be the PDF, not EPUB.
    book_id = _seed_book(scratch_library, tmp_path)
    mailer_facade.convert_book(book_id, "pdf")  # book now has EPUB and PDF
    pdf_path = mailer_facade._reader.format_files(book_id)["PDF"]

    plan = mailer_facade.email_book(book_id, "bob@example.com", format="pdf")

    assert plan["format"] == "PDF"
    assert plan["file"] == str(pdf_path)


@pytest.mark.integration
def test_email_book_invalid_recipient_rejected(
    mailer_facade: CalibreLibrary, scratch_library: Path, tmp_path: Path
):
    # basic recipient-shape validation before any plan/send.
    book_id = _seed_book(scratch_library, tmp_path)

    with pytest.raises(InvalidInputError):
        mailer_facade.email_book(book_id, "not-an-email")


@pytest.mark.integration
def test_email_book_password_never_appears_in_plan_or_result(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    smtp_record: Path,
    smtp_env: None,
):
    # EMAIL-01 AC-5: the SMTP password never appears in the plan or the result.
    book_id = _seed_book(scratch_library, tmp_path)
    password = "s3cr3t-p4ss"

    plan = mailer_facade.email_book(book_id, "bob@example.com")
    result = mailer_facade.email_book(
        book_id, "bob@example.com", token=plan["confirmation_token"]
    )

    assert password not in json.dumps(plan)
    assert password not in json.dumps(result)


@pytest.mark.integration
def test_email_book_no_metadata_backup_taken(
    mailer_facade: CalibreLibrary,
    scratch_library: Path,
    tmp_path: Path,
    backup_root: Path,
    smtp_record: Path,
    smtp_env: None,
):
    # EMAIL-01: no library mutation -> no metadata.db backup for a send.
    book_id = _seed_book(scratch_library, tmp_path)
    plan = mailer_facade.email_book(book_id, "bob@example.com")

    mailer_facade.email_book(
        book_id, "bob@example.com", token=plan["confirmation_token"]
    )

    assert _snapshots(backup_root) == []
