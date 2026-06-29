#!/usr/bin/env python3
"""🪞🔎🪪 mirror-stack-verify — one command for an OUTSIDER to confirm a ledger,
without trusting us, without an MCP client, without config.

  mirror-stack-verify LEDGER.jsonl [--ots PROOF.ots] [--explorer URL]

Two independent confirmations, both reproducible by anyone:

  1. chain   — recompute the prev_seal→seal linkage of the ledger. A break means an
               entry was inserted, deleted, or reordered after sealing. (no network,
               stdlib only — works on any mirror ledger.)
  2. bitcoin — if an OpenTimestamps proof is given, cross-check its Bitcoin block
               against a PUBLIC block explorer: the ledger head existed before that
               block's time. This is the "don't trust us" part — the clock is
               Bitcoin's and the lookup is a third party's, not ours. (needs the
               `ots` CLI + network.)

Honest scope: this proves INTEGRITY (not tampered) and PRECEDENCE (not backdated).
It does NOT prove the content is true, nor that an independent judge witnessed it.
"""
import argparse
import sys

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
    ok_chain, msg = check_chain(a.ledger)
    print(f"{OK if ok_chain else FAIL} [chain]   {msg}")

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
    print(f"=== verdict: {'CONFIRMED' if good else 'NOT CONFIRMED'} "
          f"(integrity{' + precedence' if a.ots and ok_btc else ''}) ===")
    print("scope: proves not-tampered" + (" + not-backdated" if a.ots else "") +
          "; NOT content truth, NOT an independent judging witness.")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
