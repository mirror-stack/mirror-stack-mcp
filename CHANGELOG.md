# Changelog

All notable changes to mirror-stack-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.2.2] — 2026-07-08

### Changed
- **Pinned measure-mirror bumped v0.22.0 → v0.24.0** (`956c12a` → `08d0ece`):
  picks up v0.23.0 (seal-time `kill_threshold` validation + graceful
  degradation on legacy malformed entries), v0.24.0 (grounding probes ㉑㉒㉓ —
  anchor-basis / threshold-provenance / content-delta — plus MIRROR-SPEC
  amendment A1: optional `anchor_basis` / `threshold_source` preregister
  fields, auto-audited), and v0.22.1 docs. The umbrella `mm_verify` / `audit`
  paths now reach the new probes; no new standalone tool was added.
- **Refreshed action-mirror / provenance-mirror pins** to their latest HEAD
  (`284b0fe` → `fd46e90`, `0a59e19` → `be997bf`): docs-only "ledgers conform to
  MIRROR-SPEC v1.0" commits, versions unchanged at 0.1.0.

### Fixed
- **`tests/test_server.py` fixture used a legacy `kill_threshold` shape**
  (`{"below": 0.5}`) that measure-mirror v0.23.0+ rejects at seal time. Updated
  to the structured form `{"metric", "threshold", "direction"}` so the
  cross-package integration test passes against the bumped pin. (This was a
  latent tripwire: green under the old pin, would have broken on the bump.)

---

## [0.2.1] — 2026-07-02

### Changed
- **Pinned measure-mirror bumped v0.18.0 → v0.22.0** (`fdc35e9` → `956c12a`):
  picks up MIRROR-SPEC v1.0 (ratified & frozen), 4 verify fixes surfaced by
  spec-writing (verify_chain uppercase-genesis false-FAIL; linkage_check
  crashes on non-object JSON lines and non-UTF-8 bytes → now clean malformed
  FAILs), 14 conformance vectors (`spec/vectors/`), and the 30-entry
  illusion catalog (`catalog/`).
- **`mm_retract` reminder now prompts catalog collection** — the moment of
  retraction is the moment a measurement-illusion specimen is born. The
  reminder asks to label the retraction reason with a catalog id
  (measure-mirror `catalog/`, 30 entries) and to add the case to an
  existing entry (same trick) or a new one (new trick, real case + seal
  ref required). Substrate-agnostic: reaches every agent that retracts
  through the MCP, regardless of harness.
- **DISCIPLINE (connect-time instructions) now names the normative spec and
  the catalog** — MIRROR-SPEC v1.0 as the ledger-format authority, and the
  illusion catalog as the scan-before-trusting resource.
- **`docs/STACK_CANONICAL.md`** — added the ledger-format-authority note:
  both surfaces are reference implementations of MIRROR-SPEC v1.0; where
  code and spec disagree, the code is wrong.

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
