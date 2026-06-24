"""Tests for the zero-config outsider verifier (mirror-stack-verify).

Covers the no-network chain check (the universal part); the Bitcoin cross-check is
network + `ots` CLI and is exercised manually, not in CI.
"""
import json

from mirror_stack_mcp import verify

CHAIN = [
    {"action": "a", "seal": "s1", "prev_seal": "genesis"},
    {"action": "b", "seal": "s2", "prev_seal": "s1"},
    {"action": "c", "seal": "s3", "prev_seal": "s2"},
]


def _w(p, entries):
    p.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def test_chain_intact(tmp_path):
    p = tmp_path / "l.jsonl"
    _w(p, CHAIN)
    ok, msg = verify.check_chain(str(p))
    assert ok and "intact" in msg and "head=s3" in msg


def test_chain_deleted_entry_is_caught(tmp_path):
    p = tmp_path / "l.jsonl"
    _w(p, [CHAIN[0], CHAIN[2]])           # drop s2 → s3.prev_seal(s2) != s1
    ok, msg = verify.check_chain(str(p))
    assert not ok and "broken" in msg


def test_chain_first_must_be_genesis(tmp_path):
    p = tmp_path / "l.jsonl"
    _w(p, [{"seal": "s1", "prev_seal": "s0"}])
    ok, _ = verify.check_chain(str(p))
    assert not ok


def test_chain_empty(tmp_path):
    p = tmp_path / "l.jsonl"
    p.write_text("", encoding="utf-8")
    ok, _ = verify.check_chain(str(p))
    assert not ok


def test_main_intact_no_ots_confirms(tmp_path):
    p = tmp_path / "l.jsonl"
    _w(p, CHAIN)
    assert verify.main([str(p)]) == 0     # chain ok, bitcoin skipped → integrity confirmed


def test_main_broken_chain_fails(tmp_path):
    p = tmp_path / "l.jsonl"
    _w(p, [CHAIN[0], CHAIN[2]])
    assert verify.main([str(p)]) == 1
