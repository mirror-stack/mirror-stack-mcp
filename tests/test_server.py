"""Unit + smoke tests for the unified Mirror Stack MCP server.

Covers what a fresh install / reconnect must get right:
  • all 19 tools register (drift detector — adding/removing a tool fails this);
  • the loop-safe defaults (compact output, once-per-session reminders);
  • signal-preserving compaction — OK/INFO collapse, but a WARN/FAIL is NEVER dropped
    (a hidden negative is the cardinal sin this server exists to prevent);
  • discipline-reminder modes (off / all / once);
  • the mm_preflight GO/BLOCK gate logic (seal-before-compute, resolution-before-publish);
  • one cross-package path: mm seal -> stack_verify_all (catches a stale/broken mirror dep).
"""
import json

import mirror_stack_mcp.server as s

EXPECTED_TOOLS = {
    # 🪞 measure-mirror (claims)
    "mm_preregister", "mm_verify", "mm_audit", "mm_power_check",
    "mm_falsifiability_check", "mm_prereg_lint", "mm_leakage_check",
    "mm_multiseed_check",
    "mm_retract", "mm_anchor", "mm_anchor_bitcoin", "mm_anchor_upgrade",
    "mm_anchor_verify", "mm_preflight",
    # 🪪 action-mirror
    "am_record", "am_witness", "am_verify",
    # 🔎 provenance-mirror
    "pm_verify",
    # 🪞🔎🪪 stack-level
    "stack_verify_all",
}


def _registered():
    return {t.name for t in s.mcp._tool_manager.list_tools()}


def _write(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


# ── registration / defaults ───────────────────────────────────────────────────
def test_all_19_tools_registered():
    names = _registered()
    assert names == EXPECTED_TOOLS, f"tool drift: {names ^ EXPECTED_TOOLS}"
    assert len(names) == 19


def test_defaults_are_loop_safe():
    # The dogfooding defaults a long-running loop agent depends on.
    assert s._VERBOSITY == "compact"
    assert s._MODE == "once"


# ── signal-preserving compaction ──────────────────────────────────────────────
def test_compact_summarises_ok_keeps_fail(monkeypatch):
    monkeypatch.setattr(s, "_VERBOSITY", "compact")
    findings = [
        "Finding(probe='grim', level='OK', msg='consistent')",
        "Finding(probe='power', level='INFO', msg='n ok')",
        "Finding(probe='leakage', level='FAIL', msg='train n test contamination')",
    ]
    out = s._compact(findings)
    assert len(out) == 2                                   # 2 OK/INFO -> 1 line, + the FAIL
    assert out[0].startswith("✓ 2 check(s) OK:")
    assert "grim" in out[0] and "power" in out[0]
    assert any("FAIL" in line and "leakage" in line for line in out)


def test_compact_never_drops_a_lone_fail(monkeypatch):
    monkeypatch.setattr(s, "_VERBOSITY", "compact")
    findings = ["Finding(probe='x', level='FAIL', msg='bad')"]
    assert s._compact(findings) == findings               # cardinal-sin guard


def test_full_mode_passes_through_verbatim(monkeypatch):
    monkeypatch.setattr(s, "_VERBOSITY", "full")
    findings = ["Finding(probe='a', level='OK', msg='m')"]
    assert s._compact(findings) == findings


# ── discipline reminders ──────────────────────────────────────────────────────
def test_remind_off(monkeypatch):
    monkeypatch.setattr(s, "_MODE", "off")
    monkeypatch.setattr(s, "_shown", set())
    assert "_reminder" not in s._remind("mm_verify", {"k": 1})


def test_remind_all_fires_every_call(monkeypatch):
    monkeypatch.setattr(s, "_MODE", "all")
    monkeypatch.setattr(s, "_shown", set())
    assert "_reminder" in s._remind("mm_verify", {"k": 1})
    assert "_reminder" in s._remind("mm_verify", {"k": 2})


def test_remind_once_then_silent(monkeypatch):
    monkeypatch.setattr(s, "_MODE", "once")
    monkeypatch.setattr(s, "_shown", set())
    assert "_reminder" in s._remind("mm_verify", {"k": 1})
    assert "_reminder" not in s._remind("mm_verify", {"k": 2})


def test_remind_shapes_and_unknown_tool(monkeypatch):
    monkeypatch.setattr(s, "_MODE", "all")
    monkeypatch.setattr(s, "_shown", set())
    assert s._remind("mm_verify", ["a"])[-1].startswith("\U0001fa9e")   # list -> appended
    assert "\U0001fa9e" in s._remind("mm_verify", "txt")                # str  -> joined
    assert s._remind("not_a_tool", {"k": 1}) == {"k": 1}               # no reminder defined


# ── mm_preflight GO/BLOCK gate ────────────────────────────────────────────────
def test_preflight_compute_blocks_without_prereg(tmp_path):
    led = tmp_path / "mm.jsonl"
    _write(led, [])
    assert s.mm_preflight(str(led), "c1", gate="compute")["decision"] == "BLOCK"


def test_preflight_compute_go_with_kill(tmp_path):
    led = tmp_path / "mm.jsonl"
    _write(led, [{"claim_id": "c1", "metric": "acc", "kill_threshold": {"below": 0.5}}])
    assert s.mm_preflight(str(led), "c1", gate="compute")["decision"] == "GO"


def test_preflight_compute_blocks_prereg_without_killcondition(tmp_path):
    # key present but falsy -> recognised as prereg, but unfalsifiable -> BLOCK
    led = tmp_path / "mm.jsonl"
    _write(led, [{"claim_id": "c1", "metric": "acc", "kill_threshold": None}])
    r = s.mm_preflight(str(led), "c1", gate="compute")
    assert r["decision"] == "BLOCK"
    assert "kill-condition" in " ".join(r["reasons"])


def test_preflight_publish_blocks_without_resolution(tmp_path):
    led = tmp_path / "mm.jsonl"
    _write(led, [{"claim_id": "c1", "metric": "acc", "kill_threshold": {"below": 0.5}}])
    assert s.mm_preflight(str(led), "c1", gate="publish")["decision"] == "BLOCK"


def test_preflight_publish_go_with_retraction(tmp_path):
    led = tmp_path / "mm.jsonl"
    _write(led, [
        {"claim_id": "c1", "metric": "acc", "kill_threshold": {"below": 0.5}},
        {"_type": "retraction", "claim_id": "c1"},
    ])
    assert s.mm_preflight(str(led), "c1", gate="publish")["decision"] == "GO"


def test_preflight_publish_go_with_am_record(tmp_path):
    led, am = tmp_path / "mm.jsonl", tmp_path / "am.jsonl"
    _write(led, [{"claim_id": "c1", "metric": "acc", "kill_threshold": {"below": 0.5}}])
    _write(am, [{"_type": "action", "target": "c1"}])
    r = s.mm_preflight(str(led), "c1", gate="publish", am_ledger=str(am))
    assert r["decision"] == "GO"


def test_preflight_unknown_gate(tmp_path):
    led = tmp_path / "mm.jsonl"
    _write(led, [{"claim_id": "c1", "metric": "acc", "kill_threshold": {"below": 0.5}}])
    assert s.mm_preflight(str(led), "c1", gate="bogus")["decision"] == "BLOCK"


# ── mm_prereg_lint (seal-quality) + leaked-kill gate ──────────────────────────
def test_prereg_lint_flags_leaked_kill_condition(tmp_path):
    led = tmp_path / "mm.jsonl"
    # criterion sealed into `metric`, no kill fields — the self-catch #2 shape
    _write(led, [{"claim_id": "gate0",
                  "metric": "gene1 eq; KILL if delta < 0.03 across arms",
                  "min_n": 200, "baseline": 0.5, "pass_threshold": 0.6}])
    out = s.mm_prereg_lint(str(led), "gate0")
    assert any("FAIL" in line and "leaked into" in line for line in out)


def test_prereg_lint_clean_seal_has_no_warn_or_fail(tmp_path):
    led = tmp_path / "mm.jsonl"
    s.mm_preregister(str(led), "good", metric="separation_d", min_n=240,
                     kill_threshold={"metric": "d", "threshold": 0.1, "direction": "below"},
                     pre_seal_checks=["reachability-smoke", "neutral-control"])
    out = s.mm_prereg_lint(str(led), "good")
    assert not [line for line in out if "WARN" in line or "FAIL" in line]


def test_preregister_response_carries_auto_lint(tmp_path):
    led = tmp_path / "mm.jsonl"
    r = s.mm_preregister(str(led), "c1", metric="acc", min_n=10,
                         kill_threshold={"metric": "acc", "threshold": 0.55,
                                         "direction": "below"})
    assert "lint" in r
    joined = " ".join(r["lint"])
    assert "small-sample floor" in joined          # min_n=10 surfaces immediately


def test_compute_gate_blocks_on_lint_fail_below_chance_bar(tmp_path):
    led = tmp_path / "mm.jsonl"
    # well-formed kill fields, but the pass bar sits below chance → lint FAIL
    s.mm_preregister(str(led), "c1", metric="acc", baseline=0.5, pass_threshold=0.45,
                     kill_threshold={"metric": "acc", "threshold": 0.4,
                                     "direction": "below"})
    r = s.mm_preflight(str(led), "c1", gate="compute")
    assert r["decision"] == "BLOCK"
    assert "prereg-lint FAIL" in " ".join(r["reasons"])


def test_compute_gate_go_passes_lint_check(tmp_path):
    led = tmp_path / "mm.jsonl"
    s.mm_preregister(str(led), "c1", metric="acc", min_n=240,
                     kill_threshold={"metric": "acc", "threshold": 0.55,
                                     "direction": "below"},
                     pre_seal_checks=["reachability-smoke"])
    r = s.mm_preflight(str(led), "c1", gate="compute")
    assert r["decision"] == "GO"
    assert any("prereg-lint: no FAIL" in c for c in r["checks"])


def test_compute_gate_reports_leaked_kill_condition(tmp_path):
    led = tmp_path / "mm.jsonl"
    _write(led, [{"claim_id": "gate0",
                  "metric": "gene1 eq; KILL if delta < 0.03 across arms",
                  "min_n": 200, "baseline": 0.5, "pass_threshold": 0.6}])
    r = s.mm_preflight(str(led), "gate0", gate="compute")
    assert r["decision"] == "BLOCK"
    assert "leaked into" in " ".join(r["reasons"])


# ── cross-package integration: a real mirror dep must work end-to-end ──────────
def test_stack_verify_all_on_a_freshly_sealed_ledger(tmp_path):
    led = tmp_path / "mm.jsonl"
    s.mm_preregister(str(led), "c1", metric="acc",
                     kill_threshold={"metric": "acc", "threshold": 0.5, "direction": "below"})
    r = s.stack_verify_all(mm_ledger=str(led))
    assert r["ok"] is True and r["verdict"] == "ALL OK"
    assert r["passed"] >= 1
