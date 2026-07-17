"""Integration tests for CalibreSmtpRunner — derived from spec EMAIL-01.

Uses a STUBBED ``calibre-smtp`` binary (a temp Python script that records its
argv to a file) so no real mail is ever sent and no network is touched.

EMAIL-01 AC-1: send invokes calibre-smtp with the right relay/attachment/
subject args.
EMAIL-01 AC-5: the password is never logged, never in the exception message,
and any echoed stderr is scrubbed of it.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from calibre_mcp.calibre_smtp_runner import CalibreSmtpRunner
from calibre_mcp.config import SmtpConfig
from calibre_mcp.errors import CalibreSmtpError, CalibreSmtpNotFoundError

_STUB_SOURCE = '''#!/usr/bin/env python3
import json
import os
import sys

with open(os.environ["STUB_RECORD_FILE"], "w") as f:
    json.dump(sys.argv[1:], f)

if "FORCE-FAIL" in sys.argv:
    password = ""
    if "-p" in sys.argv:
        password = sys.argv[sys.argv.index("-p") + 1]
    sys.stderr.write(f"relay rejected credentials, password was: {password}\\n")
    sys.exit(1)

sys.exit(0)
'''


@pytest.fixture
def stub_binary(tmp_path: Path) -> Path:
    stub = tmp_path / "calibre-smtp-stub.py"
    stub.write_text(_STUB_SOURCE)
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


@pytest.fixture
def record_file(tmp_path: Path, monkeypatch) -> Path:
    record = tmp_path / "argv.json"
    monkeypatch.setenv("STUB_RECORD_FILE", str(record))
    return record


@pytest.fixture
def cfg() -> SmtpConfig:
    return SmtpConfig(
        relay="smtp.example.com",
        port=465,
        username="alice",
        password="s3cr3t-p4ss",
        encryption="SSL",
        sender="alice@example.com",
    )


@pytest.fixture
def attachment(tmp_path: Path) -> Path:
    path = tmp_path / "book.epub"
    path.write_bytes(b"fake epub content")
    return path


@pytest.mark.integration
def test_send_invokes_stub_with_right_relay_and_attachment_args(
    stub_binary: Path, record_file: Path, cfg: SmtpConfig, attachment: Path
):
    runner = CalibreSmtpRunner(binary=str(stub_binary))

    runner.send(
        cfg, cfg.sender, "bob@example.com", "A book for you", "enjoy", attachment
    )

    argv = json.loads(record_file.read_text())
    assert "-a" in argv and argv[argv.index("-a") + 1] == str(attachment)
    assert "-s" in argv and argv[argv.index("-s") + 1] == "A book for you"
    assert "--relay" in argv and argv[argv.index("--relay") + 1] == cfg.relay
    assert argv[-2:] == ["bob@example.com", "enjoy"]  # to, body (from precedes them)


@pytest.mark.integration
def test_send_non_zero_exit_raises_calibre_smtp_error(
    stub_binary: Path, record_file: Path, cfg: SmtpConfig, attachment: Path
):
    runner = CalibreSmtpRunner(binary=str(stub_binary))

    with pytest.raises(CalibreSmtpError) as excinfo:
        runner.send(
            cfg, cfg.sender, "bob@example.com", "FORCE-FAIL", "enjoy", attachment
        )

    assert excinfo.value.exit_code == 1


@pytest.mark.integration
def test_password_never_appears_in_any_output_or_exception(
    stub_binary: Path, record_file: Path, cfg: SmtpConfig, attachment: Path
):
    runner = CalibreSmtpRunner(binary=str(stub_binary))

    with pytest.raises(CalibreSmtpError) as excinfo:
        runner.send(
            cfg, cfg.sender, "bob@example.com", "FORCE-FAIL", "enjoy", attachment
        )

    assert cfg.password not in str(excinfo.value)
    assert cfg.password not in excinfo.value.stderr
    assert cfg.password not in " ".join(excinfo.value.cmd)


@pytest.mark.integration
def test_missing_binary_raises_not_found_error(cfg: SmtpConfig, attachment: Path):
    runner = CalibreSmtpRunner(binary="calibre-smtp-does-not-exist")

    with pytest.raises(CalibreSmtpNotFoundError):
        runner.send(cfg, cfg.sender, "bob@example.com", "hi", "enjoy", attachment)
