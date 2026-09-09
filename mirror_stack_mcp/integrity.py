"""Read and verify one immutable-in-memory MIRROR-SPEC ledger snapshot.

Hash integrity is not signature identity, external timing, or content truth.
Both the gate and outsider CLI use this path; neither certifies pointer linkage alone.
"""
import hashlib
import json
from pathlib import Path


def _object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate JSON key: {key}")
        out[key] = value
    return out


def read_verified(path):
    """Return (entries, error). Fail closed on missing, empty or corrupt input.

    Reads once so decisions inspect exactly the snapshot whose hashes were checked.
    Accepts legacy 16-hex seals at their original, weaker assurance level.
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
        entries = [json.loads(line, object_pairs_hook=_object)
                   for line in raw.splitlines() if line.strip()]
        if not entries:
            return [], "ledger is empty; nothing verified"
        previous = "genesis"
        for i, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                return [], f"entry {i}: JSON object required"
            link, seal = entry.get("prev_seal"), entry.get("seal")
            if not isinstance(link, str) or (link.lower() != "genesis" if i == 1 else link != previous):
                return [], f"entry {i}: chain linkage broken"
            if not isinstance(seal, str) or len(seal) not in (16, 64):
                return [], f"entry {i}: missing or invalid seal"
            body = {k: v for k, v in entry.items() if k not in ("seal", "sig")}
            digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
                                               allow_nan=False).encode("utf-8")).hexdigest()
            if seal != digest[:len(seal)]:
                return [], f"entry {i}: seal mismatch; content modified"
            previous = seal
        return entries, None
    except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
        return [], f"ledger cannot be verified: {exc}"
