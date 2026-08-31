"""One pinned NATS, and a dependency the package manager can enforce.

Tier 3 found a Fedora install that could never start: nfpm.yaml lists
`nats-server` under `recommends`, Fedora has no such package, and the service
refuses to run without a broker. `recommends` is the wrong strength for a
component the application will not start without — a weak dependency lets the
package manager install something that cannot run, which is precisely what
happened.

The chosen shape, after review:

* Prefer the distro's nats-server where there is one. The distro then owns CVE
  updates, which is the policy Dockerfile.mono states explicitly ("version
  pinning on apt packages is intentionally avoided to keep CVE fixes current").
  Vendoring a pinned copy everywhere would have inverted that and made a NATS
  CVE fix wait on a Circuit Breaker release.
* Where there is none, ship it as a SEPARATE package. Separate keeps the
  vendored CVE surface out of the application package and lets an operator
  running an external or clustered broker simply not install it.

**Corrected 2026-08-30.** This file used to say "where the distro ships
nats-server (Debian/Ubuntu, Alpine), depend on it", and the deb override was a
bare `depends: nats-server` on the strength of that sentence. Debian 12 ships
one. Ubuntu 24.04 ships one. **Ubuntu 22.04 ships none** — jammy packages no
nats-server in any component — so the deb was uninstallable on a current Ubuntu
LTS, and the v0.4.0 release ran every build job and then stopped at Artifact
Smoke with `Depends: nats-server but it is not installable`.

"Debian/Ubuntu" was one word too coarse to be a packaging rule. The dependency is
now `nats-server | circuit-breaker-nats`: still hard, because the application
refuses to start without a broker, but satisfiable by the companion on any host
whose distro has none. apt prefers the leftmost installable alternative, so
hosts that do package one are unaffected. The companion is built for deb as well
as rpm now; before, the fallback named a package that was never produced for
that packager.
* Pin that vendored copy in one file, shared with deploy/setup.sh, so the
  unverified "latest" download disappears rather than gaining a fourth variant.
* Wants=, not Requires=. Since the bounded-connect fix, a missing broker
  degrades rather than hangs, and CB_NATS_URL exists so the broker can live on
  another host entirely — §7.4's multi-host agents depend on that staying
  first-class.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

REPO_ROOT = Path(__file__).resolve().parents[2]
PIN = REPO_ROOT / "packaging" / "nats-server.pin"
NFPM = REPO_ROOT / "nfpm.yaml"
NFPM_NATS = REPO_ROOT / "packaging" / "nfpm-nats.yaml"
SETUP = REPO_ROOT / "deploy" / "setup.sh"
INSTALLER = REPO_ROOT / "install.sh"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build_native_release.py"
UNIT = REPO_ROOT / "packaging" / "circuit-breaker.service"


def _pin() -> dict[str, str]:
    values = {}
    for line in PIN.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" in line:
            k, _, v = line.partition("=")
            values[k.strip()] = v.strip()
    return values


def test_the_pin_names_a_version_and_a_digest_per_arch():
    pin = _pin()
    assert re.fullmatch(r"\d+\.\d+\.\d+", pin.get("NATS_VERSION", "")), pin
    for arch in ("amd64", "arm64"):
        digest = pin.get(f"NATS_SHA256_{arch}", "")
        assert re.fullmatch(r"[0-9a-f]{64}", digest), (
            f"NATS_SHA256_{arch} must be a 64-char sha256; an unverified binary "
            f"installed as root is not a dependency, it is a supply chain"
        )


def test_setup_sh_no_longer_resolves_latest_from_the_network():
    """A release gate cannot depend on what GitHub called 'latest' that day."""
    text = SETUP.read_text(encoding="utf-8")
    assert "releases/latest" not in text, (
        "deploy/setup.sh must install the pinned version from "
        "packaging/nats-server.pin, not whatever the GitHub API returns"
    )
    assert "nats-server.pin" in text, "setup.sh must read the shared pin"


def _load_build_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("cb_build_native_release", BUILD_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolver_candidates() -> list[str]:
    """The paths cb_resolve_nats_pin() will accept, in order."""
    text = SETUP.read_text(encoding="utf-8")
    body = re.search(r"cb_resolve_nats_pin\(\)\s*\{(.*?)\n\}", text, re.DOTALL)
    assert body, "deploy/setup.sh no longer defines cb_resolve_nats_pin"
    block = re.search(r"local candidates=\(\s*(.*?)\n\s*\)", body.group(1), re.DOTALL)
    assert block, "cb_resolve_nats_pin no longer declares a candidates array"
    return re.findall(r'"([^"]+)"', block.group(1))


def test_the_bundle_ships_the_pin_that_setup_sh_refuses_to_install_without(tmp_path):
    """A release tarball that omits the pin cannot install NATS on any host.

    stage_bundle() cherry-picks individual files out of packaging/ rather than
    copying the tree, so a file the installer requires can be added to the repo,
    referenced by setup.sh, covered by a test that greps setup.sh for its name —
    and still never leave the build machine. That is what happened: v0.4.0's
    tarball had no pin anywhere in it, and every native install died at
    "Cannot find packaging/nats-server.pin" with the broker unprovisioned.
    """
    build = _load_build_script()

    fake_binary = tmp_path / "circuit-breaker"
    fake_binary.write_bytes(b"#!/bin/sh\nexit 0\n")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html>", encoding="utf-8")

    bundle_dir, manifest = build.stage_bundle(
        binary_path=fake_binary,
        version="0.0.0-test",
        target_os="linux",
        target_arch="amd64",
        frontend_dir=frontend,
        work_dir=tmp_path / "work",
    )

    staged = bundle_dir / "share" / "nats-server.pin"
    assert staged.is_file(), (
        "the bundle must ship packaging/nats-server.pin. deploy/setup.sh reads it "
        "to learn which NATS version to install and which digest to verify, and "
        "cb_fail()s the whole install when it is missing."
    )
    assert staged.read_text(encoding="utf-8") == PIN.read_text(encoding="utf-8"), (
        "the staged pin must be the repo's pin verbatim — a bundle that installs a "
        "different broker version than the deb defeats the point of sharing one file"
    )
    assert manifest["resources"].get("nats_pin") == "share/nats-server.pin", (
        "manifest.json must name the pin like every other installed resource"
    )


def test_every_installed_path_the_resolver_trusts_is_one_the_installer_creates():
    """The contract that actually broke: resolver paths and installer paths agreed
    on nothing.

    cb_resolve_nats_pin() searched /opt/circuitbreaker/packaging/ (and
    deploy/../packaging/, which is the same directory once installed), while
    stage0_install_bundle() only ever populates bin/, share/, deploy/ and
    agent-binaries/. Nothing in the product creates /opt/circuitbreaker/packaging,
    so both candidates were dead on arrival for every tarball install.
    """
    installer = INSTALLER.read_text(encoding="utf-8")
    installed_candidates = [
        c for c in _resolver_candidates() if c.startswith("/opt/circuitbreaker/")
    ]
    assert installed_candidates, (
        "cb_resolve_nats_pin must have at least one candidate under "
        "/opt/circuitbreaker — that is the only layout a released install has"
    )

    def _copied_from_bundle(candidate: str) -> bool:
        subdir = candidate.removeprefix("/opt/circuitbreaker/").split("/")[0]
        return (
            f'"${{CB_BUNDLE_DIR}}/{subdir}/." /opt/circuitbreaker/{subdir}/' in installer
        )

    reachable = [c for c in installed_candidates if _copied_from_bundle(c)]
    assert reachable, (
        f"none of {installed_candidates} live in a directory install.sh copies out "
        f"of the bundle. stage0_install_bundle populates only the subdirectories it "
        f"names explicitly, so a resolver candidate outside them can never resolve."
    )


def test_setup_sh_verifies_what_it_downloads():
    text = SETUP.read_text(encoding="utf-8")
    assert re.search(r"sha256sum\b.*(-c|--check)", text) or "NATS_SHA256_" in text, (
        "the downloaded tarball must be checked against the pinned digest"
    )


def _override_depends(platform: str) -> str:
    text = NFPM.read_text(encoding="utf-8")
    block = re.search(rf"^  {platform}:\n((?:    .*\n|\n)*)", text, re.M)
    assert block, f"no {platform} override block in nfpm.yaml"
    depends = re.search(r"depends:\n((?:      - .*\n)*)", block.group(1))
    assert depends, f"no depends list in the {platform} override"
    return depends.group(1)


def test_distro_platforms_depend_on_nats_rather_than_recommending_it():
    """The app will not start without a broker, so a weak dependency lets the
    package manager install something that cannot run."""
    for platform in ("deb", "apk"):
        assert "nats-server" in _override_depends(platform), (
            f"{platform} must depend on a broker, not recommend one: "
            f"validate_core_dependencies refuses to start without it, so a weak "
            f"dependency produces an install that cannot boot"
        )


def test_the_deb_broker_dependency_is_satisfiable_without_a_distro_package():
    """A hard dependency on a package some supported distro does not have is an
    uninstallable package, and it fails at the far end of the release pipeline.

    Ubuntu 22.04 packages no nats-server. The alternative lets the companion
    satisfy the same hard dependency there, while apt still prefers the distro's
    copy wherever one exists.
    """
    depends = _override_depends("deb")
    assert re.search(r"^      - nats-server \| circuit-breaker-nats$", depends, re.M), (
        "the deb's broker dependency must name the companion as an alternative "
        "(`nats-server | circuit-breaker-nats`). A bare `nats-server` is "
        "uninstallable on Ubuntu 22.04, which packages none; dropping to "
        "`recommends` instead would swap a loud install failure for a crash loop."
    )


def test_the_companion_broker_is_built_for_every_packager_that_names_it():
    """An alternative that resolves to a package nothing produces is not a fallback.

    The companion was built as an rpm only, while the deb is the packager that
    now names it — so the fallback existed in the dependency field and nowhere
    on disk.
    """
    build = (REPO_ROOT / "scripts" / "build_native_release.py").read_text(encoding="utf-8")
    formats = re.search(r"for nats_fmt in \(([^)]*)\)", build)
    assert formats, "build_native_release.py no longer loops over companion packagers"
    named = set(re.findall(r'"(\w+)"', formats.group(1)))
    assert {"deb", "rpm"} <= named, (
        f"the circuit-breaker-nats companion is built for {sorted(named)}. Every "
        f"packager whose depends names it must have one built, or the alternative "
        f"resolves to nothing."
    )


def test_the_smoke_gate_installs_the_candidate_set_and_proves_a_broker_resolved():
    """The gate that caught this must keep catching it.

    Installing the application deb alone on a runner whose distro has no broker
    is the exact configuration that failed, and asserting only that files landed
    would pass over an install that resolved no broker at all.
    """
    smoke = (REPO_ROOT / ".github/workflows/artifact-smoke.yml").read_text(encoding="utf-8")
    assert "circuit-breaker_*.deb" in smoke, (
        "the smoke job must name the application deb explicitly; `*.deb | head -1` "
        "picks circuit-breaker-nats once a companion ships beside it, and would "
        "assert the application's version against the broker's package"
    )
    assert "xargs -0 sudo apt-get install" in smoke, (
        "the smoke job must install the whole candidate set — that is what a user "
        "downloading the release assets gets, and on a distro without a broker it "
        "is the only thing that resolves"
    )
    assert "no nats-server on PATH after install" in smoke, (
        "the smoke job must assert a broker actually resolved; the dependency is "
        "the thing that broke, and file-presence checks do not see it"
    )


def test_rpm_does_not_recommend_a_package_fedora_does_not_have():
    text = NFPM.read_text(encoding="utf-8")
    block = re.search(r"^  rpm:\n((?:    .*\n|\n)*)", text, re.M)
    assert block, "no rpm override block"
    recommends = re.search(r"recommends:\n((?:      - .*\n)*)", block.group(1))
    if recommends:
        assert "nats-server" not in recommends.group(1), (
            "Fedora has no nats-server package, so recommending one is a "
            "dependency that silently does nothing; the circuit-breaker-nats "
            "subpackage is what provides it there"
        )


def test_a_separate_subpackage_provides_the_vendored_broker():
    assert NFPM_NATS.is_file(), (
        "the vendored broker belongs in its own package so its CVE surface stays "
        "separable and an external-broker deployment can decline it"
    )
    text = NFPM_NATS.read_text(encoding="utf-8")
    assert re.search(r"^name:\s*circuit-breaker-nats\s*$", text, re.M)


def test_the_app_unit_wants_the_broker_rather_than_requiring_it():
    """Requires= would make every install run its own broker and turn the
    clustered topology in §7.4 into a special case."""
    text = UNIT.read_text(encoding="utf-8")
    assert "Requires=circuit-breaker-nats" not in text, (
        "a missing broker degrades since the bounded-connect fix; Requires= "
        "would forbid pointing CB_NATS_URL at another host"
    )
    assert re.search(r"^Wants=.*circuit-breaker-nats", text, re.M), (
        "the unit should Wants= the bundled broker so it starts alongside it "
        "when installed, without depending on it"
    )
