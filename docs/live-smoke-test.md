# Live smoke test — every tool against a real library, without risking it

The automated suite proves each contract on throwaway scratch libraries, and
`tests/e2e/test_curation_journey.py` chains every write tool on synthetic books. What neither can
prove is that the server behaves correctly **as wired into a real host, against a real library** —
real Calibre version, real lock behavior, real Open Library responses. This runbook does that
safely, and is worth running before each release.

**Safety model:** a full copy of the library first, test books that can never collide with real ones,
and a field-by-field diff at the end proving no real book changed.

## 1. Snapshot and baseline (before touching anything)

```bash
LIB="/path/to/Calibre Library"
SNAP="$LIB-snapshot-$(date +%F)"
cp -a "$LIB" "$SNAP"                                    # full restore point
calibredb list --library-path "$LIB" --fields all --for-machine > before.json
```

Close the Calibre GUI first if you want `calibredb`-backed tools to run without lock contention.

## 2. Make test copies that can't collide with real books

Copy 2–3 small real `.epub` files out of the library and rewrite their embedded metadata, so every
test record is unmistakable (`MCPTEST` prefix) and `calibredb` doesn't flag them as duplicates of the
originals:

```bash
mkdir -p mcptest/folder/sub
cp "<small book A>.epub" mcptest/a.epub
cp "<small book B>.epub" mcptest/folder/b.epub
cp "<small book C>.epub" mcptest/folder/sub/c.epub
ebook-meta mcptest/a.epub            -t "MCPTEST Alpha" -a "MCPTEST Author One"
ebook-meta mcptest/folder/b.epub     -t "MCPTEST Beta"  -a "MCPTEST Author Two"
ebook-meta mcptest/folder/sub/c.epub -t "MCPTEST Beta"  -a "MCPTEST Author Two"   # same as b → duplicate
cp mcptest/folder/sub/c.epub mcptest/d.epub && ebook-meta mcptest/d.epub -t "MCPTEST Gamma"
echo note > mcptest/folder/readme.txt                                               # must be ignored
```

Every tag, series and rename target used below is also `mcptest-*` / `MCPTEST *`, and **every plan
must list only MCPTEST books** — if a plan ever names a real book, stop and don't confirm.

## 3. Drive every tool through the host

Ask the host (Claude Code / Desktop) to run, in order — for each two-step tool, check the plan, then
confirm with its token:

| # | Call | Expect |
| --- | --- | --- |
| 1 | `add_book(a.epub)` | `added`, new id, a backup path |
| 2 | `import_folder(mcptest/folder)` | b → `added`, c → `duplicate`, `readme.txt` absent |
| 3 | `add_book(d.epub)` | `added` (Gamma) |
| 4 | `search_books("title:MCPTEST")`, `list_books`, `get_book` | 3 test books; `total` = baseline + 3 |
| 5 | `update_metadata(Gamma, {title: "MCPTEST Beta", tags, series, series_index: 2, rating: 8})` | plan diff; a **forged token is refused**; real token applies; re-read `rating` = **8** |
| 6 | `find_duplicates()` | the Beta pair appears (plus any real groups — leave those alone) |
| 7 | `update_metadata_bulk([A, B], {tags: [...], publisher}, list_mode: "add")` | per-book diff, `failed: []` |
| 8 | `rename_tag` / `rename_author` / `rename_series` (MCPTEST names only) | plans list only test ids; `series_index` preserved |
| 9 | `read_cover(A)` → `set_cover(A, red.png)` → `read_cover(A)` | image before, `current_has_cover: true` (replace), new image after |
| 10 | `convert_book(A, "azw3")` twice | converted, then refused (already has AZW3) |
| 11 | `convert_book_bulk([A, B, 999999], "azw3")` | A `skipped`, B `converted`, 999999 `failed` |
| 12 | `merge_duplicate_group(B, [Gamma])` | Gamma's formats folded, Gamma trashed recoverably |
| 13 | `enrich_missing(limit=5)` | proposals only — nothing written |
| 14 | `email_book(A, <your address>)` | plan only; confirm only if SMTP is configured and you want the mail |
| 15 | `remove_book(A)`, `remove_book(B)` | review → removed; files in `.calibre-mcp-backups/trash/`; `get_book` → not found |
| 16 | read resource `calibre://library/stats` | totals back to baseline |

## 4. Prove no real book changed

```bash
calibredb list --library-path "$LIB" --fields all --for-machine > after.json
python3 - <<'EOF'
import json
before = {b["id"]: b for b in json.load(open("before.json"))}
after = {b["id"]: b for b in json.load(open("after.json"))}
assert set(before) == set(after), (set(before) ^ set(after))
changed = [(i, k) for i in before for k in before[i] if before[i][k] != after[i].get(k)]
assert not changed, changed
print(f"OK — {len(before)} real books identical, field by field (incl. last_modified)")
EOF
```

Residue that is expected and harmless: the test books in Calibre's recycle bin (`.caltrash/`,
auto-purged by Calibre) and in `.calibre-mcp-backups/trash/`. Once the diff passes, the snapshot from
step 1 can be deleted.

---

## Run log

### 2026-10-01 — Calibre 8.2.100, real library of 194 books

All 21 tools + the stats resource exercised as above. Result: **194/194 real books identical field
by field afterwards**, including `last_modified`.

| Finding | Outcome |
| --- | --- |
| `update_metadata(rating: 8)` stored **10** — `calibredb --field rating:N` takes *stars* and stores N×2, while the tool contract and the reader use the 0–10 scale | **Fixed** (AD-030) + round-trip regression test; it had no test before |
| Forged/guessed tokens on `update_metadata`, `rename_tag`, `rename_author`, `rename_series` | All refused before any write ✅ |
| `enrich_missing` found only **7 candidates in 196 books** (51 have an ISBN) | The v0.4 completeness gate can't be met by the ISBN path alone → ENRICH-04 in the roadmap |
| `library_stats` has no cover coverage | The v0.4 "every book has a cover" gate isn't measurable → STATS-02 |
| 2 real duplicate groups surfaced (196/209, 68/132) | Left untouched; listed as curation to-do in `BACKLOG.md` |
| `email_book` | Not exercised — the agent's permission policy blocked even the plan step; run manually |
