"""NPM-02/05/06/07/10/11: the npm CLI package's shape, before it is ever published.

Pins what `npm pack` would put in front of users: only the allowlisted runtime
files, under a size budget, with no install-time scripts, and with copies of the
identity schema, licence and native command list that match their sources. The
dedicated manifest is publishable through the protected release flow;
root/frontend privacy and public documentation gating stay enforced by
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
    r"|compat/[a-z-]+\.json"
    r"|trust/release-bundle-keys\.txt"
    r"|npm-shrinkwrap\.json)$"
)
REQUIRED_PACKED = {
    "package.json", "README.md", "LICENSE", "bin/circuitbreaker.js",
    "src/main.js", "schemas/install-identity.schema.json",
    "schemas/native-commands.json", "compat/management.json",
    "schemas/lifecycle-plan.schema.json", "schemas/lifecycle-event.schema.json",
    "schemas/lifecycle-result.schema.json", "schemas/operation-journal.schema.json",
    "trust/release-bundle-keys.txt", "npm-shrinkwrap.json",
}
# The code's budget. npm-shrinkwrap.json is dependency metadata, not code, and
# has its own budget: it grows with sigstore's tree, which deserves a look anyway.
# 64 KiB held the foundation; 80 KiB took the verification pipeline and
# install --plan (sub-plan 02); 84 KiB takes that plan's final review fixes (the
# release-answer checks and the one-pass hash and archive scan), again with
# little headroom, so each later sub-plan that adds code has to argue for its
# own growth here. 131 KiB takes sub-plan 03 Task 1's frozen lifecycle contract
# (measured 132,698 B): the four lifecycle schemas (25.5 KB, each self-contained
# so they version independently) and lifecycle-contract.js (23.7 KB), the
# coordinator's validator for them, which 03 Task 4 and 05-08 consume. 138 KiB
# takes that task's review fixes (measured 139,977 B): the bounded text and
# installed-version definitions, the interruption, step and recovery-attempt
# rules, the shared redaction, and install --plan redacting what it echoes.
# 163 KiB takes sub-plan 03 Task 4 (measured 165,750 B): events.js (10.0 KB:
# the event and result writers, the bounded descriptor decoder and the native
# step runner), lifecycle-state.js (10.6 KB: history over the trusted index),
# and main, install --plan, help and README growing the two machine streams.
# 168 KiB takes that task's review fixes (measured 170,126 B): the native step
# runner's bounded drain after exit, and exitResult building a stopped step's
# result from its journal instead of its status.
# Plans 04–09 add the native lifecycle adapters and static renderer.
UNPACKED_SIZE_BUDGET = 192 * 1024
SHRINKWRAP_SIZE_BUDGET = 40 * 1024
SHRINKWRAP = PKG / "npm-shrinkwrap.json"
ENTRY_BUDGET = 45
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
    # sigstore 5's own engines range; runtime.js's NODE_ENGINES is pinned to it too.
    assert MANIFEST["engines"] == {"node": "^22.22.2 || ^24.15.0 || >=26.0.0"}
    assert MANIFEST["license"] == "MIT"
    assert MANIFEST["repository"]["directory"] == "packages/cli"
    assert MANIFEST["files"] == ["bin/", "src/", "schemas/", "compat/", "trust/", "npm-shrinkwrap.json"]
    assert MANIFEST["private"] is False
    assert MANIFEST["publishConfig"] == {"access": "public", "registry": "https://registry.npmjs.org/"}



def test_only_sigstore_and_no_install_time_scripts() -> None:
    assert MANIFEST.get("dependencies") == {"sigstore": "5.0.0"}, "sigstore, exact, is the only runtime dependency"
    for field in ("devDependencies", "optionalDependencies", "peerDependencies", "bundleDependencies"):
        assert not MANIFEST.get(field), f"{field} must stay empty (NPM-05)"
    hooks = set(MANIFEST.get("scripts", {})) & NPM_LIFECYCLE_SCRIPTS
    assert not hooks, f"npm would run {sorted(hooks)} unasked (NPM-10)"
    # npm never publishes package-lock.json; npm-shrinkwrap.json is the one lock
    # that ships and that `npm install -g` honours, so users get the tree tested here.
    assert SHRINKWRAP.is_file(), "the dependency tree must be locked in npm-shrinkwrap.json"
    assert not (PKG / "package-lock.json").exists(), "one lockfile: npm ignores package-lock.json beside a shrinkwrap"


def test_shrinkwrap_pins_a_registry_tree_without_install_scripts() -> None:
    """NPM-10 for the tree users get: every locked package comes from the npm
    registry with an integrity hash, and none has an install-time script (npm
    records that as hasInstallScript when it writes the lock)."""
    lock = json.loads(SHRINKWRAP.read_text(encoding="utf-8"))
    assert lock["lockfileVersion"] == 3
    packages = {path: entry for path, entry in lock["packages"].items() if path}
    assert packages["node_modules/sigstore"]["version"] == "5.0.0"
    assert lock["packages"][""]["dependencies"] == MANIFEST["dependencies"]
    scripted = sorted(path for path, entry in packages.items() if entry.get("hasInstallScript"))
    assert not scripted, f"locked packages with install-time scripts (NPM-10): {scripted}"
    unpinned = sorted(
        path for path, entry in packages.items()
        if not str(entry.get("resolved", "")).startswith("https://registry.npmjs.org/")
        or not str(entry.get("integrity", "")).startswith("sha512-")
    )
    assert not unpinned, f"locked packages without a registry tarball and sha512 integrity: {unpinned}"


def _installed_package_manifests(modules: Path) -> list[Path]:
    """The package.json at each package root under a node_modules tree, nested trees included.

    A package root is `node_modules/<name>/` or `node_modules/@scope/<name>/`. Other
    package.json files inside a package (fixtures, `dist/esm/package.json` type
    markers) are not packages npm installs, so they are left out.
    """
    trees = [modules, *(p for p in modules.rglob("node_modules") if p.is_dir())]
    manifests: list[Path] = []
    for tree in trees:
        manifests.extend(tree.glob("[!@.]*/package.json"))
        manifests.extend(tree.glob("@*/*/package.json"))
    return sorted(manifests)


def test_no_installed_dependency_runs_install_scripts() -> None:
    modules = PKG / "node_modules"
    assert modules.is_dir(), "run `npm ci --ignore-scripts` in packages/cli first"
    manifests = _installed_package_manifests(modules)
    assert any(m.parent.name == "sigstore" for m in manifests), "sigstore is not installed"
    offenders = []
    for manifest in manifests:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        hooks = set(data.get("scripts", {})) & {"preinstall", "install", "postinstall"}
        if hooks:
            offenders.append(f"{manifest.parent.relative_to(modules)}: {sorted(hooks)}")
    assert not offenders, f"dependencies with install-time scripts (NPM-10): {offenders}"


def test_package_root_discovery_covers_scoped_and_nested_trees(tmp_path: Path) -> None:
    for rel in (
        "plain/package.json",
        "@scope/pkg/package.json",
        "plain/node_modules/nested/package.json",
        "@scope/pkg/node_modules/@inner/deep/package.json",
        "plain/dist/esm/package.json",
        ".package-lock.json",
    ):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("{}", encoding="utf-8")
    found = {m.relative_to(tmp_path).as_posix() for m in _installed_package_manifests(tmp_path)}
    assert found == {
        "plain/package.json",
        "@scope/pkg/package.json",
        "plain/node_modules/nested/package.json",
        "@scope/pkg/node_modules/@inner/deep/package.json",
    }


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
    sizes = {entry["path"]: entry["size"] for entry in info["files"]}
    assert sizes["npm-shrinkwrap.json"] <= SHRINKWRAP_SIZE_BUDGET, sizes["npm-shrinkwrap.json"]
    code_size = info["unpackedSize"] - sizes["npm-shrinkwrap.json"]
    assert code_size <= UNPACKED_SIZE_BUDGET, code_size
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
