"""The installed MCP dependency must emit the corrected provenance contract."""
from mirror_stack_mcp import server


def test_mcp_uses_unverified_provenance_dependency(tmp_path):
    path = tmp_path / "marker.txt"
    path.write_bytes(b"ordinary text c2pa, no manifest or signature")
    result = server.pm_verify(str(path), str(tmp_path / "pm.jsonl"))
    assert result["verdict"] == "PROVENANCE-UNVERIFIED"
    assert result["verification"]["signature_verified"] is False
    assert result["ledger_entry"]["verdict"] == result["verdict"]
