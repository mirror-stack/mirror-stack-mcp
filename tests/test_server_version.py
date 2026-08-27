# -*- coding: utf-8 -*-
"""The server must tell a client ITS version, not the SDK's.

FastMCP (1.27.2) has no `version` parameter, so `Server.version` stays None and the
lowlevel server answers `initialize` with `pkg_version("mcp")`. The result is that every
FastMCP server reports the SDK's version as its own — ours said `1.27.2`. An outside bug
report on 2026-08-24 read a different number on Windows and took it for a platform
difference; it was the SDK version there too.

This file tests the value a client actually receives (`create_initialization_options()`),
not the attribute we set — setting an attribute proves nothing about what is served.

The three candidate values on the author's machine are all different, which is what makes
these assertions able to fail:

    source __version__                              0.2.11   ← correct
    importlib.metadata.version("mirror-stack-mcp")  0.1.0    ← stale editable dist-info
    importlib.metadata.version("mcp")               1.27.2   ← the SDK, the old bug
"""
import importlib.metadata as md
import re

import pytest

from mirror_stack_mcp import __version__
from mirror_stack_mcp.server import mcp


def _served():
    return mcp._mcp_server.create_initialization_options()


def test_serves_our_own_version():
    assert _served().server_version == __version__


def test_serves_our_own_name():
    assert _served().server_name == "mirror-stack"


def test_not_the_sdk_version():
    """The original bug, stated as its own assertion so a regression names itself."""
    try:
        sdk = md.version("mcp")
    except md.PackageNotFoundError:
        pytest.skip("mcp SDK metadata unavailable — this check needs it to mean anything")
    if sdk == __version__:
        pytest.skip(f"SDK and package versions coincide at {sdk} — cannot discriminate")
    assert _served().server_version != sdk


def test_not_the_installed_dist_info():
    """🔴 The tempting fix that only looks like one.

    `importlib.metadata.version()` reads the dist-info recorded at install time. An
    editable install here has 0.1.0 frozen while the source says 0.2.11 — using it swaps
    one wrong number for another. Skipped rather than passed where they agree: a check
    that cannot tell the two apart is not evidence.
    """
    try:
        dist = md.version("mirror-stack-mcp")
    except md.PackageNotFoundError:
        pytest.skip("package not installed — nothing to confuse the source with")
    if dist == __version__:
        pytest.skip(f"dist-info agrees with source at {dist} — cannot discriminate here")
    assert _served().server_version != dist


def test_version_matches_pyproject():
    """`__version__` is what is served, so it is what must track the release.

    Parsed by regex rather than `tomllib`: this project supports 3.10, where the stdlib
    has no TOML reader, and the sibling `test_pins_are_releases.py` reads the same file
    the same way. A skip here would silently stop guarding the release version on exactly
    the interpreter the tests run under.
    """
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'(?m)^version\s*=\s*["\']([^"\']+)["\']', text)
    assert m, "no `version =` line parsed from pyproject.toml — did the format change?"
    assert m.group(1) == __version__


def test_version_looks_like_a_version():
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-].+)?", __version__), __version__


def test_the_bug_is_reproducible_on_a_bare_server():
    """⊕ Discriminating control: a FastMCP server WITHOUT the fix still shows the fault.

    If this ever stops holding, FastMCP has changed its default and the fix above may be
    redundant — but the tests would otherwise keep passing without telling anyone.
    """
    from mcp.server.fastmcp import FastMCP
    bare = FastMCP("bare-control")
    assert bare._mcp_server.version is None, (
        "FastMCP now sets a version itself — revisit whether this patch is still needed"
    )
    served = bare._mcp_server.create_initialization_options().server_version
    assert served != "bare-control"
    try:
        assert served == md.version("mcp"), "the fallback is no longer the SDK version"
    except md.PackageNotFoundError:
        pytest.skip("mcp SDK metadata unavailable")
