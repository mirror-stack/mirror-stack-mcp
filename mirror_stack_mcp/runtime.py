"""Opt-in managed stdio boundary. Files are state; MCP connections are not.

This is cooperative serialization and capability checking, NOT an OS sandbox.
Every writer sharing a workspace must use this boundary and the same root.
"""
import errno
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
from contextlib import contextmanager

from .integrity import read_verified

CONTROL = ".mirror-mcp-runtime"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


class RuntimeRefusal(ValueError):
    """No authorization, conflicting request, or unresolved prior operation."""


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeRefusal("duplicate receipt key")
        result[key] = value
    return result


def managed_root():
    value = os.environ.get("MIRROR_MCP_ROOT")
    if value is None:
        return None
    root = Path(value)
    if not value or not root.is_absolute() or not root.is_dir():
        raise RuntimeRefusal("MIRROR_MCP_ROOT must be an existing absolute workspace")
    if root.resolve() == Path(root.anchor):
        raise RuntimeRefusal("filesystem root is not an allowed workspace")
    if root.resolve() != root:
        raise RuntimeRefusal("MIRROR_MCP_ROOT must be canonical and not a symlink")
    return root


def scoped_path(value, root=None, external_read=False):
    root = root or managed_root()
    if root is None:
        return str(value)
    path = Path(value)
    path = path if path.is_absolute() else root / path
    if ".." in path.parts:
        raise RuntimeRefusal("parent traversal is not permitted")
    try:
        relative = path.relative_to(root)
    except ValueError:
        if external_read:
            from .workspace import checked_path
            grants = json.loads(os.environ.get("MIRROR_MCP_READ_LEDGERS", "[]"))
            if (not isinstance(grants, list) or len(grants) > 100 or
                    any(not isinstance(p, str) or not Path(p).is_absolute() for p in grants)):
                raise RuntimeRefusal("invalid external ledger grants")
            if str(path) in grants and checked_path(path, existing=True).is_file():
                return str(path)
        raise RuntimeRefusal("path is outside MIRROR_MCP_ROOT") from None
    if CONTROL in relative.parts or ".mirror-stack-workspace.json" in relative.parts:
        raise RuntimeRefusal("runtime control files are not tool targets")
    cursor = root
    for part in relative.parts:
        if ":" in part or part.endswith((" ", ".")) or any(ord(c) < 32 for c in part):
            raise RuntimeRefusal("ambiguous path component is not permitted")
        cursor = cursor / part
        if cursor.is_symlink():
            raise RuntimeRefusal("symlink targets are not permitted")
        if cursor.exists():
            info = cursor.lstat()
            if getattr(info, "st_file_attributes", 0) & 0x400:
                raise RuntimeRefusal("reparse point targets are not permitted")
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise RuntimeRefusal("special file targets are not permitted")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise RuntimeRefusal("hard-linked file targets are not permitted")
    return str(path)


def _control(root):
    directory = root / CONTROL
    if directory.is_symlink():
        raise RuntimeRefusal("runtime directory cannot be a symlink")
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if getattr(info, "st_file_attributes", 0) & 0x400:
        raise RuntimeRefusal("runtime directory cannot be a reparse point")
    if not stat.S_ISDIR(info.st_mode):
        raise RuntimeRefusal("invalid runtime directory")
    if os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
        raise RuntimeRefusal("runtime directory must be owner-only (0700)")
    _sync_directory(root)
    return directory


def _private_open(path, flags):
    if path.is_symlink() or (path.exists() and getattr(path.lstat(), "st_file_attributes", 0) & 0x400):
        raise RuntimeRefusal("runtime file cannot be a symlink")
    fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), 0o600)
    info = os.fstat(fd)
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
            (os.name == "posix" and (info.st_uid != os.geteuid() or info.st_mode & 0o077))):
        os.close(fd)
        raise RuntimeRefusal("runtime file must be a private regular file")
    return fd


@contextmanager
def workspace_lock(root, timeout=5.0):
    """OS-held lock: process death releases it; the lock file is NEVER deleted."""
    directory = _control(root)
    fd = _private_open(directory / "workspace.lock", os.O_CREAT | os.O_RDWR)
    acquired = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        end = time.monotonic() + timeout
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError as exc:
                if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= end:
                    raise RuntimeRefusal("BUSY: workspace locked; retry same operation_id") from None
                time.sleep(0.025)
        yield directory
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _sync_directory(directory):
    if os.name == "posix":
        fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _store(path, record):
    raw = _json(record)
    if len(raw.encode("utf-8")) > 16 * 1024 * 1024:
        raise RuntimeRefusal("RECONCILE_REQUIRED: response exceeds receipt 16 MiB limit")
    fd, name = tempfile.mkstemp(prefix=".receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(raw + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        _sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _read_receipt(path):
    fd = _private_open(path, os.O_RDONLY)
    with os.fdopen(fd, encoding="utf-8") as stream:
        if os.fstat(stream.fileno()).st_size > 16 * 1024 * 1024:
            raise RuntimeRefusal("RECONCILE_REQUIRED: oversized receipt")
        try:
            row = json.load(stream, object_pairs_hook=_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
        except (ValueError, UnicodeError):
            raise RuntimeRefusal("RECONCILE_REQUIRED: invalid receipt; preserve it") from None
    if not isinstance(row, dict) or row.get("schema") != 1:
        raise RuntimeRefusal("RECONCILE_REQUIRED: unsupported receipt")
    return row


def receipt_path(root, operation_id):
    if not isinstance(operation_id, str) or not _ID.fullmatch(operation_id):
        raise RuntimeRefusal("operation_id must be 1..128 ASCII letters/digits/_.:-")
    return root / CONTROL / (hashlib.sha256(operation_id.encode()).hexdigest() + ".json")


def operation_status(operation_id):
    """Read-only receipt summary; absence is not evidence that an operation never ran."""
    root = managed_root()
    if root is None:
        raise RuntimeRefusal("operation status requires MIRROR_MCP_ROOT")
    path = receipt_path(root, operation_id)
    if (path.parent / "recovery" / path.name).exists():
        return {"operation_id": operation_id, "status": "retired"}
    if not path.exists() and not path.is_symlink():
        return {"operation_id": operation_id, "status": "unknown"}
    row = _read_receipt(path)
    if row.get("operation_id") != operation_id:
        raise RuntimeRefusal("RECONCILE_REQUIRED: receipt identity mismatch")
    return {key: row.get(key) for key in ("operation_id", "tool", "status", "started_at", "finished_at")}


def _check_ledgers(arguments, names, allow_missing):
    for name in names:
        value = arguments.get(name)
        if not value:
            continue
        for item in value if isinstance(value, list) else [value]:
            path = Path(item)
            if not path.exists() and allow_missing:
                continue
            _, error = read_verified(path)
            if error:
                raise RuntimeRefusal("INVALID_LEDGER: " + error)
            # A complete JSON record without a terminator is readable but not append-safe.
            with path.open("rb") as stream:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) not in (b"\n", b"\r"):
                    raise RuntimeRefusal("INVALID_LEDGER: unterminated tail; explicit recovery required")


def guarded(*, paths=(), write=False, ledgers=(), read_ledgers=(), read_paths=(), network=False):
    """Preserve public signatures for FastMCP; operation_id is explicit on writers."""
    def decorate(function):
        signature = inspect.signature(function)

        @functools.wraps(function)
        def call(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = bound.arguments
            operation_id = arguments.get("operation_id")
            root = managed_root()
            if root is None:
                if operation_id is not None:
                    raise RuntimeRefusal("operation_id requires managed mode: set MIRROR_MCP_ROOT")
                return function(*args, **kwargs)
            if write and os.environ.get("MIRROR_MCP_ALLOW_WRITE") != "1":
                raise RuntimeRefusal("DENIED: managed mode is read-only")
            allowed = os.environ.get("MIRROR_MCP_WRITE_TOOLS")
            if write and allowed is not None and function.__name__ not in allowed.split(","):
                raise RuntimeRefusal("DENIED: tool not in MIRROR_MCP_WRITE_TOOLS")
            if network and (os.environ.get("MIRROR_MCP_ALLOW_NETWORK") != "1" or
                            os.environ.get("MIRROR_MCP_ALLOW_EXEC") != "1"):
                raise RuntimeRefusal("DENIED: this tool requires network and subprocess capabilities")
            if network and "explorer" in arguments:
                approved = os.environ.get("MIRROR_MCP_EXPLORER", "https://blockstream.info/api")
                if arguments["explorer"] != approved:
                    raise RuntimeRefusal("DENIED: explorer is not the operator-approved endpoint")
            receipt = receipt_path(root, operation_id) if write else None
            for name in paths:
                value = arguments.get(name)
                if value is not None and value != "":
                    external = name in read_ledgers or name in read_paths
                    arguments[name] = ([scoped_path(p, root, external) for p in value] if isinstance(value, list)
                                       else scoped_path(value, root, external))
            encoded = _json({"tool": function.__name__, "arguments": arguments}).encode()
            if len(encoded) > 8 * 1024 * 1024:
                raise RuntimeRefusal("request exceeds managed 8 MiB limit")
            digest = hashlib.sha256(encoded).hexdigest()
            with workspace_lock(root):
                # Recheck after waiting, before inspecting receipts or touching inputs.
                for name in paths:
                    value = arguments.get(name)
                    if value:
                        for item in value if isinstance(value, list) else [value]:
                            scoped_path(item, root, name in read_ledgers or name in read_paths)
                if receipt is not None and (root / CONTROL / "recovery" / receipt.name).exists():
                    raise RuntimeRefusal("RECONCILE_REQUIRED: retired operation cannot be retried")
                if receipt is not None and (receipt.exists() or receipt.is_symlink()):
                    previous = _read_receipt(receipt)
                    if previous.get("digest") != digest or previous.get("operation_id") != operation_id:
                        raise RuntimeRefusal("CONFLICT: operation_id already bound to different inputs")
                    if previous.get("status") != "done" or "result" not in previous:
                        raise RuntimeRefusal("RECONCILE_REQUIRED: interrupted operation; do not retry with a new ID")
                    return previous["result"]
                if write:
                    active = root / CONTROL / "active.json"
                    if active.exists() or active.is_symlink():
                        marker = _read_receipt(active)
                        name = marker.get("receipt", "")
                        if not isinstance(name, str) or not re.fullmatch(r"[0-9a-f]{64}\.json", name):
                            raise RuntimeRefusal("RECONCILE_REQUIRED: invalid active operation marker")
                        try:
                            previous = _read_receipt(active.parent / name)
                        except OSError:
                            raise RuntimeRefusal("RECONCILE_REQUIRED: active operation receipt unavailable") from None
                        if previous.get("status") != "done":
                            raise RuntimeRefusal("RECONCILE_REQUIRED: workspace has an interrupted operation")
                    for name in read_ledgers:
                        value = arguments.get(name)
                        for item in value if isinstance(value, list) else [value]:
                            _, error = read_verified(item)
                            if error:
                                raise RuntimeRefusal("INVALID_LEDGER: " + error)
                    _check_ledgers(arguments, ledgers, allow_missing=True)
                    pending = {"schema": 1, "operation_id": operation_id, "tool": function.__name__,
                               "digest": digest, "status": "prepared", "started_at": time.time()}
                    # Arm the workspace first. A crash between these two writes must
                    # block, even if the receipt is still missing and no effect ran.
                    _store(active, {"schema": 1, "receipt": receipt.name})
                    _store(receipt, pending)
                # Exceptions leave the prepared receipt intact, including uncertain timeouts.
                result = function(*bound.args, **bound.kwargs)
                if write:
                    _check_ledgers(arguments, ledgers, allow_missing=False)
                    for name in ledgers:
                        value = arguments.get(name)
                        for item in (value if isinstance(value, list) else [value]) if value else []:
                            with open(item, "r+b") as stream:
                                os.fsync(stream.fileno())
                            _sync_directory(Path(item).parent)
                    # Match first delivery's JSON order to replay, including MCP text blocks.
                    result = json.loads(_json(result))
                    _store(receipt, {**pending, "status": "done", "result": result,
                                     "finished_at": time.time()})
                return result
        if write:
            call.__doc__ = (function.__doc__ or "") + (
                "\nManaged mode requires operation_id and operator-granted write capability. "
                "Reuse the same ID only for delivery retries of the same request; completed "
                "responses replay, changed arguments conflict, interrupted requests require reconciliation.")
        return call
    return decorate


def announce():
    root = managed_root()
    if root is None:
        print("mirror-stack: trusted-local mode; no managed path/receipt/serialization boundary. "
              "Set MIRROR_MCP_ROOT for managed mode.", file=sys.stderr)
    else:
        print("mirror-stack: managed stdio; read-only unless MIRROR_MCP_ALLOW_WRITE=1; "
              "cooperative locking, not an OS sandbox.", file=sys.stderr)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Read a managed operation's receipt status (no recovery writes)")
    parser.add_argument("operation_id")
    args = parser.parse_args()
    try:
        print(_json(operation_status(args.operation_id)))
    except (RuntimeRefusal, OSError) as exc:
        parser.exit(2, str(exc) + "\n")
