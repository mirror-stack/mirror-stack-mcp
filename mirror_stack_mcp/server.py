"""🪞🔎🪪 Mirror Stack — unified MCP server.

One MCP server that exposes the whole stack to an agent: measure-mirror (claims),
action-mirror (actions + witness), provenance-mirror (artifacts), plus a stack-level
verify-all. Install once, add one MCP server, get the entire stack.

Philosophy unchanged: this does not prevent dishonesty — it makes only honesty provable.
The tamper-evidence comes from the hash chain + external witness, not from the MCP channel,
so exposing action-mirror here is sound (an edit still breaks the chain).

Run:  mirror-stack-mcp        (stdio server)
"""
import hashlib
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from measure_mirror import mm
from actmirror import am
from provmirror import pm

mcp = FastMCP("mirror-stack")


def _findings(fs):
    return [str(f) for f in fs] if isinstance(fs, list) else str(fs)


# ───────────────────────── 🪞 measure-mirror (claims) ─────────────────────────
@mcp.tool()
def mm_preregister(ledger_path: str, claim_id: str, metric: str, min_n: int = 200,
                   baseline: float = 0.5, pass_threshold: float = 0.6,
                   kill_condition: str | None = None, kill_threshold: dict | None = None,
                   depends_on: list[str] | None = None) -> dict:
    """Seal a claim BEFORE measuring (preregistration). kill_condition/threshold = what falsifies it."""
    return mm.preregister(ledger_path, claim_id, metric=metric, min_n=min_n, baseline=baseline,
                          pass_threshold=pass_threshold, kill_condition=kill_condition,
                          kill_threshold=kill_threshold, depends_on=depends_on)


@mcp.tool()
def mm_verify(ledger_path: str, data: dict, groups: list[str] | None = None) -> list[str]:
    """Umbrella verify: runs every probe whose input key is present in `data` (acc/n/seed_results/scores/...)."""
    return _findings(mm.verify(ledger_path, data, groups=groups))


@mcp.tool()
def mm_audit(ledger_path: str, claim_id: str, reported_metric: str, reported_acc: float,
             n: int, baseline: float | None = None) -> list[str]:
    """Audit a reported result against its sealed registration (CI, direction, ledger integrity)."""
    return _findings(mm.audit(ledger_path, claim_id, reported_metric=reported_metric,
                              reported_acc=reported_acc, n=n, baseline=baseline))


@mcp.tool()
def mm_retract(ledger_path: str, claim_id: str, reason: str) -> dict:
    """Append a chain-linked retraction (cannot be silently deleted; dependents go STALE)."""
    return mm.retract(ledger_path, claim_id, reason)


@mcp.tool()
def mm_anchor(ledger_path: str) -> dict:
    """Tamper-evident snapshot (entry_count, head_seal, file hash) to store OUTSIDE the ledger."""
    return mm.anchor(ledger_path)


# ───────────────────────── 🪪 action-mirror (actions) ─────────────────────────
@mcp.tool()
def am_record(ledger_path: str, agent: str, action: str, target: str | None = None,
              payload: dict | None = None) -> dict:
    """Seal one agent action. Set target=<claim_id> to tie the action to a claim (J1)."""
    return am.record(ledger_path, agent=agent, action=action, target=target, payload=payload)


@mcp.tool()
def am_witness(my_ledger: str, peer_ledger: str, peer_name: str) -> dict:
    """Pin a peer ledger's head into mine (J3). Catches whole-ledger replacement that chains miss."""
    return am.witness_peer(my_ledger, peer_ledger, peer_name=peer_name)


@mcp.tool()
def am_verify(ledger_path: str) -> list[str]:
    """Verify an action ledger's hash chain (edits/deletions/insertions detected)."""
    return _findings(am.verify_chain(ledger_path))


# ───────────────────────── 🔎 provenance-mirror (artifacts) ────────────────────
@mcp.tool()
def pm_verify(file_path: str, ledger_path: str = "pm_ledger.jsonl",
              origin: str | None = None) -> dict:
    """Verify a content file's provenance/integrity across 5 signals (a verifier, not a detector)."""
    return pm.verify(file_path, ledger_path=ledger_path, origin=origin)


# ───────────────────────── 🪞🔎🪪 stack-level ─────────────────────────────────
@mcp.tool()
def stack_verify_all(mm_ledger: str, anchor_dir: str | None = None,
                     am_ledger: str | None = None, am_peer_name: str | None = None) -> dict:
    """Verify the whole stack in one call: mm chain (L1) + anchors (L3) + cross-witness (L2)."""
    out, ok = [], True

    def add(level, layer, name, msg):
        nonlocal ok
        ok = ok and level
        out.append({"ok": level, "layer": layer, "name": name, "msg": msg})

    bad = [str(f) for f in mm.verify_chain(mm_ledger)
           if getattr(f, "level", "OK") not in ("OK", "INFO")]
    add(not bad, "L1 chain", Path(mm_ledger).name, "seals valid" if not bad else str(bad))

    if anchor_dir:
        for af in sorted(Path(anchor_dir).glob("anchor_*.json")):
            a = json.loads(af.read_text())
            lp = Path(a["ledger_path"])
            if not lp.exists():
                lp = af.parent / lp.name
            cur = hashlib.sha256(lp.read_bytes()).hexdigest() if lp.exists() else ""
            if cur == a["anchor_hash"]:
                add(True, "L3 anchor", af.name, "intact")
            else:
                entries = [json.loads(l) for l in lp.read_text().splitlines() if l.strip()] if lp.exists() else []
                n = a["entry_count"]
                extended = len(entries) >= n and str(entries[n - 1].get("seal", "")) == a["head_seal"]
                add(extended, "L3 anchor", af.name, "extended" if extended else "REPLACED?")

    if am_ledger and am_peer_name:
        f = am.verify_peer(am_ledger, mm_ledger, peer_name=am_peer_name)
        good = getattr(f, "level", "OK") in ("OK", "INFO")
        add(good, "L2 witness", am_peer_name, str(f))

    return {"verdict": "ALL OK" if ok else "FAILURES", "ok": ok,
            "checks": out, "passed": sum(c["ok"] for c in out), "total": len(out)}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
