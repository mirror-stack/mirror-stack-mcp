# 🪞🔎🪪 mirror-stack-mcp

**One MCP server for the whole [Mirror Stack](https://github.com/mirror-stack).** Install once,
add one server, and an agent has all four mirrors: claims, actions, provenance, and a
stack-level verify-all.

💬 **[Discussions](https://github.com/orgs/mirror-stack/discussions)** — questions · ideas · independent reproductions welcome.

## Get all mirrors at once

```bash
pip install git+https://github.com/mirror-stack/mirror-stack-mcp
```

That single install pulls **measure-mirror + action-mirror + provenance-mirror** as
dependencies — you don't clone four repos. (Apache-2.0, zero-dep cores.)

## Add one MCP server

```json
{
  "mcpServers": {
    "mirror-stack": { "command": "mirror-stack-mcp" }
  }
}
```

No `cwd`, no `PYTHONPATH` — it's a proper installed entry point. Works in Claude Code, Cursor,
Windsurf, any MCP client.

## Tools (18)

| Tool | Mirror | Does |
|---|---|---|
| `mm_preregister` | 🪞 claims | seal a claim + kill-condition **before** measuring |
| `mm_verify` | 🪞 | umbrella verify — every probe whose input key is present |
| `mm_audit` | 🪞 | audit a result vs its sealed registration |
| `mm_power_check` | 🪞 | false-negative guard — is n big enough? (design-time) |
| `mm_falsifiability_check` | 🪞 | Popper gate — kill-condition registered & not tripped? |
| `mm_leakage_check` | 🪞 | train∩test contamination |
| `mm_multiseed_check` | 🪞 | unstable signal / lucky seed |
| `mm_retract` | 🪞 | chain-linked retraction (cannot be silently deleted) |
| `mm_anchor` | 🪞 | tamper-evident snapshot to store outside the ledger (local) |
| `mm_anchor_bitcoin` | 🪞⏱️ | **real** external anchor — timestamp ledger heads into Bitcoin (OpenTimestamps) |
| `mm_anchor_upgrade` | 🪞⏱️ | retrieve the Bitcoin block attestation once a calendar has committed (~1–3h) |
| `mm_anchor_verify` | 🪞⏱️ | verify a Bitcoin anchor via a public block explorer — **no local node needed** |
| `mm_preflight` | 🪞 | GO/BLOCK gate primitive — wire into a compute launcher / pre-commit hook |
| `am_record` | 🪪 actions | seal an action; `target=<claim_id>` ties it to a claim |
| `am_witness` | 🪪 | pin a peer's ledger head (catches whole-file replacement) |
| `am_verify` | 🪪 | verify an action ledger's hash chain |
| `pm_verify` | 🔎 provenance | verify a file's provenance across 5 signals |
| `stack_verify_all` | 🪞🔎🪪 | whole stack in one call: chain (L1) + anchors (L3) + witness (L2) |

(More granular `measure-mirror` probes are reachable via `mm_verify` — it dispatches by data key.)

## External anchor: Bitcoin (OpenTimestamps) ⏱️🔗

`mm_anchor` writes a *local* snapshot — useful, but it's still **your** file. `mm_anchor_bitcoin`
upgrades the L3 layer to a **real external clock**: it timestamps your ledger heads into the
Bitcoin blockchain via [OpenTimestamps](https://opentimestamps.org), so anyone can later prove
your record existed before a given block — independent of you *and* of GitHub.

**Honest scope (this is the whole point, so we say it plainly):**

- ✅ **proves** your ledger heads existed before a Bitcoin block time → no backdating, no silent rewrite.
- ❌ **does NOT prove** the *content* is true (GIGO — an early-sealed lie is still a lie).
- ❌ **does NOT** summon an external *judging* witness (that's the social layer, L2). The clock is
  run *now* for a verifier who may arrive *later*.

Cryptography here doesn't *block* dishonesty — it makes a rewrite **detectable**.

### Use it

```bash
pip install "mirror-stack-mcp[bitcoin] @ git+https://github.com/mirror-stack/mirror-stack-mcp"
# (pulls the `ots` CLI; needs network to reach the public OpenTimestamps calendars)
```

Then, via the MCP tools (or the agent calling them):

1. **Stamp** — `mm_anchor_bitcoin(ledger_paths=["/path/seara.jsonl", …], out_dir="…/anchors_ots")`
   → builds a manifest of the heads, submits it, returns `state="pending"` + the `.ots` path.
2. **Upgrade** — in ~1–3h, `mm_anchor_upgrade(ots_path)` → `state="bitcoin_confirmed"` + `block_height`.
3. **Verify** — `mm_anchor_verify(ots_path)` cross-checks the block's merkle root on a public
   explorer (default blockstream.info) — **no Bitcoin node required** — and returns whether it matches.

Anyone can independently re-check: `curl https://blockstream.info/api/block-height/<height>`.

See **[docs/ANCHORING.md](docs/ANCHORING.md)** for the full walkthrough, CLI fallback, and the
L1 / L2 / L3 model.

## The discipline travels with the tools

When an agent connects, the server injects a compact **honest-measurement discipline** via the
MCP `instructions` handshake — so the methodology arrives *with* the tools, not as a separate
doc someone has to find. It carries the one rule that matters most: **separate the tool from
your judgment** — say "mm flagged X" only when a probe returned a Finding you can quote; say
"applying the discipline, I suspect X" when it is your reasoning. Plus: seal-before-compute
(preregister + kill-condition), power before spending, verify-before-reporting, and "a missing
ledger is itself a signal."

(MCP clients that surface server instructions — e.g. Claude Code — show this on connect. It is
guidance, not enforcement: the hard guarantee is still the chain + witness, not the prompt.)

### Reminders at each beat (configurable)

The connect-time instructions fade over a long session, so the server also re-grounds the
discipline *at the moment it matters* — a one-line reminder appended to the relevant tool's
result. `mm_preregister` → "the **result** must be sealed too, not just prose"; `mm_verify` /
`mm_audit` / `stack_verify_all` → the *before you state a number* checklist (the language rule,
both directions, scope, seal negatives); `am_record`, `mm_retract`, `mm_power_check`,
`mm_falsifiability_check` → their own one-liner. It fires at the seal/verify/publish beat, not
every turn — a nudge, not noise.

Control it with the `MIRROR_REMINDERS` env var:

| value | behaviour |
|---|---|
| `once` *(default)* | append each reminder only the first time per session |
| `all` | append the reminder on every relevant call |
| `off` | never append |

`once` is the default so a long loop doesn't re-pay for the same reminder every turn
(context hygiene). Override per server:

```json
{ "mcpServers": { "mirror-stack": {
    "command": "mirror-stack-mcp",
    "env": { "MIRROR_REMINDERS": "all" }
} } }
```

### Output compaction (loop context hygiene)

Verification output piles up across a loop's iterations — context rot + cost. The server
compacts it **without hiding signal**: `OK`/`INFO` findings collapse to one summary line, while
every **`WARN`/`FAIL` is kept verbatim** (a dropped negative would defeat the whole point).

| `MIRROR_VERBOSITY` | behaviour |
|---|---|
| `compact` *(default)* | `✓ N check(s) OK: …` + every WARN/FAIL in full |
| `full` | every finding verbatim |

Per-call compaction is the server's job; summarising the running log *across* iterations is the
loop/harness's — the server is stateless per call.

### Hard gate: seal-before-compute / seal-before-publish (opt-in)

Reminders are *soft*. For a *hard* gate, `mm_preflight` returns a GO/BLOCK decision you wire
into the action site:

- `mm_preflight(ledger, claim_id, gate="compute")` → **BLOCK** unless a preregistration *with a
  kill-condition* is sealed. Wire it into your training/experiment launcher so it refuses to
  spend compute on an unsealed claim.
- `mm_preflight(ledger, claim_id, gate="publish", am_ledger=…)` → **BLOCK** unless the *result*
  is also sealed (a retraction, or `am_record(target=claim_id)`). Wire it into a pre-commit /
  pre-publish hook so unresolved claims can't ship.

The MCP only *judges* GO/BLOCK — **your** launcher/hook does the actual blocking. The server
cannot intercept external compute or commits, and that is by design: the discipline is opt-in
(a missing ledger is itself a signal), not something the channel forces on you.

**The enforcer ships with the package.** `mm_preflight` judges; the `mirror-stack-gate` CLI is
the part that actually exits non-zero, so a shell can do the blocking the MCP can't:

```bash
mirror-stack-gate compute --ledger L.jsonl --claim my_claim && python run.py
# exits 1 (run.py never starts) unless a kill-conditioned preregistration is sealed
mirror-stack-gate publish --ledger L.jsonl --claim my_claim --am-ledger A.jsonl
# exits 1 unless the result is sealed too (a retraction or am_record(target=claim))
```

For git, drop in [`hooks/pre-commit.sample`](hooks/pre-commit.sample): it runs the publish gate
so a result can't be committed until its claim is resolved. The CLI and the MCP tool share one
`decide()` (`gate.py`), so they can never drift apart.

## Why this is sound

The tamper-evidence comes from the **hash chain + external witness**, not from the MCP channel —
so exposing the action ledger over MCP is fine: an edit still breaks the chain. This server makes
honesty *easy to prove*; it does not (and cannot) prevent an agent that simply never records.

See **[what the stack guarantees — and the one it can't](https://github.com/bhyi4/measure-mirror/blob/main/stack/PILLARS.md)**
(the four pillars: integrity · non-erasure · falsifiability · verifiability), and the
[Mirror Stack conventions + case study](https://github.com/bhyi4/measure-mirror/tree/main/stack).
