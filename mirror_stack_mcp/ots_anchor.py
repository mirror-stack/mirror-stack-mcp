"""⏱️🔗 OTS (OpenTimestamps) Bitcoin anchoring for mirror-stack ledgers.

Upgrades L3 (external anchor) from a LOCAL snapshot to a REAL external clock: prove a
ledger-head state existed before a Bitcoin block — no backdating / no silent rewrite —
independently of you AND of GitHub.

HONEST SCOPE (read before reporting):
  ✓ proves: the ledger HEADS existed before a given Bitcoin block time (precedence /
            tamper-evidence against backdating), verifiable by anyone.
  ✗ does NOT prove: the CONTENT is true (GIGO — an early-sealed lie is still a lie);
            that an external *judging* witness exists (that is a social problem, L2).

Requires the `ots` CLI (`pip install opentimestamps-client`) and network access to the
public OpenTimestamps calendars. VERIFICATION cross-checks a public block explorer, so you
do NOT need a local Bitcoin node.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import urllib.request
from pathlib import Path

OTS = os.environ.get("OTS_BIN", "ots")
DEFAULT_EXPLORER = os.environ.get("OTS_EXPLORER", "https://blockstream.info/api")
_BLOCK_RE = re.compile(r"BitcoinBlockHeaderAttestation\((\d+)\)")
_ROOT_RE = re.compile(r"Bitcoin block merkle root ([0-9a-fA-F]{64})")


def _sha256(p) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _head_seal(p) -> str | None:
    head = None
    for line in Path(p).read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
            head = d.get("seal", d.get("head_seal", head))
        except json.JSONDecodeError:
            pass
    return head


def build_manifest(ledger_paths: list[str], out_dir: str) -> tuple[str, str]:
    """Write a manifest pinning each ledger's sha256 + head seal. Returns (path, sha256)."""
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    for f in ledger_paths:
        rows.append({"ledger": os.path.basename(f), "path": str(f),
                     "bytes": Path(f).stat().st_size, "sha256": _sha256(f),
                     "head_seal": _head_seal(f)})
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    man = os.path.join(out_dir, f"manifest_{stamp}.json")
    manifest = {"_type": "ots_anchor_manifest",
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "purpose": "Bitcoin timestamp of mirror-stack ledger heads — "
                           "proves no-backdating, NOT content truth.",
                "ledger_count": len(rows), "ledgers": rows}
    Path(man).write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return man, _sha256(man)


def _info(ots_path: str) -> str:
    return subprocess.run([OTS, "info", ots_path], capture_output=True,
                          text=True, timeout=60).stdout


def stamp(ledger_paths: list[str], out_dir: str) -> dict:
    """Build a manifest of the ledger heads and submit it to the OTS Bitcoin calendars."""
    if not ledger_paths:
        return {"ok": False, "state": "error", "error": "ledger_paths is empty"}
    man, sha = build_manifest(ledger_paths, out_dir)
    try:
        r = subprocess.run([OTS, "stamp", man], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return {"ok": False, "state": "error",
                "error": f"`{OTS}` not found — pip install opentimestamps-client"}
    ots_path = man + ".ots"
    ok = os.path.exists(ots_path)
    return {"ok": ok, "manifest": man, "manifest_sha256": sha,
            "ots_proof": ots_path if ok else None,
            "ledger_count": len(ledger_paths),
            "state": "pending_bitcoin_confirmation" if ok else "stamp_failed",
            "stdout": r.stdout.strip(), "stderr": r.stderr.strip()[:400],
            "next": f"in ~1-3h call mm_anchor_upgrade('{ots_path}'), then mm_anchor_verify",
            "honest_scope": "proves no-backdating of the heads; NOT content truth (GIGO)"}


def upgrade(ots_path: str) -> dict:
    """Try to retrieve the Bitcoin block attestation for a pending proof."""
    try:
        subprocess.run([OTS, "upgrade", ots_path], capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        return {"state": "error", "error": f"`{OTS}` not found — pip install opentimestamps-client"}
    m = _BLOCK_RE.search(_info(ots_path))
    if m:
        return {"state": "bitcoin_confirmed", "block_height": int(m.group(1)),
                "next": f"mm_anchor_verify('{ots_path}')"}
    return {"state": "pending", "block_height": None,
            "next": "retry later — the calendar has not committed to a Bitcoin block yet "
                    "(typically 1-3h after stamping)"}


def _explorer_block(height: int, explorer: str):
    bh = urllib.request.urlopen(f"{explorer}/block-height/{height}", timeout=20).read().decode().strip()
    blk = json.loads(urllib.request.urlopen(f"{explorer}/block/{bh}", timeout=20).read().decode())
    return bh, blk.get("merkle_root"), blk.get("timestamp")


def verify(ots_path: str, explorer: str = DEFAULT_EXPLORER) -> dict:
    """Verify a Bitcoin-anchored proof WITHOUT a local node, by cross-checking the block
    merkle root on a public explorer. Returns block height + independent-match."""
    info = _info(ots_path)
    m = _BLOCK_RE.search(info)
    if not m:
        return {"verified": False, "state": "pending",
                "note": "no Bitcoin attestation yet — run mm_anchor_upgrade first"}
    height = int(m.group(1))
    rm = _ROOT_RE.search(info)
    expected = rm.group(1).lower() if rm else None
    try:
        bhash, actual, ts = _explorer_block(height, explorer)
    except Exception as e:  # network / explorer issue — attestation still embedded
        return {"verified": False, "block_height": height, "expected_merkle_root": expected,
                "note": f"explorer fetch failed ({e}); embedded Bitcoin attestation is present"}
    match = expected is not None and actual is not None and actual.lower() == expected
    return {"verified": match, "block_height": height,
            "expected_merkle_root": expected, "explorer_merkle_root": actual,
            "block_hash": bhash,
            "block_time_utc": (datetime.datetime.utcfromtimestamp(ts).isoformat() + "Z") if ts else None,
            "explorer": explorer,
            "proves": "ledger heads existed before this Bitcoin block (no backdating)",
            "does_not_prove": ["content truth (GIGO)", "an external judging witness exists"]}
