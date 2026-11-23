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
import uuid
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


REDACTED_SCHEME = "sha256(salt || utf8(ledger basename))"


def ledger_id(name: str, salt_hex: str) -> str:
    """Salted commitment to a ledger's file name, as written in a redacted manifest.

    Disclosing (name, salt) for ONE ledger lets anyone recompute its id; the other
    ledgers' names stay hidden because each ledger has its own random salt."""
    return hashlib.sha256(bytes.fromhex(salt_hex) + name.encode("utf-8")).hexdigest()


def _load_salts(id_map_path: str, names: list[str]) -> dict:
    """Load the private name -> salt map, adding a fresh random salt for new ledgers.

    Salts are stable across runs so the same ledger keeps the same id every day. The
    map is the only link between ids and names: keep it private, never next to the
    published manifests."""
    p = Path(id_map_path)
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    salts = dict(data.get("salts", {}))
    added = [n for n in names if n not in salts]
    for n in added:
        salts[n] = os.urandom(16).hex()
    if added or not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + f".tmp.{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(json.dumps({"_type": "ots_ledger_id_map", "scheme": REDACTED_SCHEME,
                                     "salts": salts}, ensure_ascii=False, indent=2))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, p)
    return salts


def build_manifest(ledger_paths: list[str], out_dir: str, *,
                   id_map_path: str | None = None) -> tuple[str, str]:
    """Write a manifest pinning each ledger's sha256 + head seal. Returns (path, sha256).

    Default (format 1) records each ledger's basename and absolute path. With
    ``id_map_path`` the manifest is publishable as-is (format 2): no paths, and each
    ledger is named only by a salted id (see ``ledger_id``); the private name -> salt
    map is kept at ``id_map_path``, which must lie outside ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)
    rows = []
    if id_map_path is not None:
        out_real = os.path.realpath(out_dir)
        if os.path.commonpath([out_real, os.path.realpath(id_map_path)]) == out_real:
            raise ValueError("id_map_path must not be inside out_dir (it would be published)")
        names = [os.path.basename(f) for f in ledger_paths]
        if len(set(names)) != len(names):
            raise ValueError("duplicate ledger basenames cannot be redacted unambiguously")
        salts = _load_salts(id_map_path, names)
    for f in ledger_paths:
        common = {"bytes": Path(f).stat().st_size, "sha256": _sha256(f),
                  "head_seal": _head_seal(f)}
        if id_map_path is None:
            rows.append({"ledger": os.path.basename(f), "path": str(f), **common})
        else:
            name = os.path.basename(f)
            rows.append({"ledger_id": ledger_id(name, salts[name]), **common})
    stamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    # Different legitimate operations in the same second must not replace evidence.
    man = os.path.join(out_dir, f"manifest_{stamp}_{uuid.uuid4().hex}.json")
    manifest = {"_type": "ots_anchor_manifest",
                "ts": datetime.datetime.utcnow().isoformat() + "Z",
                "purpose": "Bitcoin timestamp of mirror-stack ledger heads — "
                           "proves no-backdating, NOT content truth.",
                "ledger_count": len(rows), "ledgers": rows}
    if id_map_path is not None:
        manifest["format"] = 2
        manifest["ledger_naming"] = {
            "scheme": REDACTED_SCHEME,
            "salts": "private; disclosed per ledger by the operator on request"}
    with open(man, "x", encoding="utf-8") as stream:
        stream.write(json.dumps(manifest, ensure_ascii=False, indent=2))
        stream.flush()
        os.fsync(stream.fileno())
    return man, _sha256(man)


def _info(ots_path: str) -> str:
    return subprocess.run([OTS, "info", ots_path], capture_output=True,
                          text=True, timeout=60).stdout


def stamp(ledger_paths: list[str], out_dir: str, *, id_map_path: str | None = None) -> dict:
    """Build a manifest of the ledger heads and submit it to the OTS Bitcoin calendars.

    Pass ``id_map_path`` to write a publishable (format 2, redacted-name) manifest."""
    if not ledger_paths:
        return {"ok": False, "state": "error", "error": "ledger_paths is empty"}
    man, sha = build_manifest(ledger_paths, out_dir, id_map_path=id_map_path)
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


def locate_ledger(manifest_path: str, ledger_path: str, *, name: str | None = None,
                  salt_hex: str | None = None) -> dict:
    """Find which manifest row pins this ledger (format 1 or 2).

    Ledgers are append-only, so a later copy still matches if its first ``bytes``
    bytes hash to the pinned sha256. With ``name`` + ``salt_hex`` (disclosed by the
    operator) a format-2 row's ``ledger_id`` is also checked against that name."""
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    data = Path(ledger_path).read_bytes()
    want_id = ledger_id(name, salt_hex) if (name and salt_hex) else None
    for row in manifest.get("ledgers", []):
        n = row.get("bytes")
        if not isinstance(n, int) or n > len(data):
            continue
        if hashlib.sha256(data[:n]).hexdigest() != row.get("sha256"):
            continue
        result = {"found": True, "format": manifest.get("format", 1),
                  "pinned_bytes": n, "exact": n == len(data),
                  "pinned_lines": data[:n].count(b"\n"),
                  "head_seal": row.get("head_seal"),
                  "ledger_id": row.get("ledger_id"), "ledger": row.get("ledger")}
        if want_id is not None:
            result["name_matches"] = row.get("ledger_id") == want_id or row.get("ledger") == name
        return result
    return {"found": False, "format": manifest.get("format", 1)}
