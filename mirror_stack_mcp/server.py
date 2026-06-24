"""🪞🔎🪪 Mirror Stack — unified MCP server.

One MCP server that exposes the whole stack: measure-mirror (claims, incl. standalone probes),
action-mirror (actions + witness), provenance-mirror (artifacts), plus a stack-level
verify-all. Install once, add one MCP server, get the entire stack.

Philosophy unchanged: this does not prevent dishonesty — it makes only honesty provable.
The tamper-evidence comes from the hash chain + external witness, not from the MCP channel,
so exposing action-mirror here is sound (an edit still breaks the chain).

Run:  mirror-stack-mcp        (stdio server)
"""
import hashlib
import json
import os
import re
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from measure_mirror import mm
from actmirror import am
from provmirror import pm

from . import ots_anchor

DISCIPLINE = """\
🪞🔎🪪 MIRROR STACK — discipline for honest measurement (read on connect).

This server does NOT prevent dishonesty; it makes honesty *provable*. The guarantee is the
hash-chained ledger + external witness, not your word. Apply this whenever you measure or make
an empirical claim.

LANGUAGE RULE (most important): separate the TOOL from your JUDGMENT.
  • "mm flagged X" — only when an mm_* probe returned a Finding you can quote.
  • "applying the discipline, I suspect X" — when it is your reasoning.
  Both are valid. NEVER borrow the tool's deterministic credibility for a judgment call.

BEFORE spending compute (seal first):
  1. Preregister the claim WITH a kill-condition — mm_preregister(kill_threshold=...).
     No falsification criterion = unfalsifiable.
  2. Power: is n big enough to detect the effect? mm_power_check (design-time).

BEFORE reporting (verify before speaking):
  3. Fair baseline, not crippled, same budget/data — mm_baseline_fairness.
  4. Gaming line: rewarding the metric is an artifact; only removal/swap is honest — mm_verify(reward_terms).
  5. Both directions — false positive AND false negative. Did you test the REAL target or a stand-in?
  6. Multi-seed + independent reproduction — mm_multiseed_check; am_witness from another agent.
  7. Scope: state what you closed and did NOT close — mm_verify(claimed_scope, tested_scope).
  8. Numeric + multiplicity hygiene — mm_verify (grim, multiple-comparisons).
  9. Self-catch: "too good" is suspect first.
  If an LLM judge is involved, check it too (consistency / bias / swap / transitivity).

THE RECORD: seal claims and actions (am_record target=<claim_id>); anchor externally
(mm_anchor = local snapshot, or mm_anchor_bitcoin = real Bitcoin timestamp via OpenTimestamps —
proves no-backdating, NOT content truth); witness across agents (am_witness). Negatives and retractions are sealed too
(mm_retract) — they cannot be silently deleted. A missing ledger is itself a signal.

Run stack_verify_all before declaring a verdict.

GUARANTEES: integrity · non-erasure · falsifiability · verifiability — NOT independence (a social
property no tool can give). Map: stack/PILLARS.md. The stack also ships an outsider verifier
(mirror-stack-verify) and a hard enforcer (mirror-stack-gate, exits non-zero on BLOCK).
"""

mcp = FastMCP("mirror-stack", instructions=DISCIPLINE)


def _findings(fs):
    return [str(f) for f in fs] if isinstance(fs, list) else str(fs)


# ── signal-preserving output compaction (loop context hygiene) ────────────────
# A long loop agent accumulates verification output → context rot + cost. Compact
# it WITHOUT hiding signal: summarise the OK/INFO findings to one line, keep every
# WARN/FAIL verbatim. A dropped FAIL would be the cardinal sin (a hidden negative).
#   MIRROR_VERBOSITY = compact (default) | full
_VERBOSITY = os.environ.get("MIRROR_VERBOSITY", "compact").strip().lower()


def _compact(findings):
    if _VERBOSITY != "compact" or not isinstance(findings, list):
        return findings
    ok_names, kept = [], []
    for s in findings:
        s = str(s)
        if "level='OK'" in s or 'level="OK"' in s or "level='INFO'" in s or 'level="INFO"' in s:
            m = re.search(r"probe=['\"]([^'\"]+)['\"]", s)
            ok_names.append(m.group(1) if m else "?")
        else:
            kept.append(s)              # WARN / FAIL always verbatim
    out = []
    if ok_names:
        out.append(f"✓ {len(ok_names)} check(s) OK: {', '.join(ok_names)}")
    out.extend(kept)
    return out


# ── in-tool discipline reminders (short, at the relevant beat) ────────────────
# Configurable via the MIRROR_REMINDERS env var:
#   once (default) — append each reminder only the first time per session
#   all            — append the reminder on every relevant call
#   off            — never append
_MODE = os.environ.get("MIRROR_REMINDERS", "once").strip().lower()
_shown: set[str] = set()

_VERIFY = ('🪞 Before you state a number: (1) "mm flagged" only for a Finding above — '
           'reasoning is "I judge"; (2) both directions — false positive AND false '
           'negative; (3) state scope — what you closed and did NOT; (4) seal negatives too.')

REMINDERS = {
    "mm_preregister": "🪞 Sealed. Not done until the RESULT is sealed too — "
        "am_record(target=claim_id) on a verdict, or mm_retract if falsified. Prose doesn't "
        "count. Your kill_condition is the stop-loss; if big compute follows, seal first, then run.",
    "mm_verify": _VERIFY,
    "mm_audit": _VERIFY,
    "stack_verify_all": _VERIFY,
    "am_record": "🪞 Action sealed. If it's a claim's outcome, confirm target=claim_id ties it "
        "back. Payload = measured values, not hoped-for.",
    "mm_retract": "🪞 Negative sealed — it can't be silently deleted now, and dependents go "
        "STALE. A retraction is evidence of honesty, not failure.",
    "mm_power_check": '🪞 Underpowered ≠ "no effect" — only "can\'t detect one". A negative here '
        "is inconclusive; raise n or narrow scope.",
    "mm_falsifiability_check": "🪞 If the kill-condition tripped (FAIL), the claim is falsified by "
        'its OWN criterion → mm_retract it. If it did not trip, that\'s "not refuted", not "proven".',
    "mm_preflight": "🪞 This is a primitive — the MCP only judges GO/BLOCK. YOUR launcher / "
        "pre-commit hook must do the actual blocking; the MCP can't stop external compute or "
        "commits (by design, opt-in).",
}


def _remind(tool, result):
    """Append the tool's discipline reminder to its result, per MIRROR_REMINDERS mode."""
    if _MODE == "off":
        return result
    msg = REMINDERS.get(tool)
    if not msg:
        return result
    if _MODE == "once":
        if tool in _shown:
            return result
        _shown.add(tool)
    if isinstance(result, dict):
        return {**result, "_reminder": msg}
    if isinstance(result, list):
        return result + [msg]
    return f"{result}\n\n{msg}"


# ───────────────────────── 🪞 measure-mirror (claims) ─────────────────────────
@mcp.tool()
def mm_preregister(ledger_path: str, claim_id: str, metric: str, min_n: int = 200,
                   baseline: float = 0.5, pass_threshold: float = 0.6,
                   kill_condition: str | None = None, kill_threshold: dict | None = None,
                   depends_on: list[str] | None = None) -> dict:
    """Seal a claim BEFORE measuring (preregistration). kill_condition/threshold = what falsifies it."""
    return _remind("mm_preregister", mm.preregister(
        ledger_path, claim_id, metric=metric, min_n=min_n, baseline=baseline,
        pass_threshold=pass_threshold, kill_condition=kill_condition,
        kill_threshold=kill_threshold, depends_on=depends_on))


@mcp.tool()
def mm_verify(ledger_path: str, data: dict, groups: list[str] | None = None) -> list[str]:
    """Umbrella verify: runs every probe whose input key is present in `data` (acc/n/seed_results/scores/...)."""
    return _remind("mm_verify", _compact(_findings(mm.verify(ledger_path, data, groups=groups))))


@mcp.tool()
def mm_audit(ledger_path: str, claim_id: str, reported_metric: str, reported_acc: float,
             n: int, baseline: float | None = None) -> list[str]:
    """Audit a reported result against its sealed registration (CI, direction, ledger integrity)."""
    return _remind("mm_audit", _compact(_findings(mm.audit(
        ledger_path, claim_id, reported_metric=reported_metric,
        reported_acc=reported_acc, n=n, baseline=baseline))))


@mcp.tool()
def mm_power_check(n: int, baseline: float, min_detectable_effect: float = 0.05,
                   target_power: float = 0.8) -> str:
    """False-negative guard: is n big enough to detect the minimum effect? (design-time)."""
    return _remind("mm_power_check", str(mm.power_check(
        n, baseline, min_detectable_effect=min_detectable_effect, target_power=target_power)))


@mcp.tool()
def mm_falsifiability_check(ledger_path: str, claim_id: str,
                            reported_acc: float | None = None) -> str:
    """Popper gate: is a kill-condition registered, and did the result trip it?"""
    return _remind("mm_falsifiability_check",
                   str(mm.falsifiability_check(ledger_path, claim_id, reported_acc=reported_acc)))


@mcp.tool()
def mm_leakage_check(train_items: list, test_items: list) -> str:
    """Detect train∩test contamination via hash intersection."""
    return str(mm.leakage_check(train_items, test_items))


@mcp.tool()
def mm_multiseed_check(seed_results: list[float], baseline: float = 0.5) -> str:
    """Flag unstable signal / lucky seed across multiple runs."""
    return str(mm.multiseed_check(seed_results, baseline=baseline))


@mcp.tool()
def mm_retract(ledger_path: str, claim_id: str, reason: str) -> dict:
    """Append a chain-linked retraction (cannot be silently deleted; dependents go STALE)."""
    return _remind("mm_retract", mm.retract(ledger_path, claim_id, reason))


@mcp.tool()
def mm_anchor(ledger_path: str) -> dict:
    """Tamper-evident snapshot (entry_count, head_seal, file hash) to store OUTSIDE the ledger."""
    return mm.anchor(ledger_path)


@mcp.tool()
def mm_anchor_bitcoin(ledger_paths: list[str], out_dir: str) -> dict:
    """Real external anchor (L3): timestamp ledger HEADS into Bitcoin via OpenTimestamps.

    Upgrades mm_anchor from a LOCAL snapshot to an EXTERNAL clock — proves the heads existed
    before a Bitcoin block (no backdating / no silent rewrite), independent of you AND of GitHub,
    for a witness who may arrive later. Needs the `ots` CLI (pip install opentimestamps-client) +
    network. Returns state='pending' — call mm_anchor_upgrade in ~1-3h, then mm_anchor_verify.
    Honest scope: proves precedence of the record, NOT the truth of its content (GIGO)."""
    return _remind("mm_anchor_bitcoin", ots_anchor.stamp(ledger_paths, out_dir))


@mcp.tool()
def mm_anchor_upgrade(ots_path: str) -> dict:
    """Retrieve the Bitcoin block attestation for a pending .ots proof (run ~1-3h after stamping).
    Returns state='bitcoin_confirmed' with block_height once a calendar has committed to a block,
    else 'pending' (retry later)."""
    return ots_anchor.upgrade(ots_path)


@mcp.tool()
def mm_anchor_verify(ots_path: str, explorer: str = "https://blockstream.info/api") -> dict:
    """Verify a Bitcoin-anchored proof WITHOUT a local Bitcoin node, by cross-checking the block
    merkle root against a public explorer. Returns block height, block time, and whether the
    explorer's merkle root matches the proof's (independent confirmation, not our own word)."""
    return ots_anchor.verify(ots_path, explorer=explorer)


@mcp.tool()
def mm_preflight(ledger_path: str, claim_id: str, gate: str = "compute",
                 am_ledger: str | None = None, reported_acc: float | None = None) -> dict:
    """GO/BLOCK gate primitive — wire it into a compute launcher or a pre-publish/commit hook.

    gate="compute": GO only if a sealed preregistration WITH a kill-condition exists for
                    claim_id (enforces seal-before-compute).
    gate="publish": additionally GO only if a RESOLUTION is sealed — a retraction in
                    ledger_path, or an am_record(target=claim_id) in am_ledger.
    This is a PRIMITIVE: the MCP returns GO/BLOCK; YOUR script must do the actual blocking
    (the MCP cannot intercept external compute or commits — that is by design). The shell
    enforcer that DOES exit non-zero is `mirror-stack-gate` (mirror_stack_mcp.gate); both
    share the same decision logic so they can never drift apart.
    """
    from . import gate as _gate
    return _remind("mm_preflight", _gate.decide(ledger_path, claim_id, gate=gate,
                                                am_ledger=am_ledger, reported_acc=reported_acc))


# ───────────────────────── 🪪 action-mirror (actions) ─────────────────────────
@mcp.tool()
def am_record(ledger_path: str, agent: str, action: str, target: str | None = None,
              payload: dict | None = None) -> dict:
    """Seal one agent action. Set target=<claim_id> to tie the action to a claim (J1)."""
    return _remind("am_record",
                   am.record(ledger_path, agent=agent, action=action, target=target, payload=payload))


@mcp.tool()
def am_witness(my_ledger: str, peer_ledger: str, peer_name: str) -> dict:
    """Pin a peer ledger's head into mine (J3). Catches whole-ledger replacement that chains miss."""
    return am.witness_peer(my_ledger, peer_ledger, peer_name=peer_name)


@mcp.tool()
def am_verify(ledger_path: str) -> list[str]:
    """Verify an action ledger's hash chain (edits/deletions/insertions detected)."""
    return _compact(_findings(am.verify_chain(ledger_path)))


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

    return _remind("stack_verify_all",
                   {"verdict": "ALL OK" if ok else "FAILURES", "ok": ok,
                    "checks": out, "passed": sum(c["ok"] for c in out), "total": len(out)})


def main():
    mcp.run()


if __name__ == "__main__":
    main()
