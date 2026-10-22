# calibre-mcp

[![CI](https://github.com/gustavofsousa/calibre-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/gustavofsousa/calibre-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-8A2BE2.svg)](https://modelcontextprotocol.io/)

A local **MCP server** (stdio) that lets an LLM host — Claude Desktop, Claude Code, or any
[MCP](https://modelcontextprotocol.io/)-compatible client — manage a
[Calibre](https://calibre-ebook.com/) ebook library conversationally: search, edit metadata, add,
convert, deduplicate, remove, and email books, all with human-in-the-loop safety.

**Most Calibre MCP servers are read-only — they search and list. This one *writes* — and does it
safely.** Editing metadata, adding, converting, and deleting books is where a tool can actually
corrupt or lose your library, so every mutation here goes through a design built to make that
impossible to do by accident:

- **Plan → confirm on every destructive action.** The first call returns a human-readable diff and
  a `confirmation_token`; nothing changes until you re-call with that exact token.
- **Automatic `metadata.db` backup before every write** (rolling, last 20).
- **Recoverable deletes** — trash copy *and* Calibre recycle bin, never a hard delete.
- **Reads can't corrupt anything** — the SQLite connection is opened `mode=ro`.

> Built to stop clicking around the Calibre GUI and manage a library from a chat instead — and
> deliberately engineered as a showcase of how to design a tool that's *allowed to delete a user's
> files*: hybrid I/O design, an explicit failure taxonomy, human-approval gates on every
> destructive action, and a test suite that never touches real user data. See
> [PRODUCT.md](PRODUCT.md) for what it does and why, and [ARCHITECTURE.md](ARCHITECTURE.md) for the
> full design writeup.

## Why the hybrid design

- **Reads** (`search`, `list`, `view`, duplicate-finding) query `metadata.db` directly, read-only —
  fast, and structurally incapable of corrupting the library (the SQLite connection is opened
  `mode=ro`).
- **Writes** (`edit`, `add`, `remove`, `convert`, `email`) go through Calibre's own CLI tools
  (`calibredb`, `ebook-convert`, `calibre-smtp`) — never raw SQL — so Calibre stays authoritative
  over its own database.
- Every write is preceded by an **automatic `metadata.db` backup** (rolling, keeps the last 20).
- **Removal is recoverable**: files are copied to a managed trash folder *and* the book is sent to
  Calibre's recycle bin — never a permanent delete.
- **Every mutating or outward-facing tool is two-step** (plan → confirm): the first call returns a
  human-readable review plus a `confirmation_token`; nothing changes — and nothing is sent — until
  you re-call with that exact token.

Full rationale, module boundaries, and the decision log behind these choices live in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- **Calibre** installed, with `calibredb` and `ebook-convert` on your `PATH`
  (`calibredb --version`). `calibre-smtp` is also required if you want `email_book`.
- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/).

## Install

**Zero-clone (recommended)** — [`uv`](https://docs.astral.sh/uv/) builds and runs it straight from
the repo, no manual checkout:

```bash
uvx --from git+https://github.com/gustavofsousa/calibre-mcp calibre-mcp
```

**From a local checkout** (for development, or to pin a specific state):

```bash
git clone https://github.com/gustavofsousa/calibre-mcp calibre-mcp
cd calibre-mcp
uv sync
```

## Configure

The server manages **one** library, set via environment variable:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CALIBRE_LIBRARY_PATH` | yes | — | Path to your Calibre library directory (the folder containing `metadata.db`). |
| `CALIBRE_MCP_BACKUP_DIR` | no | `<library>/.calibre-mcp-backups/` | Where pre-write backups and trashed files are stored. |

The server **fails fast** at startup with a clear error if `CALIBRE_LIBRARY_PATH` is unset or the
directory has no `metadata.db`.

> **If you move the library on disk, update the path in _two_ places** — this server's
> `CALIBRE_LIBRARY_PATH` (host MCP config) *and* the Calibre GUI's own `library_path`
> (`~/.config/calibre/global.py.json`). They are independent; a stale env just fails fast at
> startup. See AD-028 in `.specs/STATE.md` for why there is no single source of truth (by design,
> for now).

`email_book` additionally needs SMTP relay credentials (loaded lazily — the server boots fine
without them, and only `email_book` fails if they're missing):

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CALIBRE_MCP_SMTP_RELAY` | for email | — | SMTP relay host. |
| `CALIBRE_MCP_SMTP_USERNAME` | for email | — | SMTP username. |
| `CALIBRE_MCP_SMTP_PASSWORD` | for email | — | SMTP password. Never logged, never returned in any tool output. |
| `CALIBRE_MCP_SMTP_FROM` | for email | — | Sender address. |
| `CALIBRE_MCP_SMTP_PORT` | no | `465` (SSL) / `25` (TLS/none) | SMTP port. |
| `CALIBRE_MCP_SMTP_ENCRYPTION` | no | `TLS` | One of `SSL`, `TLS`, `NONE`. |

### Claude Desktop / Claude Code

Add to your MCP config (e.g. `claude_desktop_config.json`). **Zero-clone** — runs straight from the
repo via `uvx`:

```json
{
  "mcpServers": {
    "calibre": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/gustavofsousa/calibre-mcp", "calibre-mcp"],
      "env": {
        "CALIBRE_LIBRARY_PATH": "/absolute/path/to/your/Calibre Library"
      }
    }
  }
}
```

Or, from a local checkout:

```json
{
  "mcpServers": {
    "calibre": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/calibre-mcp", "run", "calibre-mcp"],
      "env": {
        "CALIBRE_LIBRARY_PATH": "/absolute/path/to/your/Calibre Library"
      }
    }
  }
}
```

## Run manually

```bash
CALIBRE_LIBRARY_PATH="/path/to/Calibre Library" uv run calibre-mcp
# or equivalently:
CALIBRE_LIBRARY_PATH="/path/to/Calibre Library" uv run python -m calibre_mcp
```

The server communicates over stdio (JSON-RPC); it prints nothing to stdout except MCP framing —
all logs go to stderr, on purpose (see [ARCHITECTURE.md](ARCHITECTURE.md#stdout-hygiene)).

## Tools

| Tool | What it does | Gate |
| --- | --- | --- |
| `search_books` | Resolve a Calibre search query (`author:asimov`, `tag:scifi`, …) to full book metadata. | read-only |
| `list_books` | Paginated, sortable listing — works even when the Calibre GUI holds a write lock. | read-only |
| `get_book` | Full metadata for one book id. | read-only |
| `find_duplicates` | Advisory report of likely-duplicate books by normalized (title, author). Never merges. | read-only |
| `update_metadata` | Edit a whitelisted field set (title, authors, tags, series, rating, comments, …). | plan → confirm |
| `update_metadata_bulk` | Broadcast a field change to N books in one batch (`list_mode` add/remove/replace). | plan → confirm (batch) |
| `add_book` | Add a book from a local file path; surfaces duplicates honestly. | single-step (backed up) |
| `import_folder` | Recursively import every ebook file found under a directory. | additive (backed up) |
| `convert_book` | Convert to a new format (`epub`, `azw3`, `mobi`, `pdf`) — additive, keeps the original(s). | single-step (backed up) |
| `convert_book_bulk` | Convert N books to one target format in one call. | additive (backed up) |
| `remove_book` | **Recoverable** removal: trash copy + Calibre recycle bin, never a hard delete. | plan → confirm |
| `email_book` | Email a book's file via `calibre-smtp`, picking the best format automatically. | plan → confirm |

Plus one MCP **resource**, `calibre://library/stats` — an aggregate library profile (totals,
format/language mix, metadata completeness, data-quality flags) readable without any tool call.

Every tool's full contract (edge cases, error conditions, exact field whitelist) is documented in
its docstring in [`server.py`](src/calibre_mcp/server.py) — those docstrings are what the LLM host
sees, so they double as the API reference.

## Development

```bash
uv run ruff check src tests   # lint
uv run pytest                 # full suite (unit + integration + e2e)
uv run pytest -m unit         # fast unit tests only
```

137 tests across three tiers (`unit`, `integration`, `e2e`); write tests never touch a real
library — see [ARCHITECTURE.md](ARCHITECTURE.md#testing-strategy).

## Project layout

```
src/calibre_mcp/
├── server.py               # FastMCP tool surface — the only stdio/MCP-aware module
├── library.py               # CalibreLibrary facade — orchestrates every tool's business logic
├── sqlite_reader.py         # Read-only metadata.db access (the only sqlite3 call site)
├── calibredb_runner.py      # calibredb subprocess wrapper (search/edit/add/remove/add_format)
├── ebook_convert_runner.py  # ebook-convert subprocess wrapper
├── calibre_smtp_runner.py   # calibre-smtp subprocess wrapper
├── backup.py                 # metadata.db snapshots + recoverable trash
├── confirmation.py           # plan→confirm token derivation/verification
├── config.py                  # env-driven startup config, fail-fast validation
└── errors.py                  # the failure taxonomy every layer maps to
```

## Roadmap

Shipped: full read/curate/distribute loop (search, list, view, edit, add, remove, convert,
dedupe, email). What's next — library self-knowledge, bulk operations, cover/metadata enrichment,
device sync — is tracked in [`.specs/ROADMAP.md`](.specs/ROADMAP.md), including the reasoning for
sequencing and what's explicitly out of scope.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the dev workflow, the invariants a PR must preserve,
and how the spec-driven process behind this repo works.

## License

[MIT](LICENSE) © Gustavo F Sousa.
