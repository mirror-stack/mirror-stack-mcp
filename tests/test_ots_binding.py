"""Proof -> manifest -> ledger binding, and earliest-attestation selection.

`ots info` and the block explorer are faked: the cloud CI has neither the calendars'
real proofs for a test ledger nor guaranteed network access. The fake `ots info` text
mirrors the real layout (checked against a real 2026-07-25 proof): the file digest on
the first line, and each merkle-root comment right AFTER its attestation line, with the
earliest block NOT listed first.
"""
import hashlib
from pathlib import Path

import pytest
from measure_mirror import mm

from mirror_stack_mcp import ots_anchor as o
from mirror_stack_mcp import verify

ROOT_LATE, ROOT_EARLY = "d" * 64, "f" * 64
BLOCKS = {959655: ROOT_LATE, 959599: ROOT_EARLY}


def _fake_info(digest):
    return (f"File sha256 hash: {digest}\n"
            "Timestamp:\n"
            "append aa\nsha256\n"
            " -> append bb\n"
            "    verify BitcoinBlockHeaderAttestation(959655)\n"
            f"    # Bitcoin block merkle root {ROOT_LATE}\n"
            " -> append cc\n"
            "    verify BitcoinBlockHeaderAttestation(959599)\n"
            f"    # Bitcoin block merkle root {ROOT_EARLY}\n")


@pytest.fixture
def anchored(tmp_path, monkeypatch):
    led = tmp_path / "claims.jsonl"
    for cid in ("c1", "c2"):
        mm.preregister(str(led), cid, metric="acc", min_n=10, baseline=0.5,
                       pass_threshold=0.6, kill_condition="acc < 0.55")
    man, sha = o.build_manifest([str(led)], str(tmp_path / "anchors"))
    proof = man + ".ots"
    Path(proof).write_bytes(b"fake")
    mm.preregister(str(led), "c3_after_stamp", metric="acc", min_n=10, baseline=0.5,
                   pass_threshold=0.6)
    state = {"digest": sha}
    monkeypatch.setattr(o, "_info", lambda p: _fake_info(state["digest"]))
    monkeypatch.setattr(o, "_explorer_block",
                        lambda h, e: (f"hash{h}", BLOCKS[h], 1785000000))
    return led, Path(man), Path(proof), state


def test_attestations_pair_each_root_with_its_block():
    assert o._attestations(_fake_info("0" * 64)) == [(959655, ROOT_LATE), (959599, ROOT_EARLY)]


def test_verify_uses_the_earliest_block(anchored):
    _, _, proof, _ = anchored
    r = o.verify(str(proof))
    assert r["block_height"] == 959599
    assert r["expected_merkle_root"] == ROOT_EARLY
    assert r["verified"] is True
    assert r["attested_blocks"] == [959599, 959655]


def test_bind_reports_only_the_pinned_prefix(anchored):
    led, man, proof, _ = anchored
    r = o.bind(str(led), str(man), str(proof))
    assert r["bound"] is True
    assert r["existed_before"]["block_height"] == 959599
    assert [e["claim_id"] for e in r["covered_entries"]] == ["c1", "c2"]
    assert [e["claim_id"] for e in r["uncovered_entries"]] == ["c3_after_stamp"]
    assert {e["type"] for e in r["covered_entries"]} == {"preregistration"}


def test_proof_for_another_file_does_not_bind(anchored):
    led, man, proof, state = anchored
    state["digest"] = hashlib.sha256(b"some other manifest").hexdigest()
    r = o.bind(str(led), str(man), str(proof))
    assert r["bound"] is False and r["proof_matches_manifest"] is False
    assert "does not stamp this manifest" in r["note"]


def test_rewritten_ledger_does_not_bind(anchored):
    led, man, proof, _ = anchored
    lines = led.read_text(encoding="utf-8").splitlines(keepends=True)
    led.write_text(lines[1] + lines[0] + lines[2], encoding="utf-8")
    r = o.bind(str(led), str(man), str(proof))
    assert r["bound"] is False and r["manifest_pins_ledger"] is False


def test_explorer_mismatch_does_not_bind(anchored, monkeypatch):
    led, man, proof, _ = anchored
    monkeypatch.setattr(o, "_explorer_block", lambda h, e: (f"hash{h}", "e" * 64, 1785000000))
    r = o.bind(str(led), str(man), str(proof))
    assert r["bound"] is False
    assert r["proof_matches_manifest"] is True and r["manifest_pins_ledger"] is True


def test_cli_reports_external_time_only_when_bound(anchored, capsys):
    led, man, proof, state = anchored
    assert verify.main([str(led), "--ots", str(proof), "--manifest", str(man)]) == 0
    out = capsys.readouterr().out
    assert "[EXTERNAL_TIME] the first 2 ledger lines existed before Bitcoin block 959599" in out
    assert "preregistrations covered: c1, c2" in out
    assert "1 later line(s) are NOT covered" in out
    assert "UNVERIFIED" not in out

    state["digest"] = "0" * 64
    assert verify.main([str(led), "--ots", str(proof), "--manifest", str(man)]) == 1
    out = capsys.readouterr().out
    assert "[EXTERNAL_TIME] not established" in out
    assert "ledger precedence UNVERIFIED" in out


def test_cli_manifest_without_proof_fails(anchored, capsys):
    led, man, _, _ = anchored
    assert verify.main([str(led), "--manifest", str(man)]) == 1
