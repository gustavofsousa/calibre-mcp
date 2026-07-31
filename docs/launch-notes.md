# Launch notes — calibre-mcp (DRAFT — not posted)

> Working draft for the Phase A launch (see `.specs/ROADMAP.md → Strategic Horizon → Phase A`).
> Posting anywhere is a checkpointed one-way door — do not publish without an explicit go.

## Positioning (the one line)

**The Calibre MCP that writes — safely.** Most Calibre MCP servers are read-only (search/list).
This one edits metadata, adds, converts, and deletes books, and every mutation is built so you
can't wreck your library by accident: plan→confirm on destructive actions, automatic backup before
every write, recoverable deletes, read-only SQLite for reads.

## Why it's different (vs. the ~10 existing Calibre MCPs)

The field is crowded and free, but almost all of it is read-only. The moment a tool can *change*
your library is the moment it can corrupt or lose it — and that's the part everyone else skips.
calibre-mcp treats "allowed to delete a user's files" as a design problem:

- **Plan → confirm** — first call returns a human-readable diff + a `confirmation_token`; nothing
  changes until you re-call with that exact token (the token is a hash of the op params, so what's
  applied is provably what was reviewed).
- **Backup before every write** — rolling `metadata.db` snapshots, last 20.
- **Recoverable delete** — trash copy *and* Calibre recycle bin; never a hard delete.
- **Reads can't corrupt** — SQLite opened `mode=ro`.
- **Honest partial-failure contract** — a batch of 20 where #5 fails still applies the other 19 and
  reports #5; never a fake "all succeeded."

## Install (the pitch: zero-clone)

```bash
uvx --from git+https://github.com/gustavofsousa/calibre-mcp calibre-mcp
```

Wire it into Claude Desktop/Code with the `uvx` config block in the README. No checkout, no PyPI.

## Draft blurbs

**One-liner (directory/registry):**
> Manage a Calibre library from any MCP host — the only one built around *safe writes*: plan→confirm
> on destructive actions, auto-backup before every write, recoverable deletes.

**Show-HN / r/Calibre style (longer):**
> I kept wanting to fix metadata and dedupe my Calibre library from a chat instead of clicking
> through the GUI. Existing Calibre MCP servers are read-only, so I built one that can actually
> write — and spent most of the effort on *not letting an LLM wreck the library*: every destructive
> action is a two-step plan→confirm with a hashed token, every write is preceded by a rolling
> backup, deletes go to a trash copy + the recycle bin, and reads use a read-only SQLite connection
> that structurally can't corrupt anything. 137 tests, none of which touch a real library. MIT.

## Pre-launch checklist (each item = a checkpointed action, do with explicit go)

- [ ] Push current local state to the public remote (it's stale since 2026-07-17).
- [ ] Confirm CI is green on the pushed state.
- [ ] Sanity-check `uvx --from git+…` against the *pushed* repo (not just the local wheel).
- [ ] Submit to ≥1 MCP directory/registry.
- [ ] (Optional) Publish to PyPI so install drops the `--from git+…` — separate one-way door.
- [ ] Post the launch blurb (pick venue).

## Open questions before posting

- Which MCP directory/registry to target first?
- PyPI now, or after the git-based install has proven itself?
- Where to post (r/Calibre, MCP community, personal channels) — and in what order?
