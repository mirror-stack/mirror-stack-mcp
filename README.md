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

## Tools (15)

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
| `mm_anchor` | 🪞 | tamper-evident snapshot to store outside the ledger |
| `mm_preflight` | 🪞 | GO/BLOCK gate primitive — wire into a compute launcher / pre-commit hook |
| `am_record` | 🪪 actions | seal an action; `target=<claim_id>` ties it to a claim |
| `am_witness` | 🪪 | pin a peer's ledger head (catches whole-file replacement) |
| `am_verify` | 🪪 | verify an action ledger's hash chain |
| `pm_verify` | 🔎 provenance | verify a file's provenance across 5 signals |
| `stack_verify_all` | 🪞🔎🪪 | whole stack in one call: chain (L1) + anchors (L3) + witness (L2) |

(More granular `measure-mirror` probes are reachable via `mm_verify` — it dispatches by data key.)

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
| `all` *(default)* | append the reminder on every relevant call |
| `once` | append each reminder only the first time per session |
| `off` | never append |

```json
{ "mcpServers": { "mirror-stack": {
    "command": "mirror-stack-mcp",
    "env": { "MIRROR_REMINDERS": "once" }
} } }
```

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

## Why this is sound

The tamper-evidence comes from the **hash chain + external witness**, not from the MCP channel —
so exposing the action ledger over MCP is fine: an edit still breaks the chain. This server makes
honesty *easy to prove*; it does not (and cannot) prevent an agent that simply never records.

See the [Mirror Stack conventions + case study](https://github.com/bhyi4/measure-mirror/tree/main/stack).
