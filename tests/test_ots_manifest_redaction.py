import json
from pathlib import Path

import pytest

from mirror_stack_mcp.ots_anchor import build_manifest, ledger_id, locate_ledger


def _ledger(tmp_path, name, lines):
    p = tmp_path / "ledgers" / name
    p.parent.mkdir(exist_ok=True)
    p.write_text("".join(json.dumps({"seal": s}) + "\n" for s in lines), encoding="utf-8")
    return p


def test_format1_unchanged(tmp_path):
    led = _ledger(tmp_path, "secret_project.jsonl", ["a1"])
    man, _ = build_manifest([str(led)], str(tmp_path / "out"))
    d = json.loads(Path(man).read_text(encoding="utf-8"))
    assert "format" not in d
    assert d["ledgers"][0]["ledger"] == "secret_project.jsonl"
    assert d["ledgers"][0]["path"] == str(led)


def test_format2_hides_names_and_paths(tmp_path):
    led = _ledger(tmp_path, "secret_project.jsonl", ["a1", "a2"])
    idmap = tmp_path / "private" / "ids.json"
    man, _ = build_manifest([str(led)], str(tmp_path / "out"), id_map_path=str(idmap))
    text = Path(man).read_text(encoding="utf-8")
    assert "secret_project" not in text and str(tmp_path) not in text
    d = json.loads(text)
    assert d["format"] == 2 and "path" not in d["ledgers"][0] and "ledger" not in d["ledgers"][0]
    salt = json.loads(idmap.read_text(encoding="utf-8"))["salts"]["secret_project.jsonl"]
    assert d["ledgers"][0]["ledger_id"] == ledger_id("secret_project.jsonl", salt)


def test_ids_stable_across_runs_and_salts_per_ledger(tmp_path):
    a = _ledger(tmp_path, "a.jsonl", ["x"])
    b = _ledger(tmp_path, "b.jsonl", ["y"])
    idmap = str(tmp_path / "private" / "ids.json")
    m1, _ = build_manifest([str(a), str(b)], str(tmp_path / "out"), id_map_path=idmap)
    m2, _ = build_manifest([str(a), str(b)], str(tmp_path / "out"), id_map_path=idmap)
    ids = lambda m: [r["ledger_id"] for r in json.loads(Path(m).read_text())["ledgers"]]
    assert ids(m1) == ids(m2)
    salts = json.loads(Path(idmap).read_text())["salts"]
    assert salts["a.jsonl"] != salts["b.jsonl"]


def test_id_map_must_stay_outside_published_dir(tmp_path):
    led = _ledger(tmp_path, "a.jsonl", ["x"])
    out = tmp_path / "out"
    with pytest.raises(ValueError):
        build_manifest([str(led)], str(out), id_map_path=str(out / "ids.json"))


def test_locate_ledger_after_append_both_formats(tmp_path):
    led = _ledger(tmp_path, "a.jsonl", ["x1", "x2"])
    idmap = str(tmp_path / "private" / "ids.json")
    m1, _ = build_manifest([str(led)], str(tmp_path / "out"))
    m2, _ = build_manifest([str(led)], str(tmp_path / "out"), id_map_path=idmap)
    with open(led, "a", encoding="utf-8") as f:
        f.write(json.dumps({"seal": "x3"}) + "\n")
    salt = json.loads(Path(idmap).read_text())["salts"]["a.jsonl"]
    r1 = locate_ledger(m1, str(led))
    r2 = locate_ledger(m2, str(led), name="a.jsonl", salt_hex=salt)
    assert r1["found"] and r1["pinned_lines"] == 2 and not r1["exact"]
    assert r2["found"] and r2["format"] == 2 and r2["name_matches"] is True
    assert locate_ledger(m2, str(led), name="b.jsonl", salt_hex=salt)["name_matches"] is False
