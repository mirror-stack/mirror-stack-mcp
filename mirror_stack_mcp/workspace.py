"""Standalone workspace UX, vendored per product; stdlib only.

No dependency on LaneStack or the other product. Operator configuration is not
a sandbox. All business operations dispatch to the same guarded functions as MCP.
"""
import argparse
from contextlib import contextmanager
import hashlib
import importlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import uuid

JOB_ID = re.compile(r"[a-f0-9]{32}\Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def checked_path(value, existing=False):
    path = Path(value).absolute()
    if ".." in path.parts or path.parent == path:
        raise ValueError("Choose one project folder, not a filesystem root.")
    for part in [*reversed(path.parents), path]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked paths are not allowed: " + str(part))
        if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
            raise ValueError("Special files are not allowed.")
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError("Hardlinked files are not allowed.")
    if existing and not path.exists():
        raise ValueError("Path does not exist: " + str(path))
    return path


def read_json(path):
    path = checked_path(path, existing=True)
    if path.stat().st_size > 8 * 1024 * 1024:
        raise ValueError("JSON exceeds 8 MiB.")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Nonfinite JSON: " + value)
    result = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs,
                        parse_constant=constant)
    canonical(result)  # Also rejects overflowed floats.
    return result


def sync_dir(path):
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def write_json(path, value):
    checked_path(path)
    raw = canonical(value)
    if len(raw.encode()) > 8 * 1024 * 1024:
        raise ValueError("JSON exceeds 8 MiB.")
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(raw + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Workspace:
    def __init__(self, product, prefix, control, package, modes, defaults):
        self.product, self.prefix, self.control = product, prefix, control
        self.package, self.modes, self.defaults = package, modes, defaults
        self.config_name = "." + product + "-workspace.json"

    @property
    def runtime(self):
        return importlib.import_module(self.package + ".runtime")

    def tools(self):
        server = importlib.import_module(self.package + ".server")
        return {tool.name: getattr(server, tool.name) for tool in server.mcp._tool_manager.list_tools()
                if not tool.name.startswith("workspace_")}

    def root(self, value):
        root = checked_path(value, existing=True)
        if not root.is_dir():
            raise ValueError("Workspace must be a directory.")
        return root

    def load(self, root):
        root = self.root(root)
        config = read_json(root / self.config_name)
        expected = {"schema", "product", "root", "revision", "mode", "external_ledgers", "verification"}
        if (not isinstance(config, dict) or set(config) != expected or type(config["schema"]) is not int
                or config["schema"] != 1 or config["product"] != self.product or config["root"] != str(root)
                or config["mode"] not in self.modes or not isinstance(config["revision"], str)
                or not isinstance(config["external_ledgers"], list) or len(config["external_ledgers"]) > 100
                or any(not isinstance(p, str) or not Path(p).is_absolute() for p in config["external_ledgers"])
                or (config["verification"] is not None and
                    (not isinstance(config["verification"], dict) or
                     set(config["verification"]) != {"path", "sha256"}))):
            raise ValueError("Invalid or relocated workspace config; do not silently repair it.")
        verification = config["verification"]
        if verification is not None and (not isinstance(verification["path"], str) or
                                        not isinstance(verification["sha256"], str)):
            raise ValueError("Invalid verification approval.")
        return config

    def save_config(self, root, config, initial=False, expected_revision=None):
        with self.runtime.workspace_lock(root):
            path = root / self.config_name
            if initial and path.exists():
                raise ValueError("Already configured; use configure, not setup.")
            history = root / self.control / "config-history"
            checked_path(history)
            history.mkdir(mode=0o700, exist_ok=True)
            if path.exists():
                previous = self.load(root)
                if expected_revision is not None and previous["revision"] != expected_revision:
                    raise ValueError("Configuration changed concurrently; reload before updating.")
                write_json(history / (uuid.uuid4().hex + ".json"), previous)
            write_json(path, config)

    def setup(self, folder, mode):
        if mode not in self.modes:
            raise ValueError("Unknown mode.")
        root = checked_path(folder)
        if (root / self.config_name).exists():
            raise ValueError("Already configured; no files changed.")
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = dict(schema=1, product=self.product, root=str(root), revision=uuid.uuid4().hex,
                      mode=mode, external_ledgers=[], verification=None)
        self.save_config(root, config, initial=True)
        return {"workspace": str(root), "mode": mode, "next": self.product + " doctor --workspace " + str(root)}

    def configure(self, root, mode):
        config = self.load(root)
        revision = config["revision"]
        if mode not in self.modes:
            raise ValueError("Unknown mode.")
        config.update(mode=mode, revision=uuid.uuid4().hex)
        # Mode changes revoke shell approval, never silently keep an old execution grant.
        config["verification"] = None
        self.save_config(Path(root), config, expected_revision=revision)
        return config

    def environment(self, config):
        root = config["root"]
        allowed = self.modes[config["mode"]]
        env = {self.prefix + "_MCP_ROOT": root,
               self.prefix + "_MCP_ALLOW_WRITE": "1" if allowed else "0",
               self.prefix + "_MCP_WRITE_TOOLS": ",".join(allowed),
               self.prefix + "_MCP_ALLOW_EXEC": "0",
               self.prefix + "_MCP_ALLOW_NETWORK": "0",
               self.prefix + "_MCP_READ_LEDGERS": canonical(config["external_ledgers"])}
        if self.product == "yeoul":
            env.update(YEOUL_PROJECTS=str(Path(root) / "projects"),
                       YEOUL_INDEX=str(Path(root) / "KNOWLEDGE_INDEX.md"),
                       YEOUL_CLOSED_REGISTRY=str(Path(root) / "registry/closed_questions.jsonl"))
            approval = config["verification"]
            if config["mode"] == "develop" and approval:
                path = checked_path(approval["path"], existing=True)
                if not path.is_relative_to(Path(root) / ".yeoul-approved"):
                    raise ValueError("Approved baseline must be inside .yeoul-approved.")
                if hashlib.sha256(path.read_bytes()).hexdigest() != approval["sha256"]:
                    raise ValueError("Approved baseline changed; re-approval required.")
                env.update(YEOUL_MCP_ALLOW_EXEC="1", YEOUL_MCP_VERIFY_BASELINE=str(path),
                           YEOUL_MCP_VERIFY_BASELINE_SHA256=approval["sha256"])
        return env

    @contextmanager
    def activated(self, root):
        config = self.load(root)
        # Only CLI/startup uses this. MCP task tools never elevate by loading a profile.
        previous = dict(os.environ)
        clean = [key for key in os.environ if key.startswith(self.prefix + "_")]
        try:
            for key in clean:
                os.environ.pop(key, None)
            os.environ.update(self.environment(config))
            yield config
        finally:
            os.environ.clear()
            os.environ.update(previous)

    def connection(self, root):
        self.load(root)
        return {"mcpServers": {self.product: {
            "command": sys.executable,
            "args": ["-m", self.package + ".product", "serve", "--workspace", str(self.root(root))]
        }}}

    def require_managed(self, root):
        value = os.environ.get(self.prefix + "_MCP_ROOT")
        if not value or self.root(value) != self.root(root):
            raise ValueError("Start this workspace's managed server before preparing tasks.")

    def job_path(self, root, job_id):
        if not isinstance(job_id, str) or not JOB_ID.fullmatch(job_id):
            raise ValueError("Invalid task ID.")
        return Path(root) / self.control / "tasks" / (job_id + ".json")

    def load_job(self, root, job_id):
        job = read_json(self.job_path(root, job_id))
        if (not isinstance(job, dict) or set(job) != {"schema", "id", "tool", "arguments", "created", "digest"}
                or type(job["schema"]) is not int or job["schema"] != 1 or job["id"] != job_id
                or not isinstance(job["tool"], str) or not isinstance(job["arguments"], dict)
                or "operation_id" in job["arguments"] or type(job["created"]) not in (int, float)):
            raise ValueError("Invalid task record; preserve it for inspection.")
        unsigned = {k: v for k, v in job.items() if k != "digest"}
        if hashlib.sha256(canonical(unsigned).encode()).hexdigest() != job["digest"]:
            raise ValueError("Task record changed; refusing execution.")
        return job

    def prepare(self, root, tool, arguments):
        self.require_managed(root)
        if not isinstance(arguments, dict) or "operation_id" in arguments:
            raise ValueError("Arguments must be an object; task IDs are managed internally.")
        tools = self.tools()
        if tool not in tools:
            raise ValueError("Unknown business tool.")
        fn = tools[tool]
        inspect.signature(fn).bind(**arguments)
        if "operation_id" in inspect.signature(fn).parameters:
            if os.environ.get(self.prefix + "_MCP_ALLOW_WRITE") != "1":
                raise ValueError("This workspace is read-only.")
            allowed = os.environ.get(self.prefix + "_MCP_WRITE_TOOLS")
            if allowed is not None and tool not in allowed.split(","):
                raise ValueError("This tool is not permitted in the selected mode.")
        job = dict(schema=1, id=uuid.uuid4().hex, tool=tool, arguments=arguments, created=time.time())
        job["digest"] = hashlib.sha256(canonical(job).encode()).hexdigest()
        with self.runtime.workspace_lock(Path(root)):
            directory = self.job_path(root, job["id"]).parent
            checked_path(directory)
            directory.mkdir(mode=0o700, exist_ok=True)
            write_json(self.job_path(root, job["id"]), job)
        return {"task_id": job["id"], "state": "prepared", "tool": tool,
                "message": "Task prepared. Retain this ID before execution and reuse it for delivery retries."}

    def execute(self, root, job_id):
        self.require_managed(root)
        with self.runtime.workspace_lock(Path(root)):
            job = self.load_job(root, job_id)
        tools = self.tools()
        if job["tool"] not in tools:
            raise ValueError("Tool no longer exists; task cannot be migrated silently.")
        fn = tools[job["tool"]]
        arguments = dict(job["arguments"])
        if "operation_id" in inspect.signature(fn).parameters:
            arguments["operation_id"] = job_id
        try:
            result = fn(**arguments)
        except (ValueError, OSError) as exc:
            text = str(exc)
            state = "needs_attention" if "RECONCILE" in text or "CONFLICT" in text else "blocked"
            return {"task_id": job_id, "state": state, "error": text,
                    "message": "Stopped. Inspect the workspace with doctor or recover."}
        if isinstance(result, dict) and result.get("runtime_status"):
            return {"task_id": job_id, "state": "needs_attention", "result": result,
                    "message": "Inspection required. Do not bypass an uncertain operation with a new task ID."}
        return {"task_id": job_id, "state": "returned", "result": result,
                "message": "Tool response delivered. Execution completion is not verification success."}

    def receipt(self, root, job_id):
        path = Path(root) / self.control / (hashlib.sha256(job_id.encode()).hexdigest() + ".json")
        if (path.parent / "recovery" / path.name).exists():
            return {"state": "retired", "note": "Operator reconciled; this ID cannot execute again."}
        if not path.exists():
            return {"state": "not_recorded", "note": "No receipt is not proof of no effects."}
        row = self.runtime._read_receipt(path) if self.product == "mirror-stack" else self.runtime.read_json(path)
        state = row.get("status", row.get("state"))
        return {"state": state, "tool": row.get("tool", (row.get("request") or {}).get("tool"))}

    def tasks(self, root):
        directory = Path(root) / self.control / "tasks"
        checked_path(directory)
        out = []
        if directory.exists():
            for path in sorted(directory.glob("*.json"), key=lambda p: p.name):
                if len(out) >= 1000:
                    break
                job = self.load_job(root, path.stem)
                out.append({"task_id": job["id"], "tool": job["tool"], "created": job["created"],
                            **self.receipt(root, job["id"])})
        return {"tasks": out, "limit": 1000, "message": "Status inspection does not execute tasks or clear pending state."}

    def active(self, root):
        path = Path(root) / self.control / "active.json"
        if not path.exists():
            return None
        reader = self.runtime._read_receipt if self.product == "mirror-stack" else self.runtime.read_json
        marker = reader(path)
        name = marker.get("receipt")
        if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}\.json", name):
            raise ValueError("Invalid active marker; restore metadata from evidence.")
        receipt = path.parent / name
        if not receipt.exists():
            return {"receipt": name, "state": "missing", "needs_attention": True}
        row = reader(receipt)
        state = row.get("status", row.get("state"))
        return {"receipt": name, "state": state, "needs_attention": state not in ("done", "complete")}

    def doctor(self, root):
        checks = []
        try:
            config = self.load(root)
            self.environment(config)
            checks.append({"name": "workspace/config", "ok": True})
        except (ValueError, OSError) as exc:
            return {"ok": False, "checks": [{"name": "workspace/config", "ok": False, "error": str(exc)}]}
        try:
            active = self.active(root)
            checks.append({"name": "pending operation", "ok": not active or not active["needs_attention"],
                           "detail": active})
        except (ValueError, OSError) as exc:
            checks.append({"name": "pending operation", "ok": False, "error": str(exc)})
        if self.product == "yeoul":
            try:
                from .server import bash_command
                bash = bash_command()
                found = Path(bash).is_file() if Path(bash).is_absolute() else shutil.which(bash)
                checks.append({"name": "Bash", "ok": bool(found)})
            except OSError as exc:
                checks.append({"name": "Bash", "ok": False, "error": str(exc)})
        for value in config["external_ledgers"]:
            try:
                checked_path(value, existing=True)
                checks.append({"name": "linked ledger", "path": value, "ok": True})
            except (ValueError, OSError) as exc:
                checks.append({"name": "linked ledger", "path": value, "ok": False, "error": str(exc)})
        return {"ok": all(row["ok"] for row in checks), "checks": checks,
                "mode": config["mode"], "scope": "configuration and local prerequisites; not business verification",
                "message": "Readiness check only; not certification of ledger truth or business success."}

    def link(self, root, ledger, remove=False):
        config = self.load(root)
        revision = config["revision"]
        path = checked_path(ledger, existing=not remove)
        if not remove and not path.is_file():
            raise ValueError("Select one ledger file, not a directory.")
        if remove:
            config["external_ledgers"] = [p for p in config["external_ledgers"] if p != str(path)]
        elif str(path) not in config["external_ledgers"]:
            if self.product == "mirror-stack":
                from .integrity import read_verified
                _, error = read_verified(path)
                if error:
                    raise ValueError(error)
            else:
                from .server import BIN
                spec = importlib.util.spec_from_file_location("_yeoul_prereg_check", BIN / "prereg_check.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.read_verified(path)
            config["external_ledgers"].append(str(path))
        config["revision"] = uuid.uuid4().hex
        self.save_config(Path(root), config, expected_revision=revision)
        return {"ledger": str(path), "access": "revoked" if remove else "read-only",
                "message": "Reconnect to apply the change. The source ledger was not modified."}

    def recover(self, root, acknowledge=False, note="", children_stopped=False):
        self.load(root)
        if not acknowledge:
            return {"active": self.active(root), "tasks": self.tasks(root),
                    "message": "Preserve business data and receipts. Inspect changed files and surviving children. No automatic retry."}
        if not note.strip() or not children_stopped:
            raise ValueError("A reconciliation note and --children-stopped are required.")
        with self.runtime.workspace_lock(Path(root)):
            active = self.active(root)
            if not active or not active["needs_attention"]:
                return {"changed": False, "message": "No interrupted active operation to reconcile."}
            directory = Path(root) / self.control / "recovery"
            checked_path(directory)
            directory.mkdir(mode=0o700, exist_ok=True)
            record = {"schema": 1, "active": active, "note": note.strip(),
                      "children_stopped_attested": True, "time": time.time(),
                      "scope": "operator attestation, not automatic verification"}
            # A deterministic tombstone also blocks replay when the original receipt
            # was never created. Both low-level and product entrypoints check it.
            write_json(directory / active["receipt"], record)
            # Remove ONLY the pointer, under its own workspace lock, after durable audit.
            # The old pending receipt remains non-retriable.
            (Path(root) / self.control / "active.json").unlink()
            sync_dir(Path(root) / self.control)
            return {"changed": True, "message": "Reconciliation recorded. The interrupted task is retired; only new work may proceed."}

    def approve(self, root, todo):
        if self.product != "yeoul":
            raise ValueError("Verification approval is a Yeoul operator function.")
        config = self.load(root)
        revision = config["revision"]
        if config["mode"] != "develop":
            raise ValueError("Select develop mode first.")
        path = checked_path(todo, existing=True)
        if not path.is_relative_to(Path(root)):
            raise ValueError("TODO must be inside this workspace.")
        from .server import BIN
        # Import the same verifier without executing any verification command.
        spec = importlib.util.spec_from_file_location("_yeoul_verify_core", BIN / "verify_core.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        content = path.read_text(encoding="utf-8")
        if not module.eligible(content):
            raise ValueError("TODO has missing/invalid verification criteria.")
        directory = Path(root) / ".yeoul-approved"
        checked_path(directory)
        directory.mkdir(mode=0o700, exist_ok=True)
        baseline = directory / (uuid.uuid4().hex + ".json")
        write_json(baseline, {"version": 1, "todo": str(path), "text": module.canonical(content)})
        config.update(verification={"path": str(baseline),
                                    "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest()},
                      revision=uuid.uuid4().hex)
        self.save_config(Path(root), config, expected_revision=revision)
        return {"approved": str(baseline), "message": "Commands approved. OS isolation is still required where needed. Reconnect to apply."}

    def cli(self, argv=None):
        parser = argparse.ArgumentParser(prog=self.product, description="Standalone workspace setup, execution and diagnosis")
        parser.add_argument("--workspace", default=os.getcwd())
        sub = parser.add_subparsers(dest="command")
        def command(name):
            p = sub.add_parser(name)
            p.add_argument("--workspace", default=argparse.SUPPRESS)
            return p
        for name in ("setup", "configure"):
            p = command(name)
            p.add_argument("folder", nargs="?")
            p.add_argument("--mode", choices=list(self.modes), default=None)
            p.add_argument("--yes", action="store_true")
        for name in ("doctor", "connect", "tasks", "serve"):
            command(name)
        p = command("run")
        p.add_argument("tool")
        p.add_argument("--arguments", default="{}")
        p.add_argument("--yes", action="store_true")
        p = command("retry")
        p.add_argument("task_id")
        p.add_argument("--yes", action="store_true")
        for name in ("link", "unlink"):
            p = command(name)
            p.add_argument("ledger")
            p.add_argument("--yes", action="store_true")
        p = command("recover")
        p.add_argument("--acknowledge", action="store_true")
        p.add_argument("--children-stopped", action="store_true")
        p.add_argument("--note", default="")
        p.add_argument("--yes", action="store_true")
        p = command("approve")
        p.add_argument("todo")
        p.add_argument("--yes", action="store_true")
        for name, (tool, parameter, default) in self.defaults.items():
            p = command(name)
            p.add_argument(parameter, nargs="?", default=default)
            p.add_argument("--yes", action="store_true")
        args = parser.parse_args(argv)
        root = args.workspace
        cmd = args.command
        def confirm(message):
            if getattr(args, "yes", False):
                return
            if not sys.stdin.isatty():
                raise ValueError("Interactive approval required; review first, then use --yes.")
            if input(message + " [y/N] ").strip().lower() not in ("y", "yes"):
                raise ValueError("Cancelled. No changes made.")
        try:
            if cmd is None:
                parser.print_help()
                print("\nStart here: " + self.product + " setup")
                return 0
            if cmd in ("setup", "configure"):
                folder = args.folder or root
                if not args.folder and sys.stdin.isatty():
                    folder = input("Workspace folder [%s]: " % folder).strip() or folder
                mode = args.mode or "observe"
                if not args.mode and sys.stdin.isatty():
                    mode = input("Mode %s [%s]: " % ("/".join(self.modes), mode)).strip() or mode
                confirm("Configure folder %s / mode %s for %s." % (folder, mode, self.product))
                result = self.setup(folder, mode) if cmd == "setup" else self.configure(self.root(folder), mode)
            elif cmd == "doctor":
                result = self.doctor(root)
            elif cmd == "connect":
                result = self.connection(root)
            elif cmd == "serve":
                with self.activated(root):
                    importlib.import_module(self.package + ".server").main()
                return 0
            elif cmd == "tasks":
                result = self.tasks(self.root(root))
            elif cmd == "recover":
                if args.acknowledge:
                    confirm("Clear only the pending marker after operator inspection of files and surviving processes.")
                result = self.recover(self.root(root), args.acknowledge, args.note, args.children_stopped)
            elif cmd in ("link", "unlink"):
                confirm("Change external ledger read permission: " + cmd + " " + args.ledger)
                result = self.link(self.root(root), args.ledger, remove=cmd == "unlink")
            elif cmd == "approve":
                path = checked_path(args.todo, existing=True)
                print(path.read_text(encoding="utf-8"), file=sys.stderr)
                confirm("These commands run with the server account's authority. Approve these criteria and commands?")
                result = self.approve(self.root(root), str(path))
            elif cmd in ("run", "retry") or cmd in self.defaults:
                with self.activated(root):
                    if cmd == "retry":
                        confirm("Resume this task. Completed responses replay; interrupted tasks do not execute again.")
                        result = self.execute(self.root(root), args.task_id)
                    else:
                        if cmd in self.defaults:
                            tool, parameter, _ = self.defaults[cmd]
                            values = {parameter: getattr(args, parameter)}
                            if self.product == "mirror-stack" and cmd == "record":
                                values = dict(ledger_path="actions.jsonl", agent="user", action="note",
                                              payload={"text": values["text"]})
                        else:
                            tool, values = args.tool, json.loads(args.arguments)
                        if tool in self.tools() and "operation_id" in inspect.signature(self.tools()[tool]).parameters:
                            confirm("Execute task: %s %s" % (tool, canonical(values)))
                        task = self.prepare(self.root(root), tool, values)
                        print("task_id=" + task["task_id"], file=sys.stderr, flush=True)
                        result = self.execute(self.root(root), task["task_id"])
            else:
                raise ValueError("Unknown command.")
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if isinstance(result, dict):
                if result.get("ok") is False or result.get("state") in ("blocked", "needs_attention"):
                    return 2
                business = result.get("result")
                if isinstance(business, dict) and business.get("exit_code", 0) != 0:
                    return 1
                if isinstance(business, dict) and (business.get("ok") is False or business.get("decision") == "BLOCK"):
                    return 1
                if isinstance(business, list) and any("FAIL" in str(item) for item in business):
                    return 1
            return 0
        except (ValueError, OSError, KeyError, TypeError) as exc:
            print("Stopped: " + str(exc), file=sys.stderr)
            return 2
