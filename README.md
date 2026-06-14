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

## Tools (14)

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

## Why this is sound

The tamper-evidence comes from the **hash chain + external witness**, not from the MCP channel —
so exposing the action ledger over MCP is fine: an edit still breaks the chain. This server makes
honesty *easy to prove*; it does not (and cannot) prevent an agent that simply never records.

See the [Mirror Stack conventions + case study](https://github.com/bhyi4/measure-mirror/tree/main/stack).
