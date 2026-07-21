"""Integration tests for ``CalibreLibrary.update_metadata_bulk`` (BULK-01, T2).

Derived from spec ACs, asserting spec-defined outcomes. ALL writes go to a
per-test ``scratch_library`` (temp dir) — they NEVER touch the real library
(the non-negotiable test-safety rule). Books are seeded via a raw
``CalibredbRunner`` so the backup dir starts empty and the batch's own backup
is observable.

BEDIT-01: plan (no token) returns a per-book diff + one token, no write.
BEDIT-02: apply (token) backs up, applies via set_metadata, returns applied[].
BEDIT-03: a mismatched token is refused (ConfirmationError), no write.
BEDIT-04: a vanished id fails that book only; the rest still apply.
BEDIT-05: exactly one metadata.db backup is taken before the batch.
BEDIT-06: invalid input (empty/duplicate/non-int book_ids, bad list_mode,
          empty/unknown fields, list_mode without a list field) is rejected
          before any token/backup/write.
BEDIT-07: applied entries re-read the affected fields only.
BEDIT-08/09: add unions preserving existing values; remove ignores missing
          values and can resolve to [] (edge case).
Edge case: a single-id batch still runs the full plan->confirm path.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from calibre_mcp.calibredb_runner import CalibredbRunner
from calibre_mcp.config import Config
from calibre_mcp.errors import ConfirmationError, InvalidInputError
from calibre_mcp.library import CalibreLibrary

REAL_LIBRARY = Path("/home/gustavo/Documents/BibliotecaCalibre")


def _sample_epub(tmp_path: Path, name: str, index: int = 0) -> Path:
    # ``index`` picks a distinct source file so two seeded books in the same
    # test are never byte-identical (calibredb would otherwise flag the
    # second add as a duplicate and refuse to import it).
    sources = list(REAL_LIBRARY.glob("**/*.epub"))
    if len(sources) <= index:
        pytest.skip("not enough distinct sample .epub files in the real library")
    dest = tmp_path / name
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


def _seed_book(
    scratch_library: Path,
    tmp_path: Path,
    name: str,
    tags: list[str] | None = None,
    index: int = 0,
) -> int:
    """Add a book directly via the runner (no facade backup) and return its id."""
    result = CalibredbRunner(scratch_library).add(_sample_epub(tmp_path, name, index))
    assert result.book_id is not None
    if tags:
        CalibredbRunner(scratch_library).set_metadata(result.book_id, {"tags": tags})
    return result.book_id


def _snapshots(backup_root: Path) -> list[Path]:
    return list(backup_root.glob("metadata-*.db"))


# --------------------------------------------------------------------- plan


@pytest.mark.integration
def test_plan_returns_per_book_diff_and_token_without_writing(
    facade, scratch_library, tmp_path
):
    # BEDIT-01: no token -> per-book diff + one token, nothing written.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", index=1)

    plan = facade.update_metadata_bulk([b2, b1], {"series": "Dune"})

    assert plan["status"] == "plan"
    assert [d["book_id"] for d in plan["diffs"]] == [b1, b2]  # sorted order
    assert all(
        d["found"] and d["diff"]["series"]["proposed"] == "Dune" for d in plan["diffs"]
    )
    assert plan["confirmation_token"]
    assert facade.get_book(b1).series is None
    assert facade.get_book(b2).series is None


@pytest.mark.integration
def test_plan_reports_vanished_id_as_not_found(facade, scratch_library, tmp_path):
    # BEDIT-04 edge case: a nonexistent id is listed not-found in the plan, no abort.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")

    plan = facade.update_metadata_bulk([b1, 999999], {"series": "Dune"})

    entries = {d["book_id"]: d for d in plan["diffs"]}
    assert entries[999999] == {"book_id": 999999, "found": False}
    assert entries[b1]["found"] is True


# -------------------------------------------------------------------- apply


@pytest.mark.integration
def test_apply_all_succeed_writes_and_takes_exactly_one_backup(
    facade, scratch_library, backup_root, tmp_path
):
    # BEDIT-02, BEDIT-05, BEDIT-07: apply writes all books, re-reads affected
    # fields, and exactly one backup covers the whole batch.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", index=1)
    plan = facade.update_metadata_bulk([b1, b2], {"series": "Dune"})

    applied = facade.update_metadata_bulk(
        [b1, b2], {"series": "Dune"}, token=plan["confirmation_token"]
    )

    assert applied["status"] == "applied"
    by_id = {a["book_id"]: a for a in applied["applied"]}
    assert by_id[b1]["fields"] == {"series": "Dune"}
    assert by_id[b2]["fields"] == {"series": "Dune"}
    assert applied["failed"] == []
    assert facade.get_book(b1).series == "Dune"
    assert facade.get_book(b2).series == "Dune"
    assert len(_snapshots(backup_root)) == 1


@pytest.mark.integration
def test_apply_token_mismatch_refuses_and_writes_nothing(
    facade, scratch_library, backup_root, tmp_path
):
    # BEDIT-03: a wrong token is refused; nothing is written or backed up.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")

    with pytest.raises(ConfirmationError):
        facade.update_metadata_bulk([b1], {"series": "Dune"}, token="deadbeefdeadbeef")

    assert facade.get_book(b1).series is None
    assert _snapshots(backup_root) == []


@pytest.mark.integration
def test_apply_one_vanished_id_reports_failed_others_still_applied(
    facade, scratch_library, tmp_path
):
    # BEDIT-04 (Independent Test 1): one bad id fails alone; the rest apply.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    b2 = _seed_book(scratch_library, tmp_path, "b2.epub", index=1)
    plan = facade.update_metadata_bulk([b1, b2, 999999], {"series": "Dune"})

    applied = facade.update_metadata_bulk(
        [b1, b2, 999999], {"series": "Dune"}, token=plan["confirmation_token"]
    )

    applied_ids = {a["book_id"] for a in applied["applied"]}
    failed_ids = {f["book_id"] for f in applied["failed"]}
    assert applied_ids == {b1, b2}
    assert failed_ids == {999999}
    assert len(applied["applied"]) + len(applied["failed"]) == 3
    assert facade.get_book(b1).series == "Dune"
    assert facade.get_book(b2).series == "Dune"


@pytest.mark.integration
def test_single_id_batch_runs_full_plan_confirm_path(
    facade, scratch_library, backup_root, tmp_path
):
    # Edge case: a degenerate one-book batch is not an error.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    plan = facade.update_metadata_bulk([b1], {"publisher": "Acme"})

    applied = facade.update_metadata_bulk(
        [b1], {"publisher": "Acme"}, token=plan["confirmation_token"]
    )

    assert applied["applied"] == [{"book_id": b1, "fields": {"publisher": "Acme"}}]
    assert facade.get_book(b1).publisher == "Acme"
    assert len(_snapshots(backup_root)) == 1


# ---------------------------------------------------------------- list_mode


@pytest.mark.integration
def test_add_mode_preserves_existing_values_across_books(
    facade, scratch_library, tmp_path
):
    # BEDIT-08 AC1 (Independent Test 2): [a,b] add [b,c] -> [a,b,c].
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", tags=["a", "b"])
    plan = facade.update_metadata_bulk([b1], {"tags": ["b", "c"]}, list_mode="add")

    assert plan["diffs"][0]["diff"]["tags"]["proposed"] == ["a", "b", "c"]

    applied = facade.update_metadata_bulk(
        [b1], {"tags": ["b", "c"]}, list_mode="add", token=plan["confirmation_token"]
    )

    assert set(applied["applied"][0]["fields"]["tags"]) == {"a", "b", "c"}
    assert set(facade.get_book(b1).tags) == {"a", "b", "c"}


@pytest.mark.integration
def test_remove_mode_ignores_missing_values(facade, scratch_library, tmp_path):
    # BEDIT-08 AC2 (Independent Test 2): remove [a,z] from [a,b,c] -> [b,c].
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", tags=["a", "b", "c"])
    plan = facade.update_metadata_bulk([b1], {"tags": ["a", "z"]}, list_mode="remove")

    assert plan["diffs"][0]["diff"]["tags"]["proposed"] == ["b", "c"]

    applied = facade.update_metadata_bulk(
        [b1], {"tags": ["a", "z"]}, list_mode="remove", token=plan["confirmation_token"]
    )

    assert set(applied["applied"][0]["fields"]["tags"]) == {"b", "c"}
    assert set(facade.get_book(b1).tags) == {"b", "c"}


@pytest.mark.integration
def test_remove_mode_can_empty_the_list_field(facade, scratch_library, tmp_path):
    # Spec edge case: remove that empties a list field writes [] (not an error).
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub", tags=["a"])
    plan = facade.update_metadata_bulk([b1], {"tags": ["a"]}, list_mode="remove")

    assert plan["diffs"][0]["diff"]["tags"]["proposed"] == []

    applied = facade.update_metadata_bulk(
        [b1], {"tags": ["a"]}, list_mode="remove", token=plan["confirmation_token"]
    )

    assert applied["applied"][0]["fields"]["tags"] == []
    assert facade.get_book(b1).tags == []


# ------------------------------------------------------------- BEDIT-06 gate


@pytest.mark.integration
def test_rejects_empty_book_ids(facade):
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([], {"series": "Dune"})


@pytest.mark.integration
def test_rejects_duplicate_book_ids(facade, scratch_library, tmp_path):
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([b1, b1], {"series": "Dune"})


@pytest.mark.integration
def test_rejects_non_integer_book_id(facade):
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([1, "2"], {"series": "Dune"})


@pytest.mark.integration
def test_rejects_bool_as_book_id(facade):
    # bool is an int subclass in Python; must be explicitly rejected.
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([1, True], {"series": "Dune"})


@pytest.mark.integration
def test_rejects_empty_fields(facade, scratch_library, tmp_path):
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([b1], {})


@pytest.mark.integration
def test_rejects_unknown_field(facade, scratch_library, tmp_path):
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([b1], {"bogus_field": "x"})


@pytest.mark.integration
def test_rejects_invalid_list_mode(facade, scratch_library, tmp_path):
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([b1], {"tags": ["x"]}, list_mode="merge")


@pytest.mark.integration
def test_rejects_list_mode_without_a_list_field(facade, scratch_library, tmp_path):
    # Edge case: list_mode with nothing to apply it to is a caller error.
    b1 = _seed_book(scratch_library, tmp_path, "b1.epub")
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([b1], {"series": "Dune"}, list_mode="add")


@pytest.mark.integration
def test_invalid_input_rejected_before_any_backup(facade, backup_root):
    # BEDIT-06: invalid input never reaches the backup/write path.
    with pytest.raises(InvalidInputError):
        facade.update_metadata_bulk([], {"series": "Dune"})

    assert _snapshots(backup_root) == []
