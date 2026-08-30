# tests/build/test_fleet_multi_distro.py
"""One tier script, many distros — the P1 claim, checked rather than asserted.

Design §7.1: "The `runner` field carries the whole difference ... and
`tier3-artifact.sh` is unchanged by it — which is the property that makes a PVE
backend a drop-in later rather than a rewrite." §7.2 repeats it: the script is
"identical across all of them (P1)".

Phase 2 satisfied that by having exactly one row. Every install, query and
downgrade was a bare `dnf`/`rpm` call, and the script was identical across rows
the way a sentence is grammatical in a language with one sentence in it. Slice 2
added the deb family, which is the first time the claim costs anything.

The property these tests pin is not "no package manager is ever named" -- the
script has to install packages. It is that every such call sits behind the
`pkg::` layer, so adding a third format means adding a case arm rather than
hunting for the sixth place someone typed `dnf`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FLEET = REPO_ROOT / "scripts" / "ci" / "fleet"
TIER3 = REPO_ROOT / "scripts" / "ci" / "tier3-artifact.sh"
PROVISION = FLEET / "provision.sh"
DISPATCH = FLEET / "dispatch.sh"
MATRIX = FLEET / "matrix.yaml"

# Commands that only make sense for one packaging family.
FAMILY_COMMANDS = {"dnf", "yum", "rpm", "apt-get", "apt", "dpkg", "rpm-ostree"}
# The functions allowed to contain them.
PKG_LAYER = ("pkg::install_dir", "pkg::downgrade_to", "pkg::list_contents")


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """Lines with comments and blanks removed, keeping 1-based line numbers."""
    out = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.split("#", 1)[0].rstrip() if not raw.lstrip().startswith("#") else ""
        if line.strip():
            out.append((number, line))
    return out


def _pkg_layer_span(path: Path) -> tuple[int, int]:
    """The line range covering the pkg:: function DEFINITIONS.

    Definitions specifically: matching a bare `pkg::` prefix also catches the
    call sites further down the file, and the last of those has no closing brace
    after it.
    """
    text = path.read_text(encoding="utf-8").splitlines()
    starts = [
        i for i, line in enumerate(text, start=1)
        if re.match(r"^pkg::\w+\(\)\s*\{", line)
    ]
    assert starts, "tier3-artifact.sh defines no pkg:: layer"
    for i in range(starts[-1], len(text) + 1):
        if text[i - 1] == "}":
            return starts[0], i
    raise AssertionError("unterminated pkg:: function")


def test_tier_script_defines_a_package_layer():
    text = TIER3.read_text(encoding="utf-8")
    for function in PKG_LAYER:
        assert f"{function}()" in text, f"tier3-artifact.sh does not define {function}"


def _invoked_commands(line: str) -> set[str]:
    """The commands a shell line actually invokes.

    Substring matching is not good enough here and produced a false positive the
    first time: `*.rpm) PKG_FORMAT=rpm ;;` contains "rpm" three times and invokes
    nothing. So the line is split at command separators and only the first token
    of each segment counts, after leading VAR=value assignments are stripped --
    which is also what makes `DEBIAN_FRONTEND=noninteractive apt-get ...` resolve
    to `apt-get` rather than to an assignment.
    """
    commands: set[str] = set()
    for segment in re.split(r"\|\||&&|[|;()]|\$\(", line):
        tokens = segment.strip().split()
        while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=\S*", tokens[0]):
            tokens.pop(0)
        if tokens:
            commands.add(tokens[0].lstrip("!").strip())
    return commands


def test_no_package_manager_call_escapes_the_package_layer():
    """The regression this prevents: a fifth `dnf` typed inline somewhere in the
    upgrade path, which works perfectly until the deb row runs it."""
    first, last = _pkg_layer_span(TIER3)
    offenders = [
        (number, line.strip())
        for number, line in _code_lines(TIER3)
        if not (first <= number <= last)
        and _invoked_commands(line) & FAMILY_COMMANDS
    ]
    assert not offenders, (
        "package-manager calls outside the pkg:: layer:\n"
        + "\n".join(f"  tier3-artifact.sh:{n}  {line}" for n, line in offenders)
    )


def test_package_layer_handles_every_format_the_matrix_declares():
    formats = set(re.findall(r"^\s*format:\s*(\S+)", MATRIX.read_text(encoding="utf-8"), re.M))
    assert formats, "no formats found in matrix.yaml"
    first, last = _pkg_layer_span(TIER3)
    layer = "\n".join(
        line for number, line in _code_lines(TIER3) if first <= number <= last
    )
    for fmt in formats:
        assert re.search(rf"^\s*{re.escape(fmt)}\)", layer, re.M), (
            f"the pkg:: layer has no case arm for {fmt}, which matrix.yaml declares"
        )


def test_tier_script_chooses_the_format_from_the_artifact_not_the_caller():
    """A row that hands the script a .deb IS a deb row. Deriving the format from
    the artifact makes a mismatch between the row and the file a visible failure
    here, instead of a plausible-looking package-manager error in the guest."""
    text = TIER3.read_text(encoding="utf-8")
    assert re.search(r'case "\$PACKAGE" in', text), (
        "tier3-artifact.sh must derive PKG_FORMAT from the candidate it was handed"
    )
    assert "unsupported candidate format" in text, (
        "an unknown extension must fail with a named reason"
    )


def test_tier_script_refuses_an_upgrade_across_package_formats():
    text = TIER3.read_text(encoding="utf-8")
    assert "across package formats" in text, (
        "upgrading a .deb install with an .rpm is not a thing, and the failure "
        "should say so rather than surfacing as a dependency error"
    )


# ── the guest account is a row property, not a constant ────────────────────


def test_provisioning_does_not_hardcode_a_distro_account():
    """Cloud images use different default accounts -- `fedora`, `debian`,
    `ubuntu`. A hardcoded one fails every other image with
    "Permission denied (publickey)", which reads like a broken key rather than a
    wrong username.

    Checked as a bare word rather than as `account@`, which is what the first
    version of this test looked for. That shape assumed the account name only
    ever appears as an ssh destination, and it missed
    `sudo chown -R fedora /opt/cb-tier3` sitting on the line directly below a
    correctly parameterised `"$SSH_USER"@127.0.0.1` -- so the deb row died at the
    push step with `chown: invalid user: 'fedora'` on its first execution.
    """
    for script in (PROVISION, DISPATCH):
        for number, line in _code_lines(script):
            for account in ("fedora", "debian", "ubuntu"):
                assert not re.search(rf"(?<![\w-]){account}(?![\w-])", line), (
                    f"{script.name}:{number} hardcodes the {account} account; read "
                    f"ssh_user from the matrix row instead:\n  {line.strip()}"
                )
        assert "SSH_USER" in script.read_text(encoding="utf-8"), (
            f"{script.name} does not resolve a guest account"
        )


def test_provisioning_verifies_the_units_the_fixture_names():
    """Slice 1 hardcoded `postgresql && valkey`, which is Fedora's spelling.
    Debian's redis unit is redis-server, so the same literal would have failed a
    healthy Debian guest for a service that was running."""
    text = PROVISION.read_text(encoding="utf-8")
    assert "cb-fixture-services" in text, (
        "provision.sh must read the unit list from the guest fixture rather than "
        "hardcoding one distro's service names"
    )
    # Code only. The comment above the check explains why the Fedora names were
    # removed, and naming them there is the point of the comment.
    code = "\n".join(line for _, line in _code_lines(PROVISION))
    for unit in ("valkey", "redis-server"):
        assert unit not in code, (
            f"provision.sh still names the distro-specific unit {unit!r} in code"
        )


def test_provisioning_supports_both_published_digest_algorithms():
    """Fedora publishes sha256, Debian publishes sha512 and nothing else."""
    text = PROVISION.read_text(encoding="utf-8")
    assert "image_sha512" in text and "image_sha256" in text
    assert "SHA_TOOL" in text, "the checker must follow the digest the row declares"
    assert "declares both" in text, (
        "a row naming two digests must fail rather than silently preferring one"
    )
