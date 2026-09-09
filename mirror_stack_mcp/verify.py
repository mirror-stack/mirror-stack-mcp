#!/usr/bin/env python3
"""🪞🔎🪪 mirror-stack-verify — one command for an OUTSIDER to confirm a ledger,
without trusting us, without an MCP client, without config.

  mirror-stack-verify LEDGER.jsonl [--ots PROOF.ots] [--explorer URL]

Verification scope:

  1. integrity — recompute both links AND content hashes from one ledger snapshot.
                 No network; stdlib-only MIRROR-SPEC verification. Optional identity
                 signatures are NOT verified; legacy 16-hex seals remain weaker.
  2. bitcoin — if an OpenTimestamps proof is given, cross-check its Bitcoin block
               against a PUBLIC block explorer. This CLI does NOT check binding
               between that proof and this ledger, so ledger precedence remains
               UNVERIFIED. (needs the `ots` CLI + network.)

Honest scope: this checks hash INTEGRITY, not external-clock PRECEDENCE.
It does NOT prove the content is true, nor that an independent judge witnessed it.
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
    if a.ots:
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
    print(f"=== verdict: {'CONFIRMED' if good else 'NOT CONFIRMED'} (hash integrity) ===")
    print("scope: hash integrity only; NOT author identity, content truth or independent reproduction.")
    print("external time: ledger precedence UNVERIFIED — "
          "a supplied Bitcoin proof is checked separately; ledger-to-proof binding is not checked here.")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
