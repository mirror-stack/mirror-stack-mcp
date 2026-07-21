#!/usr/bin/env python3
"""⛔ GO/BLOCK gate — the *enforceable* core of mm_preflight.

mm_preflight (the MCP tool) only JUDGES; it cannot stop external compute or a git
commit. This module is the single source of truth for that judgement AND the actual
enforcer: `mirror-stack-gate` exits non-zero on BLOCK, so you can wire the
discipline into a real workflow that the MCP can't reach:

  compute (seal-before-compute):
      mirror-stack-gate compute --ledger L.jsonl --claim my_claim && python run.py
      # exits 1 unless a preregistration WITH a kill-condition is sealed for my_claim

  publish (resolution-before-publish), e.g. a git pre-commit hook:
      mirror-stack-gate publish --ledger L.jsonl --claim my_claim --am-ledger A.jsonl
      # exits 1 unless a retraction or an am_record(target=my_claim) is sealed

The same `decide()` backs server.mm_preflight, so the agent-facing tool and the
shell enforcer can never drift apart.
"""
import json
import os
import sys


def scan_claim(ledger_path, claim_id):
    """Return (prereg_entry_or_None, retracted_bool, leaked_entry_or_None) for claim_id.

    leaked_entry is a preregistration that carries NO kill fields but whose `metric`
    reads like a kill-condition — i.e. the criterion leaked into the wrong field from a
    malformed call. It is not a valid prereg (compute stays BLOCKed), but naming it lets
    the gate report the real reason instead of a misleading 'no preregistration'.
    """
    prereg, retracted, leaked = None, False, None
    if os.path.exists(ledger_path):
        with open(ledger_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("claim_id") != claim_id:
                    continue
                if e.get("_type") == "retraction":
                    retracted = True
                elif e.get("_type") is None and ("kill_threshold" in e or "kill_condition" in e) \
                        and e.get("metric") != "protocol_amendment":
                    prereg = e
                elif e.get("_type") is None and e.get("metric") not in (None, "protocol_amendment"):
                    from measure_mirror import mm
                    if leaked is None and mm._looks_like_kill_prose(e.get("metric", "")):
                        leaked = e
    return prereg, retracted, leaked


def decide(ledger_path, claim_id, gate="compute", am_ledger=None, reported_acc=None):
    """Pure GO/BLOCK decision. Returns {decision, gate, claim_id, reasons, checks}."""
    prereg, retracted, leaked = scan_claim(ledger_path, claim_id)
    checks: list[str] = []

    def out(decision, reasons):
        return {"decision": decision, "gate": gate, "claim_id": claim_id,
                "reasons": reasons, "checks": checks}

    if prereg is None:
        if leaked is not None:
            return out("BLOCK", [
                "a preregistration exists but its kill-condition leaked into the `metric` "
                f"field ({str(leaked.get('metric'))[:60]!r}...) — the automated checks can't "
                "parse it. Re-seal under a NEW claim_id with the criterion in kill_condition= "
                "(mm_prereg_lint pinpoints this)."])
        return out("BLOCK", ["no sealed preregistration for this claim — seal one "
                             "(mm_preregister with a kill-condition) before proceeding"])
    has_kill = bool(prereg.get("kill_threshold") or prereg.get("kill_condition"))
    checks.append("preregistration: sealed" + ("" if has_kill else " (NO kill-condition)"))

    if gate == "compute":
        if not has_kill:
            return out("BLOCK", ["preregistration has no kill-condition (unfalsifiable) — "
                                 "add one before spending compute"])
        # Seal-quality lint: a FAIL (e.g. a pass bar at/below chance) means the
        # automated checks can't do their job — compute would be spent against a
        # meaningless bar. WARN/INFO inform but don't block.
        from measure_mirror import mm
        lint = mm._preseal_lint(prereg)
        fails = [f for f in lint if f.level == "FAIL"]
        warns = [f for f in lint if f.level == "WARN"]
        if warns:
            checks.append("prereg-lint: " + "; ".join(f.msg for f in warns))
        if fails:
            return out("BLOCK", ["prereg-lint FAIL — " + " | ".join(f.msg for f in fails)])
        checks.append("prereg-lint: no FAIL")
        return out("GO", ["sealed preregistration with a kill-condition is present"])

    if gate == "publish":
        resolved = retracted
        if retracted:
            checks.append("resolution: retraction sealed")
        if not resolved and am_ledger and os.path.exists(am_ledger):
            with open(am_ledger, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        a = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if a.get("_type") == "action" and a.get("target") == claim_id:
                        resolved = True
                        checks.append("resolution: am_record(target) sealed")
                        break
        if not resolved:
            return out("BLOCK", ["no sealed resolution — seal the result "
                                 "(am_record target=claim_id, or mm_retract) before publishing. "
                                 "Prose doesn't count."])
        if reported_acc is not None:
            from measure_mirror import mm
            checks.append(str(mm.falsifiability_check(ledger_path, claim_id, reported_acc=reported_acc)))
        return out("GO", ["sealed preregistration + sealed resolution"])

    return out("BLOCK", [f"unknown gate '{gate}' — use 'compute' or 'publish'"])


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="mirror-stack-gate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("gate", choices=["compute", "publish"])
    ap.add_argument("--ledger", required=True, help="claims ledger (.jsonl)")
    ap.add_argument("--claim", required=True, help="claim_id to gate on")
    ap.add_argument("--am-ledger", help="action ledger (publish gate: where am_record resolutions live)")
    ap.add_argument("--acc", type=float, help="reported accuracy (publish gate: also runs falsifiability)")
    a = ap.parse_args(argv)

    r = decide(a.ledger, a.claim, gate=a.gate, am_ledger=a.am_ledger, reported_acc=a.acc)
    print(f"{'✅ GO' if r['decision'] == 'GO' else '⛔ BLOCK'} [{r['gate']}] {r['claim_id']}")
    for c in r["checks"]:
        print(f"   · {c}")
    for reason in r["reasons"]:
        print(f"   → {reason}")
    return 0 if r["decision"] == "GO" else 1


if __name__ == "__main__":
    sys.exit(main())
