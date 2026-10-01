# Roadmap (strategic) — calibre-mcp

> **What this doc is.** What the work is *for* beyond a personal tool, and the bets that build on it
> — by quarter, each gated on a real-world signal. Revised **quarterly**, not per session. "Which
> feature next?" is *not* answered here — that's [`ROADMAP.md`](ROADMAP.md) (tactical, per
> feature). Raw ideas live in [`BACKLOG.md`](BACKLOG.md). Decisions behind the direction: AD-018 →
> AD-019 → **AD-023** in [`.specs/STATE.md`](.specs/STATE.md).

**Stage:** 🧪 preview · 🌍 live · 📦 planned · ⏸️ parked · 🔒 behind a gate
**Single owner, no paid tiers** — so the optional `Plan`/`Owner` columns are left out on purpose.
Target dates are *proposed* until confirmed; a date here is a commitment, not an estimate.

---

## Direction (one screen)

- **Positioning:** *"the Calibre MCP that writes safely."* The niche is crowded (~10 free Calibre
  MCP servers, nearly all read-only); safe mutation is the one defensible spot.
- **Goal:** leverage, not revenue — portfolio proof + a reusable safe-mutation pattern. Charging
  for a local MCP wrapper is a dead end: the *host* captures the value.
- **Product scope stays narrow:** one user, one library (AD-007). Strategy never widens it.
- **Two tracks, gated independently:** the feature pipeline (`ROADMAP.md`) is always available to
  push; the bets below wait for their gates. Never sequence one behind the other.

```
Phase A — open source + brand ──Gate A→B: discovered──▶ Phase B — productize the pattern ──Gate B→C: someone pays──▶ Phase C — a vertical that pays
   (active, cost ≈ 0)                                    (queued)                                                    (not started)
```

---

## Q4 2026 — in progress · **Phase A (open source + brand)**

| # | Initiative | Stage | Target | Links to tactical |
| --- | --- | --- | --- | --- |
| A1 | Public repo current: Phase 3 + this hardening PR merged to `main` | 🧪 | 2026-10 *(proposed)* | v0.4 |
| A2 | Listed in ≥ 1 MCP directory/registry | 📦 | 2026-10 *(proposed)* | — |
| A3 | Launch write-up posted (`docs/launch-notes.md`, drafted) | 📦 | 2026-11 *(proposed)* | — |
| A4 | PyPI publish *(optional)* | ⏸️ | after v1.0 | v1.0 |

Done earlier in Phase A: direction flip recorded (AD-023), README repositioned around safe writes,
zero-clone `uvx --from git+…` install verified (and the `mcp<2` pin that keeps it working).

**Every row A1–A4 is a one-way door** (push / submit / post / publish) — each needs an explicit go.

**Gate A→B — advance when:** the repo is live and discoverable (merged, README leads with safe
writes, listed in ≥ 1 directory). **Kill/park if:** no signal after a fair window (~1 quarter after
A2+A3). Phase A has still paid for itself as a portfolio piece — don't escalate chasing vanity
metrics.

## Q1 2027 — directional · **Phase B (productize the safe-mutation pattern)** 🔒

| # | Initiative | Stage | Window | Links to tactical |
| --- | --- | --- | --- | --- |
| B1 | Pick the shape: template repo vs. skill/playbook vs. internal reuse first | 🔒 | ~jan/2027 | — |
| B2 | First internal consumer (periciamap or biblioteca-api) adopts the pattern | 🔒 | ~feb/2027 | — |
| B3 | Written playbook: "how to design an MCP that's allowed to delete" | 🔒 | ~mar/2027 | MAINT-04 is its best demo |

**Bet:** the leverage isn't the Calibre wrapper, it's the pattern — plan→confirm + backup-before-write
+ recoverable delete + an honest partial-failure contract, for any MCP that mutates user data. The
audience (teams applying AI) pays for authority and advice, not for a free MCP.

**Gate B→C — the expensive door:** ≥ 1 person/org has paid, or concretely committed to pay, for the
pattern, the content, or advice built on it. **Interest alone does not open it.** **Kill/park if:**
the pattern gets reused internally but draws no outside pull — keep it as internal tooling.

## 2027+ — not started · **Phase C (apply the pattern to a vertical that pays)** 🔒

**Bet:** point the same engine at a corpus where an error is expensive and the buyer is an
organization — forensic reports (periciamap is the natural first candidate: same owner,
error-costly domain), legal or medical records. That's where a real SaaS exists.

**Preconditions:** Gate B→C open **and** a vertical with real domain access. No pre-building before
demand is validated (Traction Mode: no full architecture without traction). **Kill/park if:**
discovery shows the vertical's bottleneck isn't safe mutation — re-aim, don't force the pattern.

---

## Known business risks

| Risk | Mitigation |
| --- | --- |
| A read-only competitor adds writes first and takes the niche | Ship A1–A2 this quarter; the moat is the *safety design*, so MAINT-04 (usable rollback) is prioritized on the tactical side. |
| "Safe writes" claim undermined by a real data-loss bug | Suite now runs its ~350 write-path tests in CI (AD-029); live smoke runbook before each release ([`docs/live-smoke-test.md`](docs/live-smoke-test.md)). |
| Effort sinks into features nobody discovers | Gate A→B is about *discovery*, not features — don't let the feature track substitute for A2/A3. |

## Not pursued (decision, not "not yet")

- Any SaaS/hosting around Calibre itself — wrong market, no moat, DMCA/storage liability.
- Monetizing calibre-mcp directly (paid tier, license) — the host captures the value.

## Delivered

| # | Initiative | Final stage | Delivered |
| --- | --- | --- | --- |
| A0 | Open-sourced (public + MIT) | 🌍 | 2026-07-17 |
| A0.1 | Repositioned around safe writes + `uvx` install | 🌍 | 2026-07-31 |
