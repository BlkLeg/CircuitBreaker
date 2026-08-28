"""Issue #106: a scanner that did not run must not read as a scanner that
found nothing.

security_scan.sh already gets this right for Gitleaks — absent binary, gate
failure, explicit message. Section 4 (ESLint) is informational by design, which
is fine; what is not fine is that a missing binary produced a raw
`sh: 1: eslint: not found` inside the report with no marker distinguishing it
from a clean run.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "security_scan.sh"


def test_eslint_section_marks_a_missing_binary_as_skipped():
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index("## 4. ESLint")
    end = text.index("## 5. Hadolint")
    section = text[start:end]
    assert "ESLint skipped" in section, (
        "the ESLint section must emit an explicit skipped marker when the "
        "binary is absent (issue #106)"
    )


def test_every_informational_section_can_say_it_did_not_run():
    """Hadolint already does this; ESLint must too. Guards the class."""
    text = SCRIPT.read_text(encoding="utf-8")
    assert "Hadolint skipped" in text
    assert "ESLint skipped" in text


def test_dockerised_trivy_reuses_its_vulnerability_database():
    """`docker run --rm` with no cache volume redownloads 110MB every run.

    Measured 2026-08-27: `make verify` took 4m55s against a 3m17s baseline and a
    4-minute hard budget, and the scan log showed
    `[vulndb] Downloading vulnerability DB...` on a machine that had just run the
    same scan. The container is discarded by --rm, so trivy's cache goes with it
    unless a host directory is mounted at its cache path.

    This is not only a budget problem. The design's goal is a gate a developer
    can trust offline; one that silently needs 110MB of network per invocation is
    not that, and the failure mode on a train is a red gate with no bad code in
    it.
    """
    text = SCRIPT.read_text(encoding="utf-8")
    # The mount lives in one array so the four invocations cannot drift apart;
    # check the array points at trivy's cache path, then that every invocation
    # uses it.
    assert 'TRIVY_CACHE_MOUNT=(-v "$TRIVY_CACHE:/root/.cache/trivy")' in text, (
        "TRIVY_CACHE_MOUNT must map a host directory onto trivy's cache path"
    )
    for line in text.splitlines():
        if "aquasec/trivy" not in line or not line.strip().startswith(("docker run", "if ! docker run")):
            continue
        assert "TRIVY_CACHE_MOUNT" in line, (
            "the dockerised trivy must mount a persistent cache, or it "
            f"redownloads its 110MB database on every run:\n    {line.strip()}"
        )
