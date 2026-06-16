# ⏱️🔗 Bitcoin anchoring (OpenTimestamps) — full guide

> Upgrade the L3 (external anchor) layer from a *local snapshot* to a **real external clock**:
> prove a ledger-head state existed before a Bitcoin block — independent of you and of GitHub —
> for a verifier who may arrive later.

## What it proves / does not prove (read first)

| | |
|---|---|
| ✅ **proves** | your ledger heads existed **before a Bitcoin block time** → no backdating, no silent rewrite. Verifiable by anyone, forever. |
| ❌ does **not** prove | the **content is true** (GIGO — an early-sealed lie is still a lie). |
| ❌ does **not** provide | an external **judging** witness — that is the social layer (L2). The clock is run *now* for a verifier who comes *later*. |

Cryptography doesn't **block** dishonesty; it makes a rewrite **detectable**. Two different jobs:
**Bitcoin = "can't silently rewind the record"**, **another operator = "can catch a false claim"**.
This tool is the first half.

## Where it sits — the L1 / L2 / L3 model

`stack_verify_all` checks three layers:

- **L1 — hash chain** (`mm_*`): you can't edit an old entry without breaking every later seal.
- **L2 — cross-witness** (`am_witness`): another operator co-signs your head — catches whole-file replacement.
- **L3 — external anchor**: **this.** `mm_anchor` was a *local* snapshot; `mm_anchor_bitcoin` makes L3 a real Bitcoin timestamp.

## Install

```bash
pip install "mirror-stack-mcp[bitcoin] @ git+https://github.com/mirror-stack/mirror-stack-mcp"
```

The `[bitcoin]` extra pulls `opentimestamps-client` (the `ots` CLI). You need **network access**
to the public OpenTimestamps calendars at stamp/upgrade time. Verification needs only a public
block explorer — **no local Bitcoin node**.

## Use it (MCP tools)

### 1. Stamp — submit the heads to Bitcoin

```
mm_anchor_bitcoin(
    ledger_paths = ["/data/.../seara.jsonl", "/data/.../action.jsonl", ...],
    out_dir      = "/data/.../anchors_ots",
)
```

Builds `manifest_<ts>.json` (each ledger's sha256 + head seal), submits it to 4+ calendar
servers, writes `manifest_<ts>.json.ots`. Returns:

```json
{ "ok": true, "manifest": ".../manifest_20260616.json",
  "manifest_sha256": "ec55147a…", "ots_proof": ".../manifest_20260616.json.ots",
  "state": "pending_bitcoin_confirmation",
  "honest_scope": "proves no-backdating of the heads; NOT content truth (GIGO)" }
```

`state` is **pending** — the calendars batch many requests and commit one Bitcoin transaction
periodically (~hourly).

### 2. Upgrade — pull the Bitcoin attestation (~1–3h later)

```
mm_anchor_upgrade(ots_path = ".../manifest_20260616.json.ots")
```

- still pending → `{ "state": "pending", "block_height": null }` (retry later)
- confirmed → `{ "state": "bitcoin_confirmed", "block_height": 953923 }`

There is no deadline — calendars retain the proof; just retry until confirmed.

### 3. Verify — independent cross-check (no node)

```
mm_anchor_verify(ots_path = ".../manifest_20260616.json.ots")
```

Extracts the block height + expected merkle root from the proof, fetches that block from a public
explorer (default `blockstream.info`), and compares:

```json
{ "verified": true, "block_height": 953923,
  "expected_merkle_root": "da52ff40…", "explorer_merkle_root": "da52ff40…",
  "block_time_utc": "2026-06-16T09:51:37Z", "explorer": "https://blockstream.info/api",
  "proves": "ledger heads existed before this Bitcoin block (no backdating)",
  "does_not_prove": ["content truth (GIGO)", "an external judging witness exists"] }
```

`verified: true` means the explorer's merkle root for that block matched the proof's — so the
confirmation is **not our own word**. Anyone can repeat it:

```bash
curl https://blockstream.info/api/block-height/953923   # → block hash
curl https://blockstream.info/api/block/<hash>          # → merkle_root, compare
```

## CLI fallback (no MCP)

The same thing with plain `ots`:

```bash
# 1. stamp a manifest (or any file)
ots stamp manifest.json
# 2. ~1-3h later
ots upgrade manifest.json.ots
# 3. verify — needs a Bitcoin node; OR cross-check the block merkle root on an explorer (above)
ots info manifest.json.ots        # shows BitcoinBlockHeaderAttestation(<height>) + merkle root
```

A self-contained re-runnable script (`ots_anchor.sh`) lives alongside the standard ledgers in the
[Mirror Stack conventions](https://github.com/bhyi4/measure-mirror/tree/main/stack).

## Notes

- **`ots verify` vs explorer**: stock `ots verify` wants a local Bitcoin node to read the block
  header. `mm_anchor_verify` deliberately uses a public explorer instead, so a fresh user with no
  node can still confirm. If you *do* run a node, `ots verify` is the fully-trustless path.
- **What to stamp**: stamp the *heads* (a manifest), not the whole ledgers — the proof pins the
  exact head seal at time T, which is all that's needed to detect a later rewrite.
- **Re-anchor periodically**: each stamp covers state *up to T*; new entries after T are covered by
  the next stamp. Run it on a cadence (e.g. per milestone, or a cron).
