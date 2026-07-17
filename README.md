# calibre-mcp

[![CI](https://github.com/gustavofsousa/calibre-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/gustavofsousa/calibre-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-8A2BE2.svg)](https://modelcontextprotocol.io/)

A local **MCP server** (stdio) that lets an LLM host — Claude Desktop, Claude Code — manage your
[Calibre](https://calibre-ebook.com/) ebook library. Reads are fast and safe (direct read-only
SQLite); writes go through `calibredb` so Calibre's own integrity logic is always respected.

> I built this to manage my own Calibre library straight from an LLM host — asking a chat to find,
> tag, add, or clean up books instead of clicking around the GUI. It's a personal project, but if it's
> useful to you too, **contributions are welcome** — see [Contributing](#contributing).

## Why the hybrid design

- **Reads** (`search`, `list`, `view`) query `metadata.db` directly, read-only — fast and can never
  corrupt the library.
- **Writes** (`edit`, `add`, `remove`) go through the `calibredb` CLI — never raw SQL — so Calibre
  stays authoritative.
- Every write is preceded by an **automatic `metadata.db` backup** (rolling, keeps the last 20).
- **Removal is recoverable**: files are copied to a managed trash folder *and* the book is sent to
  Calibre's recycle bin — never a permanent delete.
- **Edits and removals are two-step** (plan → confirm): the first call returns a human-readable
  review plus a `confirmation_token`; nothing changes until you re-call with that exact token.

## Requirements

- **Calibre** installed, with `calibredb` on your `PATH` (`calibredb --version`).
- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/).

## Install

```bash
git clone <this-repo> calibre-mcp
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

### Claude Desktop / Claude Code

Add to your MCP config (e.g. `claude_desktop_config.json`):

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

The server communicates over stdio (JSON-RPC); it prints nothing to stdout except MCP framing — all
logs go to stderr.

## Tools

| Tool | What it does |
| --- | --- |
| `search_books` | Resolve a Calibre search query to full book metadata. Empty query → empty list. |
| `list_books` | Paginated, sortable listing (lock-independent — works even when the Calibre GUI holds a write lock). |
| `get_book` | Full metadata for one book id. |
| `update_metadata` | Two-step edit of a whitelisted field set (title, authors, tags, series, rating, …). |
| `add_book` | Add a book from a local file path (returns the new id + metadata). |
| `remove_book` | Two-step, **recoverable** removal (trash copy + recycle bin). |

## Development

```bash
uv run ruff check src tests   # lint
uv run pytest                 # full suite (unit + integration + e2e)
uv run pytest -m unit         # fast unit tests only
```

Write tests never touch a real library — they bootstrap a scratch Calibre library in a temp dir.

## Scope

MVP (P1): read + edit + add/remove, with the safety net above. Convert and organize/deduplicate
(P2) are out of scope for this release. A library baseline profile exposed on connect (P3, STATS-01)
is planned after P2 — see `.specs/STATE.md`.

## Contributing

Contributions are welcome — issues, bug reports, and pull requests all help. A few pointers:

- The roadmap and design decisions live in [`.specs/STATE.md`](.specs/STATE.md) (see `AD-NNN`
  decisions and the P2/P3 backlog). Skim it before proposing larger changes so we keep the
  hybrid read/write model and safety invariants intact.
- Keep the core invariants: **reads never write**, **writes go through `calibredb`** (never raw
  SQL), logging to **stderr only**, and subprocess calls as **arg lists** (never shell strings).
- Before opening a PR, run the checks locally:

  ```bash
  uv run ruff check src tests   # lint
  uv run pytest                 # full suite (unit + integration + e2e)
  ```

- Write tests never touch a real library — they bootstrap a scratch Calibre library in a temp dir.
  Please keep it that way.

For anything non-trivial, open an issue first so we can align on approach.

## License

[MIT](LICENSE) © Gustavo F Sousa.
