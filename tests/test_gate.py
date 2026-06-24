"""Tests for the enforceable gate (decide() + the `mirror-stack-gate` CLI).

The CLI is the part that actually exits non-zero — that exit code is the
enforcement the MCP can't provide. Also pins that server.mm_preflight delegates to
the same decide(), so the agent tool and the shell enforcer can't drift.
"""
import json

from mirror_stack_mcp import gate

PRE_KILL = {"claim_id": "c1", "metric": "acc", "kill_threshold": {"below": 0.5}}


def _w(p, entries):
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


# ── decide(): compute gate ────────────────────────────────────────────────────
def test_compute_blocks_without_prereg(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [])
    assert gate.decide(str(led), "c1", "compute")["decision"] == "BLOCK"


def test_compute_go_with_kill(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [PRE_KILL])
    assert gate.decide(str(led), "c1", "compute")["decision"] == "GO"


def test_compute_blocks_prereg_without_kill(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [{"claim_id": "c1", "metric": "acc", "kill_threshold": None}])
    assert gate.decide(str(led), "c1", "compute")["decision"] == "BLOCK"


# ── decide(): publish gate ────────────────────────────────────────────────────
def test_publish_blocks_unresolved(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [PRE_KILL])
    assert gate.decide(str(led), "c1", "publish")["decision"] == "BLOCK"


def test_publish_go_with_retraction(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [PRE_KILL, {"_type": "retraction", "claim_id": "c1"}])
    assert gate.decide(str(led), "c1", "publish")["decision"] == "GO"


def test_publish_go_with_am_record(tmp_path):
    led, am = tmp_path / "l.jsonl", tmp_path / "a.jsonl"
    _w(led, [PRE_KILL])
    _w(am, [{"_type": "action", "target": "c1"}])
    assert gate.decide(str(led), "c1", "publish", am_ledger=str(am))["decision"] == "GO"


# ── the CLI actually exits non-zero on BLOCK (this is the enforcement) ─────────
def test_cli_exits_zero_on_go(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [PRE_KILL])
    assert gate.main(["compute", "--ledger", str(led), "--claim", "c1"]) == 0


def test_cli_exits_nonzero_on_block(tmp_path):
    led = tmp_path / "l.jsonl"
    _w(led, [])
    assert gate.main(["compute", "--ledger", str(led), "--claim", "c1"]) == 1


# ── the MCP tool and the shell enforcer share one decision (no drift) ─────────
def test_server_mm_preflight_delegates_to_gate(tmp_path):
    import mirror_stack_mcp.server as s
    led = tmp_path / "l.jsonl"
    _w(led, [PRE_KILL])
    assert s.mm_preflight(str(led), "c1", gate="compute")["decision"] == "GO"
