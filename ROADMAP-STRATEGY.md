# Roadmap (strategic) — calibre-mcp

> **What this doc is.** What the work is *for* beyond a personal tool, and the bets that build on
> it. It goes by quarter, and a real-world signal gates each bet. Revise it **each quarter**, not
> each session. This doc does *not* answer "which feature next?". [`ROADMAP.md`](ROADMAP.md)
> answers that (tactical, per feature). Raw ideas live in [`BACKLOG.md`](BACKLOG.md). The decisions
> behind the direction: AD-018 → AD-019 → **AD-023** in [`.specs/STATE.md`](.specs/STATE.md).

**Stage:** 🧪 preview · 🌍 live · 📦 planned · ⏸️ parked · 🔒 behind a gate
**Single owner, no paid tiers.** So the optional `Plan`/`Owner` columns are absent on purpose.
A target date is *proposed* until the owner confirms it. A confirmed date here is a commitment, not
an estimate.

---

## Direction (one screen)

- **Positioning:** *"the Calibre MCP that writes safely."* The niche is crowded (about 10 free
  Calibre MCP servers, almost all read-only). Safe mutation is the one spot that we can defend.
- **Goal:** leverage, not revenue: portfolio proof and a reusable safe-mutation pattern. A paid local
  MCP wrapper is a dead end, because the *host* captures the value.
- **Product scope stays narrow:** one user, one library (AD-007). Strategy never widens it.
- **Two tracks, each with its own gate:** you can always push the feature pipeline (`ROADMAP.md`).
  The bets below wait for their gates. Never put one track behind the other.

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

Done earlier in Phase A: the direction change is recorded (AD-023), the README leads with safe
writes, and the zero-clone `uvx --from git+…` install works (with the `mcp<2` pin that keeps it
working).

WARNING: **Each row A1–A4 is a one-way door** (push / submit / post / publish). Each one needs an
explicit go from the owner.

**Gate A→B — advance when** the repo is live and people can find it: merged, the README leads with
safe writes, listed in ≥ 1 directory. **Kill/park if** there is no signal after a fair window (about
1 quarter after A2+A3). Phase A already paid for itself as a portfolio piece. Do not escalate to
chase vanity metrics.

## Q1 2027 — directional · **Phase B (productize the safe-mutation pattern)** 🔒

| # | Initiative | Stage | Window | Links to tactical |
| --- | --- | --- | --- | --- |
| B1 | Pick the shape: template repo vs. skill/playbook vs. internal reuse first | 🔒 | ~jan/2027 | — |
| B2 | First internal consumer (periciamap or biblioteca-api) adopts the pattern | 🔒 | ~feb/2027 | — |
| B3 | Written playbook: "how to design an MCP that's allowed to delete" | 🔒 | ~mar/2027 | MAINT-04 is its best demo |

**Bet:** the leverage is not the Calibre wrapper. It is the pattern: plan→confirm +
backup-before-write + recoverable delete + an honest partial-failure contract, for any MCP that
changes user data. The audience (teams that apply AI) pays for authority and advice, not for a free
MCP.

**Gate B→C — the expensive door:** ≥ 1 person or org paid, or made a concrete commitment to pay, for
the pattern, the content or advice built on it. **Interest alone does not open it.** **Kill/park
if** the pattern gets internal reuse but no outside pull. Then keep it as internal tooling.

## 2027+ — not started · **Phase C (apply the pattern to a vertical that pays)** 🔒

**Bet:** apply the same engine to a corpus where an error is expensive and the buyer is an
organization: forensic reports, legal records or medical records. periciamap is the natural first
candidate (same owner, a domain where errors cost a lot). A real SaaS exists there.

**Preconditions:** Gate B→C is open **and** a vertical gives real domain access. Build nothing before
the demand is validated. **Kill/park if** discovery shows that the bottleneck of the vertical is not
safe mutation. Then re-aim. Do not force the pattern.

---

## Known business risks

| Risk | Mitigation |
| --- | --- |
| A read-only competitor adds writes first and takes the niche | Ship A1–A2 this quarter; the moat is the *safety design*, so MAINT-04 (usable rollback) is prioritized on the tactical side. |
| "Safe writes" claim undermined by a real data-loss bug | Suite now runs its ~350 write-path tests in CI (AD-029); live smoke runbook before each release ([`docs/live-smoke-test.md`](docs/live-smoke-test.md)). |
| Effort sinks into features nobody discovers | Gate A→B is about *discovery*, not features. Never let the feature track replace A2/A3. |

## Not pursued (decision, not "not yet")

- Any SaaS or hosting around Calibre itself: wrong market, no moat, DMCA and storage liability.
- Direct revenue from calibre-mcp (paid tier, license): the host captures the value.

## Delivered

| # | Initiative | Final stage | Delivered |
| --- | --- | --- | --- |
| A0 | Open-sourced (public + MIT) | 🌍 | 2026-07-17 |
| A0.1 | Repositioned around safe writes + `uvx` install | 🌍 | 2026-07-31 |
