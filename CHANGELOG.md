# Changelog

All notable changes to mirror-stack-mcp are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [0.2.9] — 2026-07-21

### Changed
- **measure-mirror pin `28290f2` → `abe0c19` (v0.28.0 → v0.28.1)**. Picks up the
  **`power_check` honesty fix**: the probe hardcoded its critical values
  (`z_alpha2 = 1.96`, `z_beta = 0.842`), so `mm_power_check` printed the
  requested power (e.g. "at 99% power") while the required-n was *always*
  computed at 80% power / α=0.05 — the printed text and number contradicted
  each other. Both z-values now derive from the `alpha`/`target_power`
  arguments via `statistics.NormalDist().inv_cdf` (stdlib, still zero-dep);
  `target_power=0.99` → n≥1829 (was 781), `alpha=0.0001` → n≥2229. Default
  (α=0.05, power=0.80) unchanged. This reaches the `mm_power_check` tool.
- Pin recorded as the **full 40-hex SHA** (the v0.28.0 bump #20 landed a 9-hex
  abbreviation, which broke the cross-repo pin-lag checker; normalized since).

## [0.2.8] — 2026-07-21

### Changed
- **Refreshed action-mirror + provenance-mirror pins to v0.2.0** (both
  `fd46e90`/`8edbbfd` → `fa1fc49`/`321f84a`): picks up the family-wide
  **full 64-hex SHA-256 seal** security upgrade (16-hex/64-bit truncation
  closed the dishonest-sealer birthday-collision gap ~2^32; legacy 16-hex
  seals keep verifying via prefix match, no migration). Completes the stack
  security bump already carried for measure-mirror (v0.27.0) in 0.2.7.
  provenance-mirror pin also includes its [0.2.0] CHANGELOG sync.

## [0.2.7] — 2026-07-21

### Changed
- **measure-mirror pin `13077df` → `690c27e` (v0.26.0 → v0.27.0)**. Picks up, in order:
  - **v0.27.0 — full 64-hex SHA-256 seals** (security, SPEC v1.1): 16-hex truncated
    seals allowed a birthday-search (~2³² hashes) to forge two entries sharing one seal
    and swap them post-seal. Legacy 16-hex seals keep verifying (prefix match) — no
    ledger migration. The stack's L1 chain check inherits the wider digest.
  - **v0.26.1 — ㉗ `prereg_lint` false-positive fix**: an audit of the probe against 64
    real ledgers found ⑫c was reading `baseline` as the chance floor → **44 spurious
    FAILs = 44 wrong compute-gate BLOCKs**. It now uses a declared `chance` only, so a
    below-chance gate BLOCK requires `chance=` on the preregistration.
- Docs: "bar at/below chance" → "bar at/below **declared** chance" (README, connect-time
  DISCIPLINE, `mm_prereg_lint` reminder).

### Fixed
- **`test_compute_gate_blocks_on_lint_fail_below_chance_bar`** now declares `chance=`
  (the corrected contract) + new `test_compute_gate_does_not_block_on_baseline_alone`
  pins the false-positive guard: `pass < baseline` with no declared `chance` must GO.

## [0.2.6] — 2026-07-21

### Added
- **`mm_prereg_lint` tool** (19 tools total) — surfaces measure-mirror's new
  `prereg_lint` (㉗): a seal-*quality* check to run right before spending compute.
  Distinct from `mm_falsifiability_check` (presence) and the `mm_preflight`
  existence gate — it flags a kill-condition leaked into the `metric` field, a
  quantified kill with no structured threshold, a pass bar at/below chance, a
  low `min_n`, or no declared pre-seal machine-checks.
- **`mm_preregister(pre_seal_checks=[...])`** passthrough.

### Changed (deps)
- **measure-mirror pin `e2911ca` → `13077df`** (v0.25.0 → v0.26.0, #28): brings the
  `prereg_lint` probe this release's tool and gate wiring require.

### Changed
- **Compute gate reports a leaked kill-condition** (`gate.py`) — when a
  pre-registration exists but its kill-condition leaked into `metric` (no kill
  fields), `mm_preflight`/`mirror-stack-gate compute` still BLOCKs, now with the
  accurate reason (pointing to `mm_prereg_lint`) instead of the misleading
  "no sealed preregistration".

## [0.2.5] — 2026-07-21

### Changed
- **Refreshed measure-mirror pin** (`3e2aaf24` → `e2911ca`, both v0.25.0):
  picks up measure-mirror #26 (catalog v1.8 / 45 entries — +2 specimens,
  +3 real cases from the cell arc). Docs-only downstream; no probe/API change.

### Fixed
- **Connect-time DISCIPLINE catalog count 39 → 45** (`server.py`) — the illusion
  catalog grew to 45 real sealed cases (measure-mirror #26). Caught by the
  cross-repo checker's CP2 after #26 merged. All 45 are real sealed cases
  (catalog rule: no fabrication — every entry backed by a db/curated line +
  ledger seal), so this is a faithful count, not inflation.

---

## [0.2.4] — 2026-07-09

### Changed
- **Refreshed measure-mirror pin** (`5a61ae4` → `3e2aaf24`, both v0.25.0):
  picks up measure-mirror #25 (catalog specimen `provenance-not-in-the-value`,
  v1.4 / 39 entries). Docs-only downstream; no probe/API change.

### Fixed
- **Connect-time DISCIPLINE catalog count 38 → 39** (`server.py`) — the illusion
  catalog grew to 39 (measure-mirror #25). This stale count was missed by the
  cross-repo checker's CP2 (which only inspected measure-mirror's own READMEs,
  not this server's reference) — the checker's CP2 has since been extended to
  cover this cross-repo reference.

---

## [0.2.3] — 2026-07-09

### Changed
- **Pinned measure-mirror bumped v0.24.0 → v0.25.0** (`08d0ece` → `5a61ae4`):
  picks up the anchor-discipline probes ㉔㉕ (`anchor_line_source_check`,
  `anchor_cell_check` — the other two `anchor-reproduction-failure` catalog
  subtypes, completing the trio with ㉑) and MIRROR-SPEC amendment A2 (optional
  preregister fields `anchor_cell` / `anchor_line_source` / `known_confounds`).
  The umbrella `mm_verify` / `audit` paths reach the new probes; no new
  standalone tool added here.
- **Refreshed provenance-mirror pin** (`be997bf` → `8edbbfd`): docs-only
  ("GENESIS" case-deviation disclosure), version unchanged at 0.1.0.
  action-mirror pin unchanged (already at HEAD).

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
