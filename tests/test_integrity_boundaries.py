import hashlib
import json

import pytest

from mirror_stack_mcp import gate, verify
from mirror_stack_mcp.integrity import read_verified


def write_chain(path, entries, legacy=False):
    sealed, previous = [], "genesis"
    for entry in entries:
        row = {**entry, "prev_seal": previous}
        row["seal"] = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if legacy:
            row["seal"] = row["seal"][:16]
        previous = row["seal"]
        sealed.append(row)
    path.write_text("\n".join(json.dumps(e) for e in sealed) + "\n")
    return sealed


PRE = {"claim_id": "c", "metric": "acc", "kill_condition": "kill if below baseline"}


@pytest.mark.parametrize("text", ["", "not json", "[]", "null", "42",
                                    json.dumps(PRE), '{"seal":"a","seal":"b"}'])
def test_malformed_or_unsealed_ledger_blocks(tmp_path, text):
    path = tmp_path / "claims.jsonl"
    path.write_text(text)
    assert gate.decide(str(path), "c")["decision"] == "BLOCK"
    assert read_verified(path)[1]


def test_missing_ledger_blocks(tmp_path):
    assert gate.decide(str(tmp_path / "missing"), "c")["decision"] == "BLOCK"


@pytest.mark.parametrize("legacy", [False, True])
def test_real_seal_passes_but_content_edit_fails(tmp_path, legacy, capsys):
    path = tmp_path / "claims.jsonl"
    rows = write_chain(path, [PRE], legacy)
    assert verify.main([str(path)]) == 0
    assert "ledger precedence UNVERIFIED" in capsys.readouterr().out
    rows[0]["metric"] = "changed-without-resealing"
    path.write_text(json.dumps(rows[0]) + "\n")
    assert verify.check_chain(str(path))[0]  # linkage alone still passes
    assert verify.main([str(path)]) == 1
    assert gate.decide(str(path), "c")["decision"] == "BLOCK"


@pytest.mark.parametrize("status", ["pass", "fail", "inconclusive"])
def test_explicit_bound_results_can_publish(tmp_path, status):
    claims, actions = tmp_path / "claims", tmp_path / "actions"
    pre = write_chain(claims, [PRE])[0]
    write_chain(actions, [{"_type": "action", "action": "result", "target": "c",
                           "payload": {"status": status, "summary": "observed outcome",
                                       "prereg_seal": pre["seal"]}}])
    result = gate.decide(str(claims), "c", "publish", str(actions))
    assert result["decision"] == "GO"
    assert result["verification"]["content_truth"] == "unverified"


@pytest.mark.parametrize("change", ["started", "wrong-seal", "empty-summary", "unknown-status", "tampered"])
def test_invalid_resolution_blocks(tmp_path, change):
    claims, actions = tmp_path / "claims", tmp_path / "actions"
    pre = write_chain(claims, [PRE])[0]
    row = {"_type": "action", "action": "result", "target": "c",
           "payload": {"status": "pass", "summary": "observed outcome", "prereg_seal": pre["seal"]}}
    if change == "started":
        row["action"] = "started"
    elif change == "wrong-seal":
        row["payload"]["prereg_seal"] = "another registration"
    elif change == "empty-summary":
        row["payload"]["summary"] = " "
    elif change == "unknown-status":
        row["payload"]["status"] = "started"
    sealed = write_chain(actions, [row])
    if change == "tampered":
        sealed[0]["payload"]["summary"] = "changed"
        actions.write_text(json.dumps(sealed[0]) + "\n")
    assert gate.decide(str(claims), "c", "publish", str(actions))["decision"] == "BLOCK"


def test_retraction_requires_reason_and_blocks_compute(tmp_path):
    claims = tmp_path / "claims"
    write_chain(claims, [PRE, {"_type": "retraction", "claim_id": "c"}])
    assert gate.decide(str(claims), "c", "publish")["decision"] == "BLOCK"
    write_chain(claims, [PRE, {"_type": "retraction", "claim_id": "c", "reason": "negative result"}])
    assert gate.decide(str(claims), "c", "publish")["decision"] == "GO"
    assert gate.decide(str(claims), "c", "compute")["decision"] == "BLOCK"


def test_first_registration_wins(tmp_path):
    claims = tmp_path / "claims"
    write_chain(claims, [{**PRE, "kill_condition": ""}, PRE])
    assert gate.decide(str(claims), "c")["decision"] == "BLOCK"
    write_chain(claims, [{"claim_id": "c", "metric": "acc"}, PRE])
    assert gate.decide(str(claims), "c")["decision"] == "BLOCK"


def test_unsigned_action_cannot_resolve(tmp_path):
    claims, actions = tmp_path / "claims", tmp_path / "actions"
    pre = write_chain(claims, [PRE])[0]
    actions.write_text(json.dumps({"_type": "action", "action": "result", "target": "c",
                                  "payload": {"status": "pass", "summary": "done",
                                              "prereg_seal": pre["seal"]}}))
    assert gate.decide(str(claims), "c", "publish", str(actions))["decision"] == "BLOCK"


def test_decision_reads_claims_snapshot_only_once(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path / "claims"
    write_chain(path, [PRE])
    read_text = Path.read_text
    calls = []

    def counted(self, *args, **kwargs):
        if self == path:
            calls.append(self)
        return read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    assert gate.decide(str(path), "c")["decision"] == "GO"
    assert calls == [path]


def test_mcp_empty_ledger_is_not_success(tmp_path):
    from mirror_stack_mcp.server import stack_verify_all
    claims = tmp_path / "claims"
    claims.write_text("")
    result = stack_verify_all(str(claims))
    assert result["ok"] is False
    assert result["scope"]["independent_reproduction"] == "unverified"
