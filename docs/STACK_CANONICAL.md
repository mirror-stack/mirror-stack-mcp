# Mirror Stack — canonical surfaces & the one shared primitive

Two repos make up the running stack. They are **different surfaces, not
duplicates** — keep them separate. This is the canonical map of who owns what,
so "which one is authoritative?" has a written answer.

> **Ledger format authority**: the normative definition of the ledger format
> itself (seal algorithm, chain rules, record types, verification levels) is
> **[MIRROR-SPEC v1.0](https://github.com/bhyi4/measure-mirror/blob/main/docs/SPEC.md)**
> (ratified & frozen 2026-07-02). Everything below — both surfaces, all
> verifiers — is a *reference implementation* of that spec; where code and
> spec disagree, the code is wrong. Conformance vectors: measure-mirror
> `spec/vectors/`.

## The two surfaces (division of labour)

| Surface | Lives in | Owns |
|---|---|---|
| **measure-mirror `stack/`** | [`bhyi4/measure-mirror`](https://github.com/bhyi4/measure-mirror) `stack/` | the stack **conventions + honesty docs** (`MIRROR_STACK.md`, `DISCIPLINE.md`, `PILLARS.md`, the case study); **`verify_self.py`** (one claims ledger: L1 self-chain + L3 anchors, zero external tool); **`verify_all.py`** (the orchestrator — adds L2 cross-witness *between* ledgers via `am`); `tombstone.py` |
| **mirror-stack-mcp** | this repo | the **agent MCP server** (`server.py`, 18 tools); the **`mirror-stack-gate`** enforcer CLI (`gate.py`); the **zero-config outsider** `mirror-stack-verify` CLI (`verify.py`); Bitcoin/OTS anchoring (`ots_anchor.py`) |

Rule of thumb: **measure-mirror `stack/` = the conventions and the self/orchestrated
verification that ships with the library**; **mirror-stack-mcp = how an *agent* (MCP)
or an *outsider* (CLI) reaches the stack**. Merging them would mash a library's
own verification layer into an agent-facing server. Don't.

## The one shared primitive — single-sourced

There is exactly **one** piece of logic both surfaces need: the *format-agnostic*
`prev_seal → seal` linkage check (works on any mirror ledger — claims, actions,
provenance — because it does not recompute any mirror's own seal).

It used to exist in **three** copies that had **drifted** (one even reported a
malformed-JSON ledger as "unreadable"). It is now single-sourced:

```
measure_mirror.mm.linkage_check(path) -> (ok, message, entries)   ← CANONICAL
        ├── stack/verify_self.py : generic_linkage(...)   delegates
        └── mirror_stack_mcp/verify.py : check_chain(...)  delegates
```

- **`mm.linkage_check`** — canonical, stdlib-only, format-agnostic. Linkage only.
- **`mm.verify_chain`** — the *stronger* sibling: it additionally recomputes
  measure-mirror's own SHA-256 seal. Not duplicated — a different, mm-specific
  check used by `verify_self`'s L1 seal step.

Because `linkage_check` is the single source, the two verifiers cannot diverge;
a conformance/regression test on each side asserts they agree.
