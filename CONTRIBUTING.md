# Contributing

This project started as a personal tool. Issues, bug reports and pull requests are welcome. This
page helps you start fast and keep the guarantees of the codebase.

## Setup

```bash
git clone <this-repo> calibre-mcp
cd calibre-mcp
uv sync
uv run pytest   # must be green before you change anything
```

The integration and e2e tests exercise the write path only if Calibre is installed (`calibredb`,
`ebook-convert`, `calibre-smtp` on `PATH`). Read
[ARCHITECTURE.md#testing-strategy](ARCHITECTURE.md#testing-strategy).

## Before opening a PR

```bash
uv run ruff check src tests   # lint — must be clean
uv run mypy                   # strict type-check (src) — must be clean
uv run pytest                 # full suite — must be green
```

CI runs the same three commands on each push and each PR. A red CI run blocks the merge.

Optional, read-only, against your own library: `CALIBRE_MCP_TEST_REAL_LIBRARY=/path/to/library
uv run pytest`. Before a release, run the manual [live smoke test](docs/live-smoke-test.md).

## Invariants a PR must not break

These rules carry the safety of the project. They are not style preferences. For the reason
behind each one, read [ARCHITECTURE.md](ARCHITECTURE.md#safety-mechanisms):

- **Reads never write.** `SqliteReader` opens `metadata.db` with `mode=ro`. No code path writes
  through it.
- **Writes go through a CLI runner, never raw SQL.** `calibredb`/`ebook-convert`/`calibre-smtp`
  stay the only way that this project changes a library. Never write with `sqlite3`.
- **The tool layer (`server.py`) and the facade (`library.py`) never import `sqlite3` or
  `subprocess` directly.** Reads go through `SqliteReader`. Writes go through a `*_runner.py`. For a
  fast audit, grep for those imports outside `sqlite_reader.py` and the runner modules.
- **Each subprocess call is an argument list with `shell=False`.** Never build a shell string. This
  rule stops a book title or a file path from becoming a command-injection vector.
- **Each change is backed up first.** A new tool that changes data calls `backup_metadata_db` before
  its `calibredb`/CLI call, not after.
- **Destructive or outward-facing tools use the plan→confirm gate.** If a new tool deletes data or
  sends something off the machine, it must follow the two-step pattern of
  `update_metadata`/`remove_book`/`email_book` (`confirmation.py`). Never add a new ad-hoc approval
  mechanism.
- **Logging goes to stderr only.** Stdout is the MCP stdio framing channel. Only MCP frames go
  there.
- **Write tests never touch a real Calibre library.** Create a scratch library with the
  `scratch_library` fixture in `tests/conftest.py`. Fill it with `sample_epub_sources()` from
  `tests/sample_books.py`. Never use files copied from a personal library path. This rule has zero
  exceptions.
- **A test must not skip silently.** Skip reasons print by default (`-rs`). A new skip needs a reason
  that also holds in CI.

## Code style

- Follow the lint config as it is (`ruff` rules `E`, `F`, `I`, `UP`, `B` in `pyproject.toml`).
  Before you add a rule exemption, discuss it.
- Put type hints on public functions. Use dataclasses for structured data (`Book`, `TrashResult`,
  `Config`).
- The docstrings on `@mcp.tool()` functions face the user. The LLM host reads them to decide how to
  call the tool. Make them precise about edge cases and error conditions. A one-line summary is not
  enough.
- Comment only when the code does not show the *why*: a non-obvious constraint, a workaround, an
  invariant that a future edit can break in silence. Do not write comments that repeat the code.

## How features get added here

Non-trivial features follow a light spec-driven process: **Specify → Design → Tasks → Execute**,
tracked in `.specs/`.

- `.specs/STATE.md` holds the dated decision log (`AD-NNN`) and the project status.
- [`ROADMAP.md`](ROADMAP.md) holds the versioned delivery plan.
- [`BACKLOG.md`](BACKLOG.md) holds the unsequenced ideas.

Before you propose a larger change, read them. Then you build on the same assumptions as the rest of
the codebase. For anything more than a small fix, open an issue first. We agree on the approach
before you spend time on an implementation.

## Reporting bugs

Include these items:

- Your Calibre version (`calibredb --version`).
- The tool call that caused the issue: name and arguments. Remove anything private.
- The exact error message.

If the bug is about data safety (something removed or changed by surprise), say if the auto-backup
and trash safety net worked. That detail helps the triage most.
