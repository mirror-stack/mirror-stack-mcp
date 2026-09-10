"""Standalone product contract. All data and approvals stay in temporary folders."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = str(Path(__file__).resolve().parents[1])
if not os.environ.get("PRODUCT_TEST_INSTALLED"):
    sys.path.insert(0, SOURCE)
from mirror_stack_mcp.product import workspace
from mirror_stack_mcp.workspace import write_json
from mirror_stack_mcp import server
if os.environ.get("PRODUCT_TEST_INSTALLED"):
    SOURCE = str(Path(server.__file__).resolve().parents[1])
MODE, TOOL, EFFECT, COMPLETE, PACKAGE = "record", "am_record", "actions.jsonl", "done", "mirror_stack_mcp"
ARGUMENTS = {"ledger_path":"actions.jsonl", "agent":"user", "action":"note", "payload":{"text":"hello"}}

class ProductContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="standalone product ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "workspace"
        self.env = patch.dict(os.environ, {k:v for k,v in os.environ.items()
                                          if not k.startswith(workspace.prefix + "_")}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        workspace.setup(self.root, MODE)

    def test_setup_preserves_data_and_refuses_reinitialize(self):
        data = self.root / "business.txt"
        data.write_text("preserve")
        with self.assertRaises(ValueError):
            workspace.setup(self.root, MODE)
        self.assertEqual(data.read_text(), "preserve")
        self.assertTrue(workspace.doctor(self.root)["ok"])
        connection = workspace.connection(self.root)
        config = connection["mcpServers"][workspace.product]
        self.assertEqual(config["args"][-1], str(self.root))
        self.assertNotIn("lane", json.dumps(config))

    def test_prepare_then_execute_shared_with_mcp(self):
        with workspace.activated(self.root):
            task = server.workspace_prepare(TOOL, ARGUMENTS)
            self.assertEqual(task["state"], "prepared")
            self.assertFalse((self.root / EFFECT).exists())
            first = workspace.execute(self.root, task["task_id"])
            self.assertEqual(first["state"], "returned", first)
            self.assertTrue((self.root / EFFECT).exists(), first)
            snapshot = self.snapshot()
            second = server.workspace_execute(task["task_id"])
            self.assertEqual(first, second)
            self.assertEqual(snapshot, self.snapshot())
            direct = getattr(server, TOOL)(**ARGUMENTS, operation_id=task["task_id"])
            self.assertEqual(direct, first["result"])
            self.assertEqual(snapshot, self.snapshot())
            self.assertEqual(server.workspace_tasks()["tasks"][0]["state"], COMPLETE)

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes()
                for p in self.root.rglob("*") if p.is_file()
                and workspace.control not in p.parts}

    def test_readonly_does_not_elevate_from_writable_profile(self):
        with workspace.activated(self.root):
            os.environ[workspace.prefix + "_MCP_ALLOW_WRITE"] = "0"
            with self.assertRaises(ValueError):
                server.workspace_prepare(TOOL, ARGUMENTS)
        self.assertFalse((self.root / EFFECT).exists())

    def test_changed_task_refused(self):
        with workspace.activated(self.root):
            task = workspace.prepare(self.root, TOOL, ARGUMENTS)
            path = workspace.job_path(self.root, task["task_id"])
            job = json.loads(path.read_text())
            job["arguments"] = {}
            write_json(path, job)
            with self.assertRaises(ValueError):
                workspace.execute(self.root, task["task_id"])
            self.assertFalse((self.root / EFFECT).exists())

    def test_operator_metadata_cannot_be_business_target(self):
        with workspace.activated(self.root):
            if workspace.product == "mirror-stack":
                with self.assertRaises(ValueError):
                    server.am_record(workspace.config_name, "u", "note", operation_id="bad")
            else:
                result = server.verify_gate(workspace.config_name, operation_id="bad")
                self.assertNotEqual(result["exit_code"], 0)
            self.assertEqual(workspace.load(self.root)["mode"], MODE)

    def test_missing_receipt_recovery_retires_old_id(self):
        with workspace.activated(self.root):
            task = workspace.prepare(self.root, TOOL, ARGUMENTS)
            receipt_name = hashlib.sha256(task["task_id"].encode()).hexdigest() + ".json"
            marker = {"receipt": receipt_name}
            if workspace.product == "mirror-stack":
                marker["schema"] = 1
            write_json(self.root / workspace.control / "active.json", marker)
            self.assertFalse(workspace.doctor(self.root)["ok"])
            self.assertTrue(workspace.recover(self.root)["active"]["needs_attention"])
            with self.assertRaises(ValueError):
                workspace.recover(self.root, True, "", True)
            self.assertFalse((self.root / EFFECT).exists())
            got = workspace.execute(self.root, task["task_id"])
            self.assertEqual(got["state"], "needs_attention", got)
            result = workspace.recover(self.root, True, "Inspected files; no surviving child.", True)
            self.assertTrue(result["changed"])
            got = workspace.execute(self.root, task["task_id"])
            self.assertEqual(got["state"], "needs_attention", got)
            self.assertFalse((self.root / EFFECT).exists())
            self.assertEqual(workspace.tasks(self.root)["tasks"][0]["state"], "retired")
            new_task = workspace.prepare(self.root, TOOL, ARGUMENTS)
            self.assertEqual(workspace.execute(self.root, new_task["task_id"])["state"], "returned")

    def test_mode_change_backs_up_and_revokes(self):
        old = workspace.load(self.root)
        workspace.configure(self.root, "observe")
        self.assertEqual(workspace.load(self.root)["mode"], "observe")
        history = list((self.root / workspace.control / "config-history").glob("*.json"))
        self.assertTrue(any(json.loads(p.read_text()) == old for p in history))
        with workspace.activated(self.root), self.assertRaises(ValueError):
            workspace.prepare(self.root, TOOL, ARGUMENTS)
        with self.assertRaises(ValueError):
            workspace.save_config(self.root, old, expected_revision=old["revision"])

    def test_external_grant_exact_file_readonly_and_revocable(self):
        ledger = self.base / "outside.jsonl"
        body = {"prev_seal": "genesis", "claim_id": "c", "metric": "m", "kill_condition": "n < 20"}
        body["seal"] = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        ledger.write_text(json.dumps(body) + "\n")
        original = ledger.read_bytes()
        workspace.link(self.root, ledger)
        with workspace.activated(self.root):
            if workspace.product == "mirror-stack":
                from mirror_stack_mcp.runtime import scoped_path
                self.assertEqual(scoped_path(ledger, external_read=True), str(ledger))
                server.mm_anchor(str(ledger))
                with self.assertRaises(ValueError):
                    server.am_record(str(ledger), "u", "note", operation_id="external-write")
            else:
                from yeoul_mcp.runtime import Policy
                policy = Policy({})
                self.assertEqual(policy.path(str(ledger), external_read=True), ledger)
                with self.assertRaises(ValueError):
                    policy.path(str(ledger))
                arc = self.root / "arc"
                arc.mkdir()
                (arc / ".prereg").write_text("c\n" + str(ledger) + "\nseal\n")
                policy.validate("status", {})
            self.assertEqual(ledger.read_bytes(), original)
        workspace.link(self.root, ledger, remove=True)
        with workspace.activated(self.root):
            if workspace.product == "mirror-stack":
                with self.assertRaises(ValueError):
                    scoped_path(ledger, external_read=True)
            else:
                with self.assertRaises(ValueError):
                    Policy({}).path(str(ledger), external_read=True)
        self.assertEqual(ledger.read_bytes(), original)

    def test_cli_outside_launch_directory(self):
        env = dict(os.environ, PYTHONPATH=SOURCE, PYTHONDONTWRITEBYTECODE="1")
        def cli(*args):
            return subprocess.run([sys.executable, "-B", "-m", PACKAGE + ".product", *args,
                                   "--workspace", str(self.root)], cwd=self.base, env=env,
                                  text=True, capture_output=True, timeout=30)
        self.assertEqual(cli("doctor").returncode, 0)
        result = cli("run", TOOL, "--arguments", json.dumps(ARGUMENTS), "--yes")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        task_id = json.loads(result.stdout)["task_id"]
        self.assertIn("task_id=" + task_id, result.stderr)
        repeated = cli("retry", task_id, "--yes")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(result.stdout), json.loads(repeated.stdout))


    def test_product_stdio_reconnect_replays_task(self):
        import asyncio
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        from mirror_stack_mcp import __version__
        async def run():
            settings = StdioServerParameters(
                command=sys.executable,
                args=["-B", "-m", PACKAGE + ".product", "serve", "--workspace", str(self.root)],
                env=dict(os.environ, PYTHONPATH=SOURCE, PYTHONDONTWRITEBYTECODE="1"))
            async def connect(task_id=None):
                async with stdio_client(settings) as (reader, writer):
                    async with ClientSession(reader, writer) as client:
                        hello = await client.initialize()
                        self.assertEqual(hello.serverInfo.version, __version__)
                        names = {tool.name for tool in (await client.list_tools()).tools}
                        self.assertTrue({"workspace_prepare", "workspace_execute", "workspace_tasks"} <= names)
                        self.assertNotIn("workspace_recover", names)
                        if task_id is None:
                            reply = await client.call_tool("workspace_prepare", {"tool": TOOL, "arguments": ARGUMENTS})
                            self.assertFalse(reply.isError, reply)
                            task_id = json.loads(reply.content[0].text)["task_id"]
                        result = await client.call_tool("workspace_execute", {"task_id": task_id})
                        self.assertFalse(result.isError, result)
                        return task_id, json.loads(result.content[0].text)
            task_id, first = await connect()
            snapshot = self.snapshot()
            _, second = await connect(task_id)
            self.assertEqual(first, second)
            self.assertEqual(first["state"], "returned")
            self.assertEqual(snapshot, self.snapshot())
        asyncio.run(asyncio.wait_for(run(), timeout=60))

if __name__ == "__main__":
    unittest.main()
