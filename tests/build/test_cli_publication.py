"""The dedicated npm package shares the protected, signed candidate release flow."""
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/release.yml").read_text())


def test_pack_once_before_candidate_sums_and_reuse_exact_bytes():
    steps = WORKFLOW["jobs"]["release"]["steps"]
    pack = [i for i, step in enumerate(steps) if "npm pack --ignore-scripts" in step.get("run", "")]
    assert len(pack) == 1
    signing = next(i for i, step in enumerate(steps) if "sign_release_sums.sh" in step.get("run", ""))
    assert pack[0] < signing
    assert any(step.get("with", {}).get("node-version") == "22.22.2" for step in steps)
    promote = WORKFLOW["jobs"]["promote"]
    assert promote["environment"] == "release"
    assert promote["permissions"]["id-token"] == "write"
    script = next(step["run"] for step in promote["steps"] if "cli_publish.mjs" in step.get("run", ""))
    assert "npm pack" not in script
    assert script.index("cb_verify_sums_signature") < script.index("cb_verify_sums_entry") < script.index("gh attestation verify") < script.index("cli_packed_smoke.sh") < script.index("cli_publish.mjs")
    assert "npm-publication.json" in script
    assert "npm@11.5.1" in script


def test_cli_tarball_is_signed_and_attested_with_server_assets():
    steps = WORKFLOW["jobs"]["release"]["steps"]
    gpg = next(step["run"] for step in steps if step.get("name") == "GPG sign artifacts")
    assert "*.tgz" in gpg
    attestation = next(step for step in steps if step.get("uses", "").startswith("actions/attest-build-provenance@"))
    assert "dist/release/blkleg-circuitbreaker-*.tgz" in attestation["with"]["subject-path"]
