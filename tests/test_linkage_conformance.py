"""P2 single-source regression for the outsider verifier's `check_chain`.

`check_chain` now delegates to measure-mirror's canonical `mm.linkage_check`
instead of carrying a parallel copy. The old copy had **drifted**: it reported a
malformed-JSON ledger as "unreadable" (a file-IO message) rather than as
corrupt. These lock in the single-sourced behaviour — and that both entry points
(the package CLI and the library fn) give the identical verdict — so the copy
cannot silently come back.
"""
from measure_mirror.mm import linkage_check

from mirror_stack_mcp import verify


def _w(p, lines):
    p.write_text("\n".join(lines), encoding="utf-8")


def test_malformed_json_is_not_called_unreadable(tmp_path):
    """The drift the single-source fixed: malformed JSON != 'unreadable'."""
    p = tmp_path / "l.jsonl"
    _w(p, ['{"prev_seal":"genesis","seal":"a"}', '{not json}'])
    ok, msg = verify.check_chain(str(p))
    assert not ok
    assert "malformed JSON" in msg and "unreadable" not in msg


def test_missing_file_is_unreadable(tmp_path):
    ok, msg = verify.check_chain(str(tmp_path / "nope.jsonl"))
    assert not ok and "unreadable" in msg


def test_check_chain_agrees_with_canonical(tmp_path):
    """Both entry points share one definition → identical verdict + message."""
    p = tmp_path / "l.jsonl"
    cases = [
        ['{"prev_seal":"genesis","seal":"a"}', '{"prev_seal":"a","seal":"b"}'],   # intact
        ['{"prev_seal":"genesis","seal":"a"}', '{"prev_seal":"WRONG","seal":"b"}'],  # broken
        ['{"prev_seal":"x","seal":"a"}'],                                         # non-genesis
        [],                                                                       # empty
    ]
    for lines in cases:
        _w(p, lines)
        assert verify.check_chain(str(p)) == linkage_check(str(p))[:2]
