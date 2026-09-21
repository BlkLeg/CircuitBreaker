"""Every platform install.sh claims is either executed or explained.

``install.sh`` has two ``case "$ID"`` statements that decide whether a host is
supported, and both refuse with the same sentence: "Supported: Ubuntu, Debian,
Fedora, RHEL, Rocky, AlmaLinux, Arch". That sentence is a published promise,
and it was checked by nothing. Before the installer journey existed, the
``dnf`` and ``pacman`` branches of ``deploy/setup.sh`` had never been executed
by anything — not CI, not a human, not this suite — and the two defects that
found their way out to users on Rocky Linux 10 (a hardcoded ``redis-cli`` on a
Valkey host, and a dependency check that could never pass there) both lived in
exactly that unexecuted region.

``specs/1.0.0/release-control/install-support-matrix.yaml`` is the single
declaration. This file binds it to the three things that must agree with it:

  * the OS ids install.sh actually accepts — in **both** case statements, since
    they are separate lists that have no mechanism keeping them equal;
  * the distro matrix in ``.github/workflows/installer-journey.yml``;
  * the matrix's own account of anything it does not execute.

The rule the last one encodes: a claimed family is either run in CI or carries
a ``covered_by`` and a ``reason``. There is no third state. A row that is
neither is a platform the project promises and does not verify, which is the
condition this whole file exists to make impossible to reach quietly.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALL_SH = REPO_ROOT / "install.sh"
JOURNEY_WORKFLOW = REPO_ROOT / ".github/workflows/installer-journey.yml"
MATRIX = REPO_ROOT / "specs/1.0.0/release-control/install-support-matrix.yaml"

# `ubuntu|debian) PKG_MGR="apt-get" ;;` and the `echo "apt-get"` spelling of
# the same branch. Both statements list ids the same way, so one pattern reads
# both.
_SUPPORTED_BRANCH = re.compile(
    r"^\s*([a-z0-9|]+)\)\s*(?:PKG_MGR=|echo\s+)?[\"']?(apt-get|dnf|pacman)[\"']?\s*;;",
    re.MULTILINE,
)


def _matrix() -> dict:
    return yaml.safe_load(MATRIX.read_text(encoding="utf-8"))


def _declared_families() -> dict[str, dict]:
    return {row["id"]: row for row in _matrix()["families"]}


def _install_sh_case_statements() -> list[dict[str, str]]:
    """Every `case` that maps an OS id to a package manager, as id -> manager.

    Returned as a list because there is more than one and they are allowed to
    be found independently; the test below is what requires them to agree.
    """
    text = INSTALL_SH.read_text(encoding="utf-8")
    statements: list[dict[str, str]] = []
    # Each `case ... esac` that mentions a package manager.
    for block in re.findall(r"case\s+\"?\$\{?(?:ID|OS_ID)\}?\"?\s+in(.*?)esac", text, re.DOTALL):
        mapping: dict[str, str] = {}
        for ids, manager in _SUPPORTED_BRANCH.findall(block):
            for os_id in ids.split("|"):
                mapping[os_id] = manager
        if mapping:
            statements.append(mapping)
    return statements


def test_install_sh_has_more_than_one_supported_os_list() -> None:
    """The premise of the next test: there really are two lists to reconcile."""
    statements = _install_sh_case_statements()
    assert len(statements) >= 2, (
        "expected install.sh to contain at least two OS-id case statements "
        f"(cb_detect_pkg_mgr and the preflight); found {len(statements)}. "
        "If they were consolidated into one, that is an improvement — update "
        "this test to match rather than deleting the reconciliation below."
    )


def test_every_supported_os_list_in_install_sh_agrees() -> None:
    """Both case statements accept the same ids and pick the same manager.

    They are separate literals with nothing keeping them in step. A family
    added to one and not the other is a host that passes the preflight and
    then fails deep inside a dependency install, naming a package manager
    that was never selected for it.
    """
    statements = _install_sh_case_statements()
    first, *rest = statements
    for index, other in enumerate(rest, start=2):
        assert other == first, (
            "install.sh's OS-id case statements disagree.\n"
            f"  statement 1: {sorted(first.items())}\n"
            f"  statement {index}: {sorted(other.items())}"
        )


def test_matrix_declares_exactly_the_families_install_sh_accepts() -> None:
    """The declaration and the code cannot drift apart."""
    accepted = set(_install_sh_case_statements()[0])
    declared = set(_declared_families())

    undeclared = accepted - declared
    assert not undeclared, (
        f"install.sh accepts {sorted(undeclared)} but {MATRIX.name} does not "
        "declare them. Every family the installer accepts needs a row saying "
        "where that claim is executed."
    )

    unaccepted = declared - accepted
    assert not unaccepted, (
        f"{MATRIX.name} declares {sorted(unaccepted)}, which install.sh does "
        "not accept. Remove the row, or add the family to install.sh."
    )


def test_declared_package_managers_match_install_sh() -> None:
    """A row's `package_manager` is what install.sh would actually select."""
    accepted = _install_sh_case_statements()[0]
    mismatches = [
        f"{row_id}: matrix says {row['package_manager']!r}, install.sh selects "
        f"{accepted[row_id]!r}"
        for row_id, row in _declared_families().items()
        if row["package_manager"] != accepted[row_id]
    ]
    assert not mismatches, "install-support-matrix.yaml misstates a package manager:\n  " + "\n  ".join(
        mismatches
    )


def _journey_distros() -> list[str]:
    document = yaml.safe_load(JOURNEY_WORKFLOW.read_text(encoding="utf-8"))
    return list(document["jobs"]["journey"]["strategy"]["matrix"]["distro"])


def test_every_executed_family_is_in_the_journey_matrix() -> None:
    """A row naming a journey is a row whose journey actually runs."""
    distros = set(_journey_distros())
    expected = {
        row["journey"] for row in _declared_families().values() if row.get("journey")
    }

    missing = expected - distros
    assert not missing, (
        f"{MATRIX.name} says these families are executed, but "
        f"installer-journey.yml does not run them: {sorted(missing)}"
    )

    extra = distros - expected
    assert not extra, (
        f"installer-journey.yml runs {sorted(extra)}, which no row in "
        f"{MATRIX.name} claims. Add the row, or drop the matrix entry."
    )


def test_every_family_is_executed_or_explained() -> None:
    """No third state: a claim is run, or it carries covered_by + reason."""
    offences: list[str] = []
    declared = _declared_families()

    for row_id, row in declared.items():
        if row.get("journey"):
            continue
        covered_by = row.get("covered_by") or []
        reason = (row.get("reason") or "").strip()
        if not covered_by:
            offences.append(
                f"{row_id}: no journey and no covered_by — install.sh claims this "
                "platform and nothing verifies it"
            )
            continue
        if len(reason) < 40:
            offences.append(
                f"{row_id}: covered_by is set but the reason is missing or too "
                "short to be one. Say why the family cannot be executed directly."
            )
        unknown = [name for name in covered_by if name not in declared]
        if unknown:
            offences.append(f"{row_id}: covered_by names undeclared families {unknown}")
        unexecuted = [
            name for name in covered_by if name in declared and not declared[name].get("journey")
        ]
        if unexecuted:
            offences.append(
                f"{row_id}: covered_by names {unexecuted}, which are themselves "
                "not executed — a claim cannot be covered by another unverified claim"
            )

    assert not offences, "unverified platform claims:\n  " + "\n  ".join(offences)


def test_the_journey_container_step_knows_every_matrix_distro() -> None:
    """Each matrix entry resolves to an image in the container step.

    The matrix and the `case "${DISTRO}"` that turns a matrix entry into an
    image are separate lists in the same file. A distro added to one and not
    the other fails at run time with "unknown distro", which is a 6-minute
    round trip to discover.
    """
    text = JOURNEY_WORKFLOW.read_text(encoding="utf-8")
    missing = [
        distro
        for distro in _journey_distros()
        if not re.search(rf"^\s*(?:[a-z0-9]+\|)*{re.escape(distro)}(?:\|[a-z0-9]+)*\)\s*IMAGE=", text, re.MULTILINE)
    ]
    assert not missing, (
        "installer-journey.yml's matrix lists distros its container step cannot "
        f"resolve to an image: {missing}"
    )


def test_matrix_images_match_the_journey_workflow() -> None:
    """The image a row declares is the image the workflow actually starts."""
    text = JOURNEY_WORKFLOW.read_text(encoding="utf-8")
    mismatches: list[str] = []
    for row_id, row in _declared_families().items():
        journey = row.get("journey")
        if not journey:
            continue
        match = re.search(
            rf"^\s*(?:[a-z0-9]+\|)*{re.escape(journey)}(?:\|[a-z0-9]+)*\)\s*IMAGE=(\S+)\s*;;",
            text,
            re.MULTILINE,
        )
        assert match is not None, f"no IMAGE= branch for {journey}"
        if match.group(1) != row["image"]:
            mismatches.append(
                f"{row_id}: matrix declares {row['image']}, workflow starts {match.group(1)}"
            )
    assert not mismatches, (
        "install-support-matrix.yaml and installer-journey.yml name different "
        "images:\n  " + "\n  ".join(mismatches)
    )


def test_every_claimed_architecture_is_declared_and_verified_somewhere() -> None:
    """arm64 is claimed by install.sh's arch check; say where it is executed."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    accepted = set(re.findall(r"^\s*(x86_64|aarch64)\)\s*ARCH=", text, re.MULTILINE))
    declared = {row["uname"]: row for row in _matrix()["architectures"]}

    assert accepted == set(declared), (
        f"install.sh accepts architectures {sorted(accepted)}; the matrix "
        f"declares {sorted(declared)}"
    )

    for uname, row in declared.items():
        verified = row.get("installer_journey") or row.get("artifact_smoke")
        assert verified, (
            f"{uname}: install.sh accepts this architecture and no gate runs it"
        )
        if not row.get("installer_journey"):
            assert len((row.get("reason") or "").strip()) >= 40, (
                f"{uname}: the installer journey does not cover it, so the matrix "
                "has to say what does and why"
            )
