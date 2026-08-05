"""Every git pin must point at the commit its version label claims.

Found by a family-wide consistency audit: the `action-mirror` and
`provenance-mirror` pins were both commented `# v0.2.0` while sitting TWO
commits *before* the v0.2.0 tag. The two missing commits were the org migration
(`bhyi4/` → `mirror-stack/`) and the SPEC v1.1 reference update — so anyone
installing this package got pre-migration docs under a v0.2.0 label.

A pin whose comment names a release it does not point to is a lie the installer
cannot see, which is exactly the defect class this stack exists to catch.
"""
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PIN_RE = re.compile(
    r'"(?P<pkg>[a-z-]+) @ git\+https://github\.com/(?P<owner>[\w-]+)/'
    r'(?P<repo>[\w-]+)@(?P<sha>[0-9a-f]{40})",\s*#\s*(?P<ver>v?[\d.]+)')


def _pins():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pins = [m.groupdict() for m in PIN_RE.finditer(text)]
    assert pins, "no git pins parsed from pyproject.toml — did the format change?"
    return pins


def test_every_pin_declares_a_version():
    for pin in _pins():
        assert pin["ver"], f"{pin['pkg']} pin has no version comment"


def test_pin_shas_are_full_length_and_lowercase():
    """A short SHA is ambiguous and an uppercase one breaks string comparison."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for sha in re.findall(r'git\+https://github\.com/[\w-]+/[\w-]+@([0-9a-fA-F]+)', text):
        assert len(sha) == 40, f"pin {sha} is not a full 40-hex commit SHA"
        assert sha == sha.lower(), f"pin {sha} is not lowercase"


@pytest.mark.parametrize("pin", _pins(), ids=lambda p: p["pkg"])
def test_pin_matches_its_tagged_release(pin):
    url = f"https://api.github.com/repos/{pin['owner']}/{pin['repo']}/tags"
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            tags = json.load(r)
    except (urllib.error.URLError, TimeoutError) as e:      # offline / rate limited
        pytest.skip(f"GitHub tags unreachable for {pin['repo']}: {e}")
    want = pin["ver"] if pin["ver"].startswith("v") else "v" + pin["ver"]
    match = [t for t in tags if t["name"] == want]
    assert match, (
        f"{pin['pkg']} pin claims {want} but that tag does not exist "
        f"(tags: {[t['name'] for t in tags][:5]})")
    assert match[0]["commit"]["sha"] == pin["sha"], (
        f"{pin['pkg']} pin is commented {want} but points at {pin['sha'][:8]}, "
        f"while {want} is {match[0]['commit']['sha'][:8]}")
