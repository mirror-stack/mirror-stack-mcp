"""Actual stdio tools/call, not direct Python invocation. All state is temporary."""
import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_managed_write_replay_and_denial(tmp_path):
    async def run():
        env = {**os.environ, "MIRROR_MCP_ROOT": str(tmp_path.resolve()),
               "MIRROR_MCP_ALLOW_WRITE": "1", "MIRROR_MCP_WRITE_TOOLS": "am_record"}
        server = StdioServerParameters(command=sys.executable,
                                      args=["-m", "mirror_stack_mcp.server"], env=env)
        async with stdio_client(server) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                init = await client.initialize()
                assert init.serverInfo.name == "mirror-stack"
                tools = await client.list_tools()
                assert len(tools.tools) == 22
                arguments = {"ledger_path": "actions.jsonl", "agent": "worker", "action": "test",
                             "operation_id": "wire-1"}
                first = await client.call_tool("am_record", arguments)
                assert not first.isError
                second = await client.call_tool("am_record", arguments)
                assert not second.isError
                assert second.content == first.content
                outside = await client.call_tool("am_record", {**arguments, "operation_id": "wire-2",
                                                               "ledger_path": "../escape.jsonl"})
                assert outside.isError
                missing = await client.call_tool("am_record", {k: v for k, v in arguments.items()
                                                               if k != "operation_id"})
                assert missing.isError
                denied = await client.call_tool("mm_retract", {"ledger_path": "actions.jsonl",
                                                                "claim_id": "c", "reason": "x",
                                                                "operation_id": "wire-3"})
                assert denied.isError
        rows = [json.loads(line) for line in (tmp_path / "actions.jsonl").read_text().splitlines()]
        assert len(rows) == 1

    asyncio.run(asyncio.wait_for(run(), timeout=25))
