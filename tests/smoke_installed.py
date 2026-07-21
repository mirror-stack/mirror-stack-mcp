"""Run from OUTSIDE the source tree, against the INSTALLED wheel (see CI `package` job).

This is the exact check that would have caught our local install going silently stale:
'works in the repo, broken/old once installed'. It asserts the unified server imports
in a clean environment, exposes all 19 tools, and that the three re-exposed mirror
packages are importable (a missing/renamed mirror dep fails here, loudly).
"""
import mirror_stack_mcp.server as s

tools = {t.name for t in s.mcp._tool_manager.list_tools()}
assert len(tools) == 19, f"expected 19 tools, got {len(tools)}: {sorted(tools)}"
assert callable(s.main), "entry point mirror_stack_mcp.server:main missing"

import measure_mirror  # noqa: F401  re-exposed claim probes
import actmirror       # noqa: F401  action ledger
import provmirror      # noqa: F401  provenance

print(f"OK: mirror-stack-mcp installed cleanly — {len(tools)} tools, all mirrors importable")
