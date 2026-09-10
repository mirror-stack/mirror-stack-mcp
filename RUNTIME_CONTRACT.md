# Managed stdio runtime contract

Introduced in v0.3.0; does not automatically change existing client configurations.
The transport remains **stdio**. Start with the [workspace guide](WORKSPACE_GUIDE.md):
`mirror-stack setup` saves a product-owned profile and `mirror-stack serve` applies it.

## Modes and authority

With `MIRROR_MCP_ROOT` unset, the server retains its **trusted-local compatibility
mode**: the caller has the server user's filesystem authority, paths keep their
previous meaning, and managed locking/receipts are not active. A startup warning
goes to stderr, never the MCP stdout stream. Setting an empty/invalid root fails;
it does not silently fall back to trusted mode.

To opt in, set an existing, canonical, absolute workspace in the MCP client's
server environment. These are operator settings, not tool arguments:

```json
{
  "mcpServers": {
    "mirror-stack": {
      "command": "mirror-stack-mcp",
      "env": {
        "MIRROR_MCP_ROOT": "/absolute/project",
        "MIRROR_MCP_ALLOW_WRITE": "1",
        "MIRROR_MCP_WRITE_TOOLS": "mm_preregister,mm_retract,am_record,am_witness,pm_verify"
      }
    }
  }
}
```

- Without `MIRROR_MCP_ALLOW_WRITE=1`, managed mode is business-data read-only.
  Runtime lock metadata may still be created by read calls.
- Optional `MIRROR_MCP_WRITE_TOOLS` is an exact comma-separated allowlist. An empty
  value denies all writers; omission allows writers if ALLOW_WRITE is granted.
- `pm_verify` **writes a provenance ledger** and is therefore a writer, despite its name.
- OTS stamping, upgrading and verification invoke an external program and may use
  the network. They additionally require BOTH `MIRROR_MCP_ALLOW_NETWORK=1` and
  `MIRROR_MCP_ALLOW_EXEC=1`. Neither is enabled by the example.
- The explorer argument must exactly equal operator setting `MIRROR_MCP_EXPLORER`
  (default `https://blockstream.info/api`). This is not a complete network sandbox:
  redirects, OTS calendars and executable behavior still require trusted deployment
  and, where necessary, OS/network egress restrictions. `OTS_BIN` is operator-owned.
- Tool paths resolve against the managed root, not the client's current directory.
  Outside paths, parent traversal, symlinks, hard-linked files, special files and
  targets inside `.mirror-mcp-runtime` or the workspace profile are refused.
  Embedded anchor ledger paths are checked too. `MIRROR_MCP_READ_LEDGERS` is an
  operator-owned JSON array of exact absolute ledger filenames, granting read
  access only in designated ledger inputs. `mirror-stack link/unlink` manages it.
  No external writes or automatic fallback to another project's ledger are allowed.

This boundary is **not authentication of the `agent` string**, per-request human
approval, or an OS sandbox. An operator grants the connection these capabilities.
Use separate restricted processes for different trust levels. An actor able to
rewrite the server, change its environment, race filesystem paths, or invoke the
underlying CLIs directly can bypass this cooperative boundary. Protect the workspace
and runtime control directory with OS permissions. Windows deployments must provision
an owner-only ACL; POSIX mode checks cannot establish a Windows ACL.

## Serialization and state

Managed requests use one exclusive OS-held lock per workspace, including readers,
so cooperating product CLI/MCP processes using the same root do not inspect partially appended ledger writes.
The lock covers validation, ledger verification, execution and receipt persistence.
Waiting is bounded to five seconds; contention returns `BUSY`, never success.
The OS releases the lock when the process dies. **Do not delete the lock file**:
unlinking it could allow a second live lock inode and concurrent writers.

This deliberately favors correctness over parallel throughput. All cooperating
processes must use the same canonical root. Legacy MCPs, direct mm/am/pm calls,
other writers, overlapping but differently configured roots and network filesystems
are not coordinated by this lock. Do not claim distributed or cross-tool locking.

Before managed ledger writes, the complete existing ledger's hashes and links are
checked; empty, malformed, duplicate-key, tampered and unterminated-tail ledgers
are refused. A missing destination may be created. Post-write verification and
fsync precede the completed receipt. No old ledger is rewritten or rehashed.
The original formats and legacy hash-strength limits remain unchanged.

The server's reminder `_shown` set is only presentation state. It resets on restart
and is not an approval, ledger, job queue, or evidence source.

## Delivery retries and interruption

The seven writing tools accept an additional optional `operation_id` parameter:
`mm_preregister`, `mm_retract`, `am_record`, `am_witness`, `pm_verify`,
`mm_anchor_bitcoin`, `mm_anchor_upgrade`. It is **required in managed mode**.
Supplying an ID without managed mode is refused, not silently ignored.

```python
am_record(ledger_path="actions.jsonl", agent="worker", action="result", target="claim-1",
          payload={"status": "fail", "summary": "Observed failure", "prereg_seal": "..."},
          operation_id="lane-12-session-7-result-1")
```

An ID is 1–128 ASCII letters/digits/`_.:-`, starting with a letter or digit. It is
workspace-wide across tools. The receipt stores a digest of normalized tool name
and arguments; it does not store the raw request separately.

1. Persist the workspace's active marker, then a `prepared` receipt, before business
   side effects. A marker pointing to a missing receipt also requires reconciliation.
2. Run under the workspace lock, then persist `done` and the exact returned result.
3. Same ID + same arguments replays the stored result without repeating the work.
4. Same ID + different arguments/tool returns `CONFLICT`.
5. An exception, timeout or crash after preparation leaves `prepared`. Subsequent
   attempts return `RECONCILE_REQUIRED`, even after the process is restarted.
   The active-operation marker also blocks new writes with different IDs until
   reconciliation; read-only tools remain available for diagnosis.

`done` means the tool returned and its response was persisted. It is NOT scientific
success: a persisted response can report failure or a pending Bitcoin confirmation.
Replaying returns the historical response, not a fresh verification of current files.
To deliberately refresh/poll/make a new attempt, use a new ID; do not change IDs to
work around an uncertain outcome. These are guarded retries, **not an exactly-once
transaction spanning external programs, networks, filesystem and receipts**.

Read an operation's status without starting/retrying it:

```bash
python -m mirror_stack_mcp.runtime lane-12-session-7-result-1
```

Set the same `MIRROR_MCP_ROOT` for this diagnostic. `unknown` means no receipt was
found, not proof that nothing ran. For `prepared`, stop writers, preserve the receipt
and inspect the actual ledger/artifacts/child process state. Record an operator's
reconciliation before any new request. There is no tool that deletes pending receipts,
rolls back ledger entries, or automatically marks ambiguous operations successful.

Receipts live in `.mirror-mcp-runtime/<sha256-of-ID>.json`, with owner-only POSIX
permissions and atomic replacement; file and parent directory are fsynced on POSIX.
Windows does not receive a POSIX directory-fsync guarantee. Power-loss behavior still
depends on the storage system. Receipts contain responses and may contain sensitive
data: back them up privately with their workspace, not in public exports. Do not prune
receipts while their IDs can be retried. Removing one removes its deduplication memory.

## Integration and verification

The product exposes `workspace_prepare`, `workspace_execute`, and `workspace_tasks`.
Any consumer, including LaneStack, can retain the returned task ID and use this
public contract. Advanced clients can still persist explicit operation IDs before
sending business-tool calls. Show `BUSY`, `CONFLICT`, `RECONCILE_REQUIRED`, and
business results separately. No consumer owns the product's permissions or state.

Operator-only `mirror-stack recover` defaults to inspection. Explicit acknowledgement
requires a note and a stopped-children attestation. It writes a durable recovery
tombstone before removing only the active pointer; the old ID stays non-retriable
even if its receipt was missing. It does not stop processes or prove consistency.
See the [recovery procedure](WORKSPACE_GUIDE.md).

Tests: `python -m pytest tests/test_runtime_contract.py` exercises real writers,
parallel processes, duplicate delivery, crashes, path/capability denial, invalid
ledgers and actual FastMCP tool schemas. Existing source tests remain separate.
Windows/macOS and installed-wheel verification must be reported for the environments
actually exercised; local Linux success does not certify those platforms.
