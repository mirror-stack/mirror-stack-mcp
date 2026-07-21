"""The MCP wrappers must forward metric_range/chance to measure-mirror's audit so a
percentage / delta claim doesn't false-FAIL through the server (P0). Thin pass-through;
the probe logic itself is covered in measure-mirror's own suite."""
import pytest

pytest.importorskip("mcp", reason="mcp package not installed — server tests need it; core gate/verify tests run without it")
from mirror_stack_mcp import server


def _fails(findings):
    return [f for f in findings if "level='FAIL'" in str(f) or 'level="FAIL"' in str(f)]


def test_mm_audit_percentage_no_false_range_fail(tmp_path):
    led = str(tmp_path / "l.jsonl")
    out = server.mm_audit(led, "c", reported_metric="eng_improve_pct", reported_acc=54.1, n=3000)
    assert not any("metric-range" in str(f) for f in _fails(out))   # 54.1 ∈ [0,100], not "out of [0,1]"


def test_mm_audit_explicit_metric_range_forwarded(tmp_path):
    led = str(tmp_path / "l.jsonl")
    out = server.mm_audit(led, "c", reported_metric="mystery", reported_acc=6.4, n=800,
                          metric_range="unbounded")
    assert not _fails(out)                                          # unbounded → no range/grim FAIL


def test_mm_preregister_seals_metric_kind(tmp_path):
    led = str(tmp_path / "l.jsonl")
    entry = server.mm_preregister(led, "p", metric="eng_improve_pct", min_n=100,
                                  baseline=50.0, pass_threshold=50.0,
                                  metric_range=[0, 100], chance=50.0)
    assert entry["metric_range"] == [0, 100] and entry["chance"] == 50.0
    # audit with no explicit kind args reads them back from the sealed prereg
    out = server.mm_audit(led, "p", reported_metric="eng_improve_pct", reported_acc=54.1, n=3000)
    assert not any("metric-range" in str(f) for f in _fails(out))
