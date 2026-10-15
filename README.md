# calibre-mcp

[![CI](https://github.com/gustavofsousa/calibre-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/gustavofsousa/calibre-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-8A2BE2.svg)](https://modelcontextprotocol.io/)

A local **MCP server** (stdio). An LLM host manages a [Calibre](https://calibre-ebook.com/) ebook
library through it, in a conversation. The host is Claude Desktop, Claude Code or any
[MCP](https://modelcontextprotocol.io/)-compatible client. The server can search, edit metadata,
add, convert, deduplicate, organize, fix covers, fill metadata gaps, remove and email books. A human
approves each risky step.

**Most Calibre MCP servers are read-only: they search and list. This one *writes*, and it writes
safely.** A tool can corrupt or lose your library when it edits metadata, adds, converts or deletes
books. So each change here goes through a design that prevents an accident:

- **Plan → confirm on each destructive action.** The first call returns a human-readable diff and a
  `confirmation_token`. Nothing changes until you call again with that exact token.
- **Automatic `metadata.db` backup before each write** (rolling, last 20).
- **Recoverable deletes** — a trash copy *and* the Calibre recycle bin. Never a hard delete.
- **Reads cannot corrupt anything** — the server opens the SQLite connection with `mode=ro`.

> The goal: manage a library from a chat, not by clicks in the Calibre GUI. The project is also a
> showcase of how to design a tool that *can delete the files of a user*. It shows four parts: a
> hybrid I/O design, an explicit failure taxonomy, human-approval gates on each destructive action,
> and a test suite that never touches real user data. For what it does and why, read [PRODUCT.md](PRODUCT.md). For the
> full design, read [ARCHITECTURE.md](ARCHITECTURE.md).

## Why the hybrid design

- **Reads** (`search`, `list`, `view`, duplicate search) query `metadata.db` directly, read-only.
  They are fast. Their structure makes library corruption impossible: the SQLite connection opens
  with `mode=ro`.
- **Writes** (`edit`, `rename`, `add`, `remove`, `convert`, `merge`, `cover`, `email`) go through
  the CLI tools of Calibre (`calibredb`, `ebook-convert`, `calibre-smtp`). They never use raw SQL. So
  Calibre stays the authority over its own database.
- **Backup:** before each write, the server makes an **automatic `metadata.db` backup** (rolling,
  keeps the last 20).
- **Removal is recoverable:** the server copies the files to a managed trash folder *and* sends the
  book to the Calibre recycle bin. Never a permanent delete.
- **Each tool that changes data or sends data out has two steps** (plan → confirm). The first call
  returns a human-readable review and a `confirmation_token`. Nothing changes, and nothing goes out,
  until you call again with that exact token.

The full rationale, the module boundaries and the decision log live in
[ARCHITECTURE.md](ARCHITECTURE.md).

## Requirements

- **Calibre** installed, with `calibredb` and `ebook-convert` on your `PATH`
  (`calibredb --version`). If you want `email_book`, you also need `calibre-smtp`.
- **Python ≥ 3.12** and [`uv`](https://docs.astral.sh/uv/).

## Install

**Zero-clone (recommended)** — [`uv`](https://docs.astral.sh/uv/) builds and runs it directly from
the repo, with no manual checkout:

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

The server manages **one** library. An environment variable sets it:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CALIBRE_LIBRARY_PATH` | yes | — | Path to your Calibre library directory (the folder containing `metadata.db`). |
| `CALIBRE_MCP_BACKUP_DIR` | no | `<library>/.calibre-mcp-backups/` | Where pre-write backups and trashed files are stored. |

If `CALIBRE_LIBRARY_PATH` is not set, or the directory has no `metadata.db`, the server **fails
fast** at startup with a clear error.

> **If you move the library on disk, update the path in _two_ places:** the
> `CALIBRE_LIBRARY_PATH` of this server (host MCP config) *and* the `library_path` of the Calibre
> GUI (`~/.config/calibre/global.py.json`). The two are independent. A stale env fails fast at
> startup. AD-028 in `.specs/STATE.md` explains why there is no single source of truth (by design,
> for now).

`email_book` also needs SMTP relay credentials. The server loads them lazily. It boots without them,
and only `email_book` fails if they are missing:

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `CALIBRE_MCP_SMTP_RELAY` | for email | — | SMTP relay host. |
| `CALIBRE_MCP_SMTP_USERNAME` | for email | — | SMTP username. |
| `CALIBRE_MCP_SMTP_PASSWORD` | for email | — | SMTP password. Never logged, never returned in any tool output. |
| `CALIBRE_MCP_SMTP_FROM` | for email | — | Sender address. |
| `CALIBRE_MCP_SMTP_PORT` | no | `465` (SSL) / `25` (TLS/none) | SMTP port. |
| `CALIBRE_MCP_SMTP_ENCRYPTION` | no | `TLS` | One of `SSL`, `TLS`, `NONE`. |

### Claude Desktop / Claude Code

Add this to your MCP config (for example `claude_desktop_config.json`). **Zero-clone** — it runs
directly from the repo through `uvx`:

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

The server talks over stdio (JSON-RPC). It prints nothing to stdout except the MCP framing. All
logs go to stderr, on purpose ([ARCHITECTURE.md](ARCHITECTURE.md#stdout-hygiene)).

## Tools

| Tool | What it does | Gate |
| --- | --- | --- |
| **Read** | | |
| `search_books` | Resolve a Calibre search query (`author:asimov`, `tag:scifi`, …) to full book metadata. | read-only |
| `list_books` | Paginated, sortable listing — works even when the Calibre GUI holds a write lock. | read-only |
| `get_book` | Full metadata for one book id. | read-only |
| `read_cover` | Return a book's cover as viewable image content. | read-only |
| `find_duplicates` | Advisory report of likely-duplicate books by normalized (title, author). Never merges. | read-only |
| **Curate** | | |
| `update_metadata` | Edit a whitelisted field set (title, authors, tags, series, rating, comments, …). | plan → confirm |
| `update_metadata_bulk` | Broadcast a field change to N books in one batch (`list_mode` add/remove/replace). | plan → confirm (batch) |
| `rename_author` | Rename an author across every book — co-author-safe; renaming onto an existing name merges. | plan → confirm (batch) |
| `rename_tag` | Rename a tag across every book — other tags untouched; merges onto an existing tag. | plan → confirm (batch) |
| `rename_series` | Rename a series across every book — each book keeps its `series_index`. | plan → confirm (batch) |
| `set_cover` | Set a book's cover from a local image file (replace vs. add shown in the plan). | plan → confirm |
| `merge_duplicate_group` | Fold duplicate records into a survivor you choose — formats only, losers recoverably deleted. | plan → confirm (batch) |
| **Enrich** *(outbound network — see below)* | | |
| `enrich_from_identifier` | Propose missing metadata/cover for one book: by ISBN, or — without one — by title/author search (only a high-confidence match is proposed). Writes nothing. | read-only proposal |
| `enrich_missing` | Bounded sweep (default 25, max 100) proposing gap-fills for incomplete books, with or without an ISBN. Writes nothing. | read-only proposal |
| **Add & convert** | | |
| `add_book` | Add a book from a local file path; surfaces duplicates honestly. | single-step (backed up) |
| `import_folder` | Recursively import every ebook file found under a directory. | additive (backed up) |
| `convert_book` | Convert to a new format (`epub`, `azw3`, `mobi`, `pdf`) — additive, keeps the original(s). | single-step (backed up) |
| `convert_book_bulk` | Convert N books to one target format in one call. | additive (backed up) |
| **Remove & deliver** | | |
| `remove_book` | **Recoverable** removal: trash copy + Calibre recycle bin, never a hard delete. | plan → confirm |
| `email_book` | Email a book's file via `calibre-smtp`, picking the best format automatically. | plan → confirm |

**Enrichment goes through the normal gates.** The `enrich_*` tools only *propose*. To apply a
proposal, pass it to `update_metadata`, and pass its downloaded cover to `set_cover`. Each one has
its own plan → confirm.

WARNING: The `enrich_*` tools are the only tools that touch the network. They send the **ISBN** of
the book to the [Open Library API](https://openlibrary.org/developers/api) (no key, no account). For
a book with no ISBN, they send its **title and author**.

The tools send one request per second at most. The score of a title/author match is deterministic.
The tool proposes a match only when title *and* author agree. The result shows which work matched,
so you can check it before you apply it. Each other tool is fully local.

**`rating` uses the stored 0–10 scale of Calibre** (0–5 stars × 2, so `8` = ★★★★). Odd values are
half stars.

The server also has one MCP **resource**, `calibre://library/stats`. It is an aggregate profile of
the library: totals, format and language mix, metadata completeness (with cover coverage), and
data-quality flags (duplicate groups, books with no cover). You can read it with no tool call.

The docstring of each tool in [`server.py`](src/calibre_mcp/server.py) holds its full contract: edge
cases, error conditions, the exact field whitelist. The LLM host sees those docstrings, so they are
also the API reference.

## Development

```bash
uv run ruff check src tests   # lint
uv run mypy                   # strict type-check
uv run pytest                 # full suite (unit + integration + e2e)
uv run pytest -m unit         # fast unit tests only
```

About 390 tests in three tiers (`unit`, `integration`, `e2e`). Write tests never touch a real
library. They run against throwaway scratch libraries with synthetic sample books
(`tests/sample_books.py`). So the whole write path runs in CI too. A few read-only checks can also
run against your own library. To opt in, set `CALIBRE_MCP_TEST_REAL_LIBRARY=/path/to/library`. Read
[ARCHITECTURE.md](ARCHITECTURE.md#testing-strategy). For a manual end-to-end check against a real
library with no risk to it, read [docs/live-smoke-test.md](docs/live-smoke-test.md).

## Project layout

```
src/calibre_mcp/
├── server.py                # FastMCP tool surface — the only stdio/MCP-aware module
├── library.py               # CalibreLibrary facade — orchestrates every tool's business logic
├── sqlite_reader.py         # Read-only metadata.db access (the only sqlite3 call site)
├── calibredb_runner.py      # calibredb subprocess wrapper (search/edit/add/remove/add_format)
├── ebook_convert_runner.py  # ebook-convert subprocess wrapper
├── calibre_smtp_runner.py   # calibre-smtp subprocess wrapper
├── openlibrary_client.py    # Open Library HTTP client (the only network call site)
├── title_match.py           # pure title/author match scoring for ISBN-less enrichment
├── backup.py                # metadata.db snapshots + recoverable trash
├── confirmation.py          # plan→confirm token derivation/verification
├── bulk_edit.py             # pure list_mode (add/remove/replace) resolution for bulk edits
├── rename_resolve.py        # pure rename algebra shared by author/tag/series renames
├── author_rename.py         # author-rename entry point (thin re-export of rename_resolve)
├── folder_scan.py           # pure ebook discovery for folder import
├── config.py                # env-driven startup config, fail-fast validation
└── errors.py                # the failure taxonomy every layer maps to
```

## Roadmap

Shipped: the full read → curate → organize → enrich → distribute loop above. Three short docs hold
the planning:

- [`ROADMAP.md`](ROADMAP.md) — **tactical**: which feature ships in which version, phase gates,
  debt. Next up: **metadata rollback** (restore any of the automatic `metadata.db` backups from
  the MCP).
- [`ROADMAP-STRATEGY.md`](ROADMAP-STRATEGY.md) — **strategic**: what the project is for and the
  gated bets beyond it.
- [`BACKLOG.md`](BACKLOG.md) — the unsequenced pool of ideas, by domain.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md). It covers the dev workflow, the invariants that a PR must
keep, and the spec-driven process of this repo.

## License

[MIT](LICENSE) © Gustavo F Sousa.
