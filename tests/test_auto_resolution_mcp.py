"""The mm_falsifiability_check wrapper must forward am_ledger so the server can
self-evaluate a kill-condition from a sealed resolution (P1). Thin pass-through;
the recovery logic itself is covered in measure-mirror's own suite."""
import json

import pytest

pytest.importorskip("mcp", reason="mcp package not installed — server tests need it; core gate/verify tests run without it")
from mirror_stack_mcp import server


def test_falsifiability_recovers_from_am_ledger(tmp_path):
    led, am = tmp_path / "l.jsonl", tmp_path / "am.jsonl"
    server.mm_preregister(str(led), "c1", metric="acc", min_n=10, baseline=0.5,
                          pass_threshold=0.6,
                          kill_threshold={"metric": "acc", "threshold": 0.55, "direction": "below"})
    am.write_text(json.dumps({"_type": "action", "target": "c1",
                              "payload": {"reported_acc": 0.40}}) + "\n", encoding="utf-8")
    out = server.mm_falsifiability_check(str(led), "c1", am_ledger=str(am))
    assert "FAIL" in out and "auto-recovered" in out          # 0.40 < 0.55, recovered, no manual acc


def test_falsifiability_unresolved_still_warns(tmp_path):
    led = tmp_path / "l.jsonl"
    server.mm_preregister(str(led), "c1", metric="acc", min_n=10, baseline=0.5,
                          pass_threshold=0.6,
                          kill_threshold={"metric": "acc", "threshold": 0.55, "direction": "below"})
    assert "WARN" in server.mm_falsifiability_check(str(led), "c1")
