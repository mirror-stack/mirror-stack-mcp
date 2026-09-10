"""Managed stdio boundary: actual writers, multi-process retries and negative controls."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mirror_stack_mcp import server as s
from mirror_stack_mcp.integrity import read_verified
from mirror_stack_mcp.runtime import (RuntimeRefusal, guarded, managed_root,
                                      operation_status, receipt_path, workspace_lock)


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setenv("MIRROR_MCP_ROOT", str(tmp_path.resolve()))
    monkeypatch.setenv("MIRROR_MCP_ALLOW_WRITE", "1")
    for key in ("MIRROR_MCP_WRITE_TOOLS", "MIRROR_MCP_ALLOW_NETWORK", "MIRROR_MCP_ALLOW_EXEC"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path.resolve()


def record(operation_id="op-1", **kw):
    return s.am_record("actions.jsonl", "worker", "test", operation_id=operation_id, **kw)


def test_restart_replay_and_changed_arguments_conflict(managed):
    first = record(payload={"n": 1})
    original = (managed / "actions.jsonl").read_bytes()
    code = "from mirror_stack_mcp.server import am_record; import json; print(json.dumps(am_record('actions.jsonl','worker','test',payload={'n':1},operation_id='op-1')))"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == first
    assert (managed / "actions.jsonl").read_bytes() == original
    with pytest.raises(RuntimeRefusal, match="CONFLICT"):
        record(payload={"n": 2})
    assert (managed / "actions.jsonl").read_bytes() == original


def test_managed_requires_id_and_write_permission(managed, monkeypatch):
    with pytest.raises(RuntimeRefusal, match="operation_id"):
        record(None)
    monkeypatch.setenv("MIRROR_MCP_ALLOW_WRITE", "0")
    with pytest.raises(RuntimeRefusal, match="read-only"):
        record()
    assert not (managed / "actions.jsonl").exists()


def test_policy_rechecked_before_replay(managed, monkeypatch):
    record()
    monkeypatch.setenv("MIRROR_MCP_WRITE_TOOLS", "mm_preregister")
    with pytest.raises(RuntimeRefusal, match="not in"):
        record()


@pytest.mark.parametrize("path", ["../escape.jsonl", ".mirror-mcp-runtime/workspace.lock"])
def test_scope_escape_and_control_targets_refused(managed, path):
    with pytest.raises(RuntimeRefusal):
        s.am_record(path, "a", "x", operation_id="escape")


def test_absolute_outside_and_read_escape_refused(managed):
    with pytest.raises(RuntimeRefusal, match="outside"):
        s.mm_anchor(str(managed.parent / "outside.jsonl"))


def test_symlink_and_hardlink_refused(managed, tmp_path):
    target = managed / "real"
    target.write_text("original")
    link = managed / "link"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(RuntimeRefusal, match="symlink"):
        s.pm_verify("link", "pm.jsonl", operation_id="link")
    hard = managed / "hard"
    os.link(target, hard)
    with pytest.raises(RuntimeRefusal, match="hard-linked"):
        s.pm_verify("hard", "pm.jsonl", operation_id="hard")


@pytest.mark.parametrize("contents", ["", "broken\n", '{"seal":"a","seal":"b"}\n'])
def test_invalid_existing_ledger_not_extended(managed, contents):
    path = managed / "actions.jsonl"
    path.write_text(contents)
    with pytest.raises(RuntimeRefusal, match="INVALID_LEDGER"):
        record()
    assert path.read_text() == contents
    assert not receipt_path(managed, "op-1").exists()


def test_valid_unterminated_tail_refused(managed):
    record()
    path = managed / "actions.jsonl"
    raw = path.read_bytes().rstrip(b"\n")
    path.write_bytes(raw)
    with pytest.raises(RuntimeRefusal, match="unterminated"):
        record("op-2")
    assert path.read_bytes() == raw


def test_nonfinite_input_refused_before_write(managed):
    with pytest.raises(ValueError):
        record(payload={"n": float("nan")})
    assert not (managed / "actions.jsonl").exists()


def test_interrupted_request_never_reexecutes(managed):
    code = '''
import os
from pathlib import Path
from mirror_stack_mcp.runtime import guarded
@guarded(write=True)
def crash(operation_id=None):
    (Path(os.environ['MIRROR_MCP_ROOT']) / 'effect').write_text('once')
    os._exit(17)
crash(operation_id='crash-1')
'''
    result = subprocess.run([sys.executable, "-c", code], timeout=20)
    assert result.returncode == 17
    assert (managed / "effect").read_text() == "once"

    @guarded(write=True)
    def crash(operation_id=None):
        pytest.fail("interrupted operation was re-executed")

    with pytest.raises(RuntimeRefusal, match="RECONCILE_REQUIRED"):
        crash(operation_id="crash-1")
    with pytest.raises(RuntimeRefusal, match="RECONCILE_REQUIRED"):
        record("different-id")
    assert not (managed / "actions.jsonl").exists()
    # Kernel lock released on process death, receipt retained.
    with workspace_lock(managed, timeout=0.1):
        assert json.loads(receipt_path(managed, "crash-1").read_text())["status"] == "prepared"


def test_parallel_processes_same_and_distinct_ids(managed):
    code = "from mirror_stack_mcp.server import am_record; import sys; am_record('actions.jsonl','a','x',operation_id=sys.argv[1])"
    processes = [subprocess.Popen([sys.executable, "-c", code, op], stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True)
                 for op in ("same", "same", "one", "two")]
    try:
        for process in processes:
            _, stderr = process.communicate(timeout=30)
            assert process.returncode == 0, stderr
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()
    entries, error = read_verified(managed / "actions.jsonl")
    assert error is None
    assert len(entries) == 3


def test_lock_wait_is_bounded(managed):
    with workspace_lock(managed):
        with pytest.raises(RuntimeRefusal, match="BUSY"):
            with workspace_lock(managed, timeout=0.05):
                pytest.fail("second lock acquired")


def test_receipt_corruption_refuses_replay(managed):
    record()
    receipt_path(managed, "op-1").write_text('{"schema":1,"schema":1}')
    with pytest.raises(RuntimeRefusal, match="RECONCILE_REQUIRED"):
        record()


def test_network_tools_require_separate_capabilities(managed):
    with pytest.raises(RuntimeRefusal, match="network"):
        s.mm_anchor_verify("proof.ots")
    with pytest.raises(RuntimeRefusal, match="network"):
        s.mm_anchor_bitcoin(["actions.jsonl"], "anchors", operation_id="net")


def test_all_tool_schemas_preserved_and_writers_expose_id(managed):
    tools = {tool.name: tool for tool in s.mcp._tool_manager.list_tools()}
    assert len(tools) == 22
    for name in ("am_record", "am_witness", "pm_verify", "mm_preregister",
                 "mm_retract", "mm_anchor_bitcoin", "mm_anchor_upgrade"):
        assert "operation_id" in tools[name].parameters["properties"]
        assert "Managed mode requires operation_id" in tools[name].description


def test_provenance_and_prereg_writes_remain_verified(managed):
    (managed / "artifact").write_text("ordinary c2pa marker")
    got = s.pm_verify("artifact", operation_id="pm")
    assert got["verdict"] == "PROVENANCE-UNVERIFIED"
    assert read_verified(managed / "pm_ledger.jsonl")[1] is None
    s.mm_preregister("claims.jsonl", "c", "acc", kill_condition="below chance", operation_id="pre")
    assert read_verified(managed / "claims.jsonl")[1] is None


def test_embedded_anchor_path_cannot_escape(managed):
    record()
    anchors = managed / "anchors"
    anchors.mkdir()
    (anchors / "anchor_bad.json").write_text(json.dumps({"ledger_path": str(managed.parent / "private")}))
    with pytest.raises(RuntimeRefusal, match="outside"):
        s.stack_verify_all("actions.jsonl", "anchors")


def test_bad_root_never_falls_back_to_trusted(monkeypatch):
    monkeypatch.setenv("MIRROR_MCP_ROOT", "")
    with pytest.raises(RuntimeRefusal):
        managed_root()


def test_id_without_managed_mode_is_not_silently_ignored(monkeypatch):
    monkeypatch.delenv("MIRROR_MCP_ROOT", raising=False)
    with pytest.raises(RuntimeRefusal, match="requires managed"):
        record()


def test_status_does_not_create_runtime_state_and_reports_done(managed):
    assert operation_status("missing") == {"operation_id": "missing", "status": "unknown"}
    assert not (managed / ".mirror-mcp-runtime").exists()
    record()
    before = receipt_path(managed, "op-1").read_bytes()
    assert operation_status("op-1")["status"] == "done"
    assert receipt_path(managed, "op-1").read_bytes() == before


def test_lock_control_symlink_refused(managed):
    control = managed / ".mirror-mcp-runtime"
    control.mkdir(mode=0o700)
    outside = managed / "untouched"
    outside.write_text("unchanged")
    try:
        (control / "workspace.lock").symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(RuntimeRefusal, match="symlink"):
        record()
    assert outside.read_text() == "unchanged"


def test_anchor_manifests_never_overwrite_on_timestamp_collision(managed):
    from mirror_stack_mcp.ots_anchor import build_manifest
    record()
    args = ([str(managed / "actions.jsonl")], str(managed / "anchors"))
    first, digest = build_manifest(*args)
    content = Path(first).read_bytes()
    second, _ = build_manifest(*args)
    assert first != second
    assert Path(first).read_bytes() == content
    assert Path(second).exists()


def test_crash_between_marker_and_receipt_fails_closed(managed, monkeypatch):
    from mirror_stack_mcp import runtime
    original = runtime._store

    def fault(path, row):
        if row.get("status") == "prepared":
            raise OSError("injected persistence failure")
        return original(path, row)

    with monkeypatch.context() as scoped:
        scoped.setattr(runtime, "_store", fault)
        with pytest.raises(OSError, match="injected"):
            record("interrupted")
    assert not (managed / "actions.jsonl").exists()
    with pytest.raises(RuntimeRefusal, match="RECONCILE_REQUIRED"):
        record("new-id")
    with pytest.raises(RuntimeRefusal, match="RECONCILE_REQUIRED"):
        record("interrupted")
