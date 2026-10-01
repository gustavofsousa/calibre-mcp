# Contributing

This started as a personal tool, but issues, bug reports, and pull requests are welcome. A few
pointers to get productive quickly and keep the codebase's guarantees intact.

## Setup

```bash
git clone <this-repo> calibre-mcp
cd calibre-mcp
uv sync
uv run pytest   # should be green before you change anything
```

You'll need Calibre installed (`calibredb`, `ebook-convert`, `calibre-smtp` on `PATH`) for the
integration/e2e tests to actually exercise the write path — see
[ARCHITECTURE.md#testing-strategy](ARCHITECTURE.md#testing-strategy).

## Before opening a PR

```bash
uv run ruff check src tests   # lint — must be clean
uv run mypy                   # strict type-check (src) — must be clean
uv run pytest                 # full suite — must be green
```

CI runs the same three commands on every push/PR; a red CI run blocks merge.

Optional, read-only, against your own library: `CALIBRE_MCP_TEST_REAL_LIBRARY=/path/to/library
uv run pytest`. Before a release, run the manual [live smoke test](docs/live-smoke-test.md).

## Invariants a PR must not break

These are load-bearing, not style preferences — read
[ARCHITECTURE.md](ARCHITECTURE.md#safety-mechanisms) for the reasoning behind each:

- **Reads never write.** `SqliteReader` opens `metadata.db` with `mode=ro`; no code path writes
  through it.
- **Writes go through a CLI runner, never raw SQL.** `calibredb`/`ebook-convert`/`calibre-smtp`
  stay the only way this project mutates a library — never `sqlite3` writes.
- **The tool layer (`server.py`) and the facade (`library.py`) never import `sqlite3` or
  `subprocess` directly.** Reads go through `SqliteReader`; writes go through a `*_runner.py`.
  Grepping for those imports outside `sqlite_reader.py` and the runner modules is the fast audit.
- **Every subprocess call is an argument list with `shell=False`.** Never build a shell string —
  this is what keeps a book title or file path from becoming a command-injection vector.
- **Every mutation is backed up first.** New mutating tools call `backup_metadata_db` before their
  `calibredb`/CLI call, not after.
- **Destructive or outward-facing tools use the plan→confirm gate.** If a new tool deletes data or
  sends something off the machine, it should follow the same two-step pattern as
  `update_metadata`/`remove_book`/`email_book` (see `confirmation.py`), not add a new ad-hoc
  approval mechanism.
- **Logging is stderr-only.** Stdout is the MCP stdio framing channel; nothing but MCP frames may
  be written there.
- **Write tests never touch a real Calibre library.** Bootstrap a scratch library via the
  `scratch_library` fixture in `tests/conftest.py` and seed it with `sample_epub_sources()` from
  `tests/sample_books.py` — never with files copied from a personal library path. This is the one
  rule with zero exceptions.
- **A test must not skip silently.** Skip reasons print by default (`-rs`); a new skip needs a
  reason that holds in CI too.

## Code style

- Follow the lint config as-is (`ruff` rules `E`, `F`, `I`, `UP`, `B` — see `pyproject.toml`); don't
  add new rule exemptions without discussing them.
- Type hints on public functions; dataclasses for structured data (see `Book`, `TrashResult`,
  `Config`).
- Docstrings on `@mcp.tool()` functions are user-facing — they're what the LLM host reads to decide
  how to call the tool. Keep them precise about edge cases and error conditions, not just a
  one-line summary.
- Comment only when the *why* isn't obvious from the code (a non-obvious constraint, a workaround,
  an invariant a future edit could silently break). Skip comments that just restate what the code
  does.

## How features get added here

Non-trivial features follow a lightweight spec-driven process: **Specify → Design → Tasks →
Execute**, tracked under `.specs/`. `.specs/STATE.md` holds the dated decision log (`AD-NNN`) and
current project status; [`ROADMAP.md`](ROADMAP.md) holds the versioned delivery plan and
[`BACKLOG.md`](BACKLOG.md) the unsequenced ideas. Skim them before proposing a
larger change so you're building on the same assumptions the rest of the codebase does. For
anything beyond a small fix, open an issue first so we can align on approach before you invest
time in an implementation.

## Reporting bugs

Include: your Calibre version (`calibredb --version`), the tool call that triggered the issue
(name + arguments, redact anything private), and the exact error message. If it's a data-safety
concern (something removed/changed unexpectedly), note whether the auto-backup/trash safety net
worked as expected — that's the detail most useful for triage here.
