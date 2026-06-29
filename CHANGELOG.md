# Changelog

All notable changes to mirror-stack-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.2.0] — 2026-06-29

Single-source the stack's linkage check (P2) + first canonical map of the two surfaces.

### Changed
- **`verify.check_chain` now delegates to measure-mirror's canonical
  `mm.linkage_check`** instead of carrying a parallel copy of the
  format-agnostic prev_seal→seal algorithm. The algorithm had existed in three
  copies that drifted: the inline copy here reported a **malformed-JSON** ledger
  as `"unreadable"` (a file-IO message), while the canonical fn distinguishes
  corrupt from unreadable. One definition → no drift. (measure-mirror is already
  a hard dependency, so this adds no new coupling.)

### Added
- **[`docs/STACK_CANONICAL.md`](docs/STACK_CANONICAL.md)** — the canonical map of
  which surface owns what (measure-mirror `stack/` = conventions + self-verify +
  L2 orchestrator; this package = MCP server + gate CLI + outsider verify CLI),
  and the one shared primitive that is single-sourced.
- Regression tests pinning the single-sourced behaviour and that both entry
  points (CLI + library) give the identical verdict (37 → 40 tests).

### Requires
- **measure-mirror >= 0.18.0** (`mm.linkage_check`). The pinned dependency SHA is
  bumped to the 0.18.0 commit (`fdc35e9`).

---

## [0.1.0]

Initial release — one MCP server exposing all four mirrors (claims · actions ·
provenance · stack verify-all), the `mirror-stack-gate` enforcer CLI, the
zero-config `mirror-stack-verify` outsider CLI, Bitcoin (OpenTimestamps)
anchoring, connect-time discipline instructions, and reminder/verbosity controls.
