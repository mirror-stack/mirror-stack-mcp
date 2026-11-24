#!/usr/bin/env python3
"""🪞🔎🪪 mirror-stack-verify — one command for an OUTSIDER to confirm a ledger,
without trusting us, without an MCP client, without config.

  mirror-stack-verify LEDGER.jsonl [--ots PROOF.ots [--manifest MANIFEST.json]] [--explorer URL]

Verification scope:

  1. integrity — recompute both links AND content hashes from one ledger snapshot.
                 No network; stdlib-only MIRROR-SPEC verification. Optional identity
                 signatures are NOT verified; legacy 16-hex seals remain weaker.
  2. bitcoin — if an OpenTimestamps proof is given, cross-check its EARLIEST Bitcoin
               block against a PUBLIC block explorer. (needs the `ots` CLI + network.)
  3. binding — with --manifest as well: the proof must stamp that manifest (sha256),
               and the manifest must pin a prefix of THIS ledger. Only then are the
               pinned lines reported as existing before the block (EXTERNAL_TIME).
               Without --manifest, ledger precedence remains UNVERIFIED.

Honest scope: without a bound proof this checks hash INTEGRITY only, not
external-clock PRECEDENCE. It never proves the content is true, nor that an independent judge witnessed it.
"""
import argparse
import sys
from .integrity import read_verified

OK, FAIL, WARN = "✅", "❌", "⚠️"


def check_chain(path):
    """Format-agnostic prev_seal→seal linkage. Returns (ok, message).

    Single source: delegates to measure-mirror's canonical `mm.linkage_check`
    (stdlib-only, zero-dep) rather than keeping a parallel copy — measure-mirror
    is already a hard dependency of this package, and a second copy had drifted
    (it reported malformed JSON as "unreadable"). One definition = no drift.
    """
    from measure_mirror.mm import linkage_check
    ok, message, _entries = linkage_check(path)
    return ok, message


def check_bitcoin(ots_path, explorer):
    """Cross-check an OTS proof's Bitcoin block on a public explorer. (ok, dict)."""
    try:
        from . import ots_anchor
    except ImportError:                       # running as a loose script, not the package
        import ots_anchor                      # type: ignore
    kw = {"explorer": explorer} if explorer else {}
    res = ots_anchor.verify(ots_path, **kw)
    return bool(res.get("verified")), res


def main(argv=None):
    ap = argparse.ArgumentParser(prog="mirror-stack-verify", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ledger", help="path to a mirror ledger (.jsonl)")
    ap.add_argument("--ots", help="OpenTimestamps proof (.ots) for the Bitcoin cross-check")
    ap.add_argument("--manifest", help="the anchor manifest the --ots proof stamps; binds the "
                    "proof to this ledger so precedence can be reported")
    ap.add_argument("--explorer", help="block explorer API base (default: blockstream)")
    a = ap.parse_args(argv)

    print("=== 🪞🔎🪪 mirror-stack-verify (you recompute — you don't trust us) ===")
    entries, error = read_verified(a.ledger)
    ok_chain = error is None
    msg = error or f"{len(entries)} entries: linkage and SHA-256 seals recomputed"
    print(f"{OK if ok_chain else FAIL} [HASH_RECOMPUTED] {msg}")
    if entries and any(len(e["seal"]) == 16 for e in entries):
        print(f"{WARN} legacy 16-hex seals: weaker collision resistance")

    ok_btc = True
    bound = None
    if a.manifest and not a.ots:
        print(f"{FAIL} [binding] --manifest needs --ots (the proof that stamps it)")
        ok_btc = False
    elif a.ots and a.manifest:
        try:
            from . import ots_anchor
            kw = {"explorer": a.explorer} if a.explorer else {}
            bound = ots_anchor.bind(a.ledger, a.manifest, a.ots, **kw)
        except Exception as e:                # ots CLI missing / unreadable files
            bound = {"bound": False, "bitcoin": {}, "note": f"binding check unavailable: {e}"}
        res = bound.get("bitcoin") or {}
        if res.get("block_height"):
            print(f"{OK if res.get('verified') else WARN} [bitcoin] earliest block "
                  f"{res['block_height']} @ {res.get('block_time_utc')} — "
                  f"{'merkle root matches the explorer' if res.get('verified') else res.get('note', 'not confirmed')}")
        print(f"{OK if bound.get('proof_matches_manifest') else FAIL} [binding] proof stamps the manifest")
        if bound.get("proof_matches_manifest"):
            print(f"{OK if bound.get('manifest_pins_ledger') else FAIL} [binding] manifest pins "
                  f"this ledger's first {bound.get('pinned_lines', '?')} line(s)")
        if bound.get("bound"):
            n_later = len(bound.get("uncovered_entries", []))
            print(f"{OK} [EXTERNAL_TIME] {bound['proves']}")
            pre = [r["claim_id"] for r in bound.get("covered_entries", [])
                   if r.get("type") == "preregistration" and r.get("claim_id")]
            if pre:
                shown = ", ".join(pre[:10]) + (f" … (+{len(pre) - 10})" if len(pre) > 10 else "")
                print(f"{OK} [EXTERNAL_TIME] preregistrations covered: {shown}")
            if n_later:
                print(f"{WARN} [EXTERNAL_TIME] {n_later} later line(s) are NOT covered by this proof")
        else:
            print(f"{FAIL} [EXTERNAL_TIME] not established — {bound.get('note')}")
        ok_btc = bool(bound.get("bound"))
    elif a.ots:
        try:
            ok_btc, res = check_bitcoin(a.ots, a.explorer)
        except Exception as e:                # ots CLI missing / network — be explicit
            ok_btc, res = False, {"note": f"bitcoin check unavailable: {e}"}
        if res.get("block_height"):
            print(f"{OK if ok_btc else WARN} [bitcoin] block {res['block_height']} "
                  f"@ {res.get('block_time_utc')} — "
                  f"{'merkle root matches the explorer' if ok_btc else res.get('note', 'not confirmed')}")
        else:
            print(f"{WARN} [bitcoin] {res.get('note', 'no Bitcoin attestation')}")
    else:
        print(f"{WARN} [bitcoin] skipped — pass --ots PROOF.ots for the external-clock check")

    good = ok_chain and ok_btc
    scope = "hash integrity + external time" if bound and bound.get("bound") else "hash integrity"
    print(f"=== verdict: {'CONFIRMED' if good else 'NOT CONFIRMED'} ({scope}) ===")
    print("scope: NOT author identity, content truth or independent reproduction.")
    if bound and bound.get("bound"):
        print("external time: the pinned lines existed before the Bitcoin block above; "
              "later lines are not covered.")
    else:
        print("external time: ledger precedence UNVERIFIED — "
              "pass --ots PROOF.ots --manifest MANIFEST.json to bind a proof to this ledger.")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
