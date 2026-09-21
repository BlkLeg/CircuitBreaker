"""The boot gate may configure the packaged install, but not replace it.

`.github/workflows/artifact-smoke.yml` has to point the candidate at the
runner's ephemeral Postgres, Redis, NATS and setup token. It used to do that
with a plain `tee` at /etc/circuit-breaker/circuit-breaker.env, which truncates
the file `packaging/postinstall.sh` generated seconds earlier and drops every
line it writes. The run then failed like this:

    OSError: [Errno 30] Read-only file system: '/data'

with the unit crash-looping until /livez ran out its budget. CB_DATA_DIR was
gone, so the service fell back to `Path.cwd()/"data"`; the unit sets no
WorkingDirectory, so systemd runs it from `/`; ProtectSystem=strict makes `/`
read-only. Nothing was wrong with the package.

That is the failure mode the gate is least able to afford. A boot check that
rewrites the configuration under test is not testing the package, and when it
fails it points the reader at packaging — the one place with no defect in it.
`test_package_env_contract.py` proves postinstall writes these lines; this file
proves the gate still has them at the moment it starts the service.

The key list is derived from postinstall rather than restated, so a path added
there has to be added to the workflow's assertion too.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
POSTINSTALL = REPO_ROOT / "packaging" / "postinstall.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "artifact-smoke.yml"

ENV_PATH = "/etc/circuit-breaker/circuit-breaker.env"

# The waiver is not a path, so the path regex below cannot find it, but losing
# it fails the boot exactly as hard: validate_core_dependencies() refuses to
# start when CB_EGRESS_PROXY_URL is empty and this is unset.
_NON_PATH_KEYS = ("CB_ALLOW_DIRECT_EGRESS",)


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _pinned_keys() -> set[str]:
    """Every key postinstall pins to an absolute path, plus the egress waiver.

    The same shape `test_package_env_contract.py` uses, so the two files agree
    on what "the package decided this" means.
    """
    text = POSTINSTALL.read_text(encoding="utf-8")
    keys = {
        m.group(1)
        for m in re.finditer(r"^((?:CB_)?[A-Z_]*(?:DIR|INI))=(/\S+)$", text, re.M)
    }
    assert keys, "postinstall.sh pins no absolute paths; the derivation above is stale"
    return keys | set(_NON_PATH_KEYS)


def test_the_gate_never_truncates_the_packaged_env() -> None:
    """A truncating write at the env file is the defect itself."""
    offenders = [
        line.strip()
        for line in _workflow_text().splitlines()
        if ENV_PATH in line or '"$ENV_FILE"' in line
        if re.search(r"(?:^|\s)(?:sudo\s+)?tee\s+(?!-a\b)", line)
        or re.search(r"(?<!>)>(?!>)\s*(?:\"?\$ENV_FILE\"?|" + re.escape(ENV_PATH) + r")", line)
    ]
    assert not offenders, (
        "artifact-smoke.yml writes the packaged env with a truncating "
        "redirect, which discards everything packaging/postinstall.sh "
        "generated and boots the service without CB_DATA_DIR:\n  "
        + "\n  ".join(offenders)
        + "\nOverlay the ephemeral values onto the file instead "
        "(`tee -a` after deleting only the keys being overridden)."
    )


def test_the_gate_asserts_every_packaged_key_survived() -> None:
    """Overlaying correctly today is not the same as still doing it tomorrow."""
    text = _workflow_text()
    missing = sorted(key for key in _pinned_keys() if key not in text)
    assert not missing, (
        "packaging/postinstall.sh pins these into the generated env, but "
        "artifact-smoke.yml never checks they survived the step that points "
        "the service at the runner's dependencies: "
        + ", ".join(missing)
        + ". Add them to that step's assertion loop, or a future edit there "
        "will drop them and the boot will fail as a packaging defect."
    )


def test_the_gate_requires_the_package_to_have_generated_the_env() -> None:
    """Overlaying onto a file that is not there would silently write only the
    ephemeral half — the same crash, with no packaged lines to lose."""
    text = _workflow_text()
    assert re.search(r"the package did not generate", text), (
        "artifact-smoke.yml overlays the ephemeral values onto "
        f"{ENV_PATH} but never asserts the package created it. If postinstall "
        "stops generating the env, the overlay would produce a file holding "
        "only the runner's credentials and the service would crash-loop on "
        "/data with nothing to point at the real cause."
    )
