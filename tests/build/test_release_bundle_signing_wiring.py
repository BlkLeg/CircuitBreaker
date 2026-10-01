"""Where release.yml signs, verifies and attests the bundles (spec: release pipeline)."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = yaml.safe_load((ROOT / ".github" / "workflows" / "release.yml").read_text())
DRY_RUN = yaml.safe_load((ROOT / ".github" / "workflows" / "release-dry-run.yml").read_text())
JOBS: dict[str, Any] = RELEASE["jobs"]


def _steps(job: str, workflow: dict[str, Any] = RELEASE) -> list[dict[str, Any]]:
    return workflow["jobs"][job]["steps"]


def _index(job: str, predicate, workflow: dict[str, Any] = RELEASE) -> int:
    for i, step in enumerate(_steps(job, workflow)):
        if predicate(step):
            return i
    raise AssertionError(f"no matching step in {job}")


def _runs(step: dict[str, Any], needle: str) -> bool:
    return needle in step.get("run", "")


def test_only_the_stage_job_declares_the_signing_environment() -> None:
    declared = {name: job.get("environment") for name, job in JOBS.items() if job.get("environment")}
    assert declared == {"release": "release-signing", "promote": "release"}


def test_the_stage_job_can_attest() -> None:
    perms = JOBS["release"]["permissions"]
    assert perms == {
        "contents": "write", "packages": "write", "id-token": "write",
        "security-events": "write", "attestations": "write",
    }


def test_signing_happens_after_the_final_sums_and_before_the_draft() -> None:
    final = _index("release", lambda s: s.get("name") == "Write the final SHA256SUMS")
    sign = _index("release", lambda s: _runs(s, "scripts/ci/sign_release_sums.sh"))
    verify = _index("release", lambda s: _runs(s, "cb_verify_sums_signature"))
    attest = _index("release", lambda s: str(s.get("uses", "")).startswith("actions/attest-build-provenance@"))
    stage = _index("release", lambda s: _runs(s, "gh release create"))
    candidate = _index("release", lambda s: s.get("name") == "Write candidate.json")
    assert final < sign < verify < attest < candidate < stage


def test_the_key_reaches_only_the_signing_step_and_only_through_env() -> None:
    holders = [s for s in _steps("release") if "RELEASE_BUNDLE_SIGNING_KEY" in yaml.safe_dump(s)]
    assert len(holders) == 1
    step = holders[0]
    assert step["env"]["RELEASE_BUNDLE_SIGNING_KEY"] == "${{ secrets.RELEASE_BUNDLE_SIGNING_KEY }}"
    run = step["run"]
    assert "${{" not in run
    assert "umask 077" in run
    assert 'rm -f "${keyfile}"' in run
    assert "trap" in run
    assert "exit 1" in run  # an empty secret stops the release


def test_the_final_sums_exclude_the_signature_files() -> None:
    step = _steps("release")[_index("release", lambda s: s.get("name") == "Write the final SHA256SUMS")]
    assert "! -name 'SHA256SUMS*'" in step["run"]


def test_attestation_covers_the_bundle_tarballs() -> None:
    step = _steps("release")[_index("release", lambda s: str(s.get("uses", "")).startswith("actions/attest-build-provenance@"))]
    assert step["with"]["subject-path"] == "dist/release/circuit-breaker_*_linux_*.tar.gz"


def test_new_steps_never_soften_failure() -> None:
    for step in _steps("release"):
        text = yaml.safe_dump(step)
        if "sign_release_sums" in text or "cb_verify_sums" in text or "attest-build-provenance" in text:
            assert "continue-on-error" not in step
            assert "always()" not in str(step.get("if", ""))


def test_signing_is_refused_off_main_before_the_key_is_written() -> None:
    step = _steps("release")[_index("release", lambda s: _runs(s, "scripts/ci/sign_release_sums.sh"))]
    run = step["run"]
    guard = run.index('"${GITHUB_REF}" != "refs/heads/main"')
    write = run.index("printf '%s\\n' \"${RELEASE_BUNDLE_SIGNING_KEY}\"")
    assert guard < write


def test_promote_verify_checks_signature_hashes_and_provenance_before_approval() -> None:
    step = _steps("promote-verify")[_index("promote-verify", lambda s: _runs(s, "cb_verify_sums_signature"))]
    run = step["run"]
    assert "--pattern 'SHA256SUMS.sig'" in run
    assert "deploy/keys/release-bundle-keys.txt" in run
    assert "cb_verify_sums_entry" in run
    assert 'gh attestation verify "${tarball}" --repo "${GITHUB_REPOSITORY}"' in run
    assert "${{" not in run
    assert JOBS["promote-verify"]["permissions"]["attestations"] == "read"


def test_post_publish_verifies_the_published_signature() -> None:
    download = _steps("post-publish")[_index("post-publish", lambda s: s.get("name") == "Download the published tarball and checksums")]
    assert '--pattern "SHA256SUMS.sig"' in download["run"]
    verify = _index("post-publish", lambda s: _runs(s, "cb_verify_sums_signature"))
    hashes = _index("post-publish", lambda s: s.get("name") == "Verify the published tarball against the published checksums")
    assert verify < hashes


def test_the_dry_run_rehearses_signing_with_a_throwaway_key() -> None:
    step = _steps("staged-publication", DRY_RUN)[_index("staged-publication", lambda s: _runs(s, "sign_release_sums.sh"), DRY_RUN)]
    run = step["run"]
    assert "openssl genpkey -algorithm ed25519" in run  # generated at run time, never stored
    assert "cb_verify_sums_signature" in run
    assert "tampered" in run  # the negative case must fail
    assert "secrets." not in yaml.safe_dump(step)


# ---------------------------------------------------------------------------
# The verify steps run for real, with cb_verify_sums_signature stubbed to the
# exit code under test, so the message each code produces is pinned.
# ---------------------------------------------------------------------------

_SOURCE_LIB = re.compile(r'^\s*source "?(\$\{GITHUB_WORKSPACE\}/)?deploy/lib/bundle-signature\.sh"?$', re.MULTILINE)
_NO_KEY = "deploy/keys/release-bundle-keys.txt holds no usable key, or"
_VERIFY_STEPS = [
    ("release", "Verify SHA256SUMS.sig against the trusted keys", "the new SHA256SUMS.sig does not verify"),
    ("promote-verify", "Verify the draft's signature, bundle hashes and provenance",
     "the draft's SHA256SUMS.sig does not verify"),
    ("post-publish", "Verify the published signature", "the published SHA256SUMS.sig does not verify"),
]


def _run_with_stubbed_verify(run: str, rc: int, cwd: Path) -> subprocess.CompletedProcess[str]:
    stub = (f'cb_verify_sums_signature() {{ [ {rc} -eq 0 ] && echo 0123456789abcdef; return {rc}; }}\n'
            "cb_verify_sums_entry() { return 0; }\n"
            "gh() { :; }\n")
    assert _SOURCE_LIB.search(run), "the step no longer sources deploy/lib/bundle-signature.sh"
    script = stub + _SOURCE_LIB.sub("", run).replace("/tmp/signed", str(cwd / "signed"))
    env = {**os.environ, "GITHUB_WORKSPACE": str(cwd), "VERSION": "0.4.7", "GITHUB_REPOSITORY": "o/r"}
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, cwd=cwd, env=env, check=False)


@pytest.mark.parametrize(("job", "name", "mismatch"), _VERIFY_STEPS, ids=[j for j, _, _ in _VERIFY_STEPS])
def test_verify_steps_name_a_missing_key_apart_from_a_mismatch(job: str, name: str, mismatch: str,
                                                               tmp_path: Path) -> None:
    run = _steps(job)[_index(job, lambda s: s.get("name") == name)]["run"]
    no_key = _run_with_stubbed_verify(run, 2, tmp_path)
    assert no_key.returncode == 1
    assert f"::error::{_NO_KEY}" in no_key.stdout
    assert mismatch not in no_key.stdout
    bad = _run_with_stubbed_verify(run, 1, tmp_path)
    assert bad.returncode == 1
    assert f"::error::{mismatch}" in bad.stdout
    assert _NO_KEY not in bad.stdout


def test_the_dry_run_rehearsal_reports_a_failed_verification(tmp_path: Path) -> None:
    run = _steps("staged-publication", DRY_RUN)[
        _index("staged-publication", lambda s: _runs(s, "sign_release_sums.sh"), DRY_RUN)]["run"]
    (tmp_path / "scripts").symlink_to(ROOT / "scripts")
    (tmp_path / "dist" / "release").mkdir(parents=True)
    (tmp_path / "dist" / "release" / "SHA256SUMS").write_text("0" * 64 + "  ./x\n")
    for rc in (1, 2):
        r = _run_with_stubbed_verify(run, rc, tmp_path)
        assert r.returncode == 1
        assert "::error::the rehearsal SHA256SUMS.sig does not verify" in r.stdout


def test_gpg_signing_is_strict_and_still_skips_without_a_key(tmp_path: Path) -> None:
    step = _steps("release")[_index("release", lambda s: s.get("name") == "GPG sign artifacts")]
    assert step["run"].startswith("set -euo pipefail\n")
    env = {**os.environ, "GPG_PRIVATE_KEY": "", "GPG_PASSPHRASE": ""}
    r = subprocess.run(["bash", "-c", step["run"]], capture_output=True, text=True, cwd=tmp_path, env=env,
                       check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "skipping GPG signing" in r.stdout
