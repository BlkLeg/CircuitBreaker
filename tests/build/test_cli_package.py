"""NPM-02/05/06/07/10/11: the npm CLI package's shape, before it is ever published.

Pins what `npm pack` would put in front of users: only the allowlisted runtime
files, under a size budget, with no install-time scripts, and with copies of the
identity schema, licence and native command list that match their sources. The
manifest stays private here; sub-plan 09 lifts that together with
test_npm_is_not_a_distribution_channel.py.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "packages" / "cli"
MANIFEST = json.loads((PKG / "package.json").read_text(encoding="utf-8"))

# npm runs these without being asked, on install, pack or publish. NPM-10: none may exist.
NPM_LIFECYCLE_SCRIPTS = {
    "preinstall", "install", "postinstall",
    "preprepare", "prepare", "postprepare",
    "prepack", "postpack",
    "prepublish", "prepublishOnly", "publish", "postpublish",
    "dependencies",
}
PACKED_ALLOWLIST = re.compile(
    r"^(?:package\.json|README\.md|LICENSE"
    r"|bin/circuitbreaker\.js"
    r"|src/[a-z-]+\.js"
    r"|schemas/[a-z-]+(?:\.schema)?\.json"
    r"|compat/[a-z-]+\.json)$"
)
REQUIRED_PACKED = {
    "package.json", "README.md", "LICENSE", "bin/circuitbreaker.js",
    "src/main.js", "schemas/install-identity.schema.json",
    "schemas/native-commands.json", "compat/management.json",
}
UNPACKED_SIZE_BUDGET = 64 * 1024
ENTRY_BUDGET = 40
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def _dispatched_commands(script: Path) -> set[str]:
    """Same pattern as test_cb_cli_parity.py: names in cb's top-level case dispatcher."""
    return set(re.findall(r"^[ ]{2}([a-z][a-z-]*)\)", script.read_text(), flags=re.MULTILINE))


def _pack() -> dict:
    out = subprocess.run(
        ["npm", "pack", "--dry-run", "--json", "--ignore-scripts"],
        cwd=PKG, capture_output=True, text=True, check=True,
    )
    [info] = json.loads(out.stdout)
    return info


def test_manifest_identity() -> None:
    assert MANIFEST["name"] == "@blkleg/circuitbreaker"
    assert MANIFEST["bin"] == {"circuitbreaker": "bin/circuitbreaker.js"}
    assert MANIFEST["type"] == "module"
    assert MANIFEST["os"] == ["linux"]
    assert MANIFEST["engines"] == {"node": ">=22"}
    assert MANIFEST["license"] == "MIT"
    assert MANIFEST["repository"]["directory"] == "packages/cli"
    assert MANIFEST["files"] == ["bin/", "src/", "schemas/", "compat/"]
    assert MANIFEST["private"] is True and "publishConfig" not in MANIFEST, (
        "the CLI is published only by sub-plan 09, together with the ADR 0006 guard revision"
    )


def test_no_dependencies_and_no_install_time_scripts() -> None:
    for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies", "bundleDependencies"):
        assert not MANIFEST.get(field), f"{field} must stay empty (NPM-05)"
    hooks = set(MANIFEST.get("scripts", {})) & NPM_LIFECYCLE_SCRIPTS
    assert not hooks, f"npm would run {sorted(hooks)} unasked (NPM-10)"


def test_launcher_is_executable_with_a_node_shebang() -> None:
    launcher = PKG / "bin" / "circuitbreaker.js"
    assert launcher.read_text(encoding="utf-8").startswith("#!/usr/bin/env node\n")
    assert launcher.stat().st_mode & 0o111
    tracked = subprocess.run(
        ["git", "ls-files", "-s", "packages/cli/bin/circuitbreaker.js"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert tracked.startswith("100755"), "git must record the launcher as executable"


def test_packed_contents_are_allowlisted_and_within_budget() -> None:
    info = _pack()
    paths = {entry["path"] for entry in info["files"]}
    strays = sorted(p for p in paths if not PACKED_ALLOWLIST.match(p))
    assert not strays, f"npm pack would publish files outside the allowlist: {strays}"
    assert REQUIRED_PACKED <= paths, f"npm pack is missing {sorted(REQUIRED_PACKED - paths)}"
    assert info["unpackedSize"] <= UNPACKED_SIZE_BUDGET, info["unpackedSize"]
    assert info["entryCount"] <= ENTRY_BUDGET, info["entryCount"]


def test_npmignore_backs_up_the_allowlist() -> None:
    lines = set((PKG / ".npmignore").read_text(encoding="utf-8").split())
    assert {"test/", ".env", ".env.*", "*.pem", "*.key", "*.map"} <= lines


def test_inventory_matches_the_native_dispatcher() -> None:
    inventory = json.loads((PKG / "schemas" / "native-commands.json").read_text(encoding="utf-8"))
    names = {c["name"] for c in inventory["commands"]}
    dispatched = _dispatched_commands(ROOT / "deploy" / "cli" / "cb")
    assert names == dispatched, (
        f"packages/cli/schemas/native-commands.json and deploy/cli/cb disagree: "
        f"only in the inventory {sorted(names - dispatched)}, only in cb {sorted(dispatched - names)}"
    )


def test_identity_schema_copy_is_byte_identical() -> None:
    assert (PKG / "schemas" / "install-identity.schema.json").read_bytes() == (
        ROOT / "specs" / "install" / "identity.schema.json"
    ).read_bytes(), "re-copy specs/install/identity.schema.json into packages/cli/schemas/"


def test_licence_copy_is_byte_identical() -> None:
    assert (PKG / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()


def test_certified_servers_are_distinct_releases_not_newer_than_the_cli() -> None:
    table = json.loads((PKG / "compat" / "management.json").read_text(encoding="utf-8"))
    own = tuple(int(n) for n in SEMVER.match(MANIFEST["version"]).groups())
    parsed = []
    for version in table["certified_servers"]:
        match = SEMVER.match(version)
        assert match, f"{version!r} is not a release version"
        parsed.append(tuple(int(n) for n in match.groups()))
    assert parsed == sorted(set(parsed)), "certified_servers must be unique and ascending"
    # The CLI's own release may be listed: VERSION lags the release bump, and the list
    # must keep the prior release certified once the CLI moves on.
    assert all(v <= own for v in parsed), (
        "list only releases up to the CLI's own; newer servers are never certified by listing"
    )
