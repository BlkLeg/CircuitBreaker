"""Issue #106's defect class, reproduced by Trivy: dev-ci run 36386697012
(2026-09-28, job "Security Gate") shows a transient Docker Hub pull failure
("Unable to find image 'aquasec/trivy:latest' locally ... connection reset by
peer") reported as "GATE FAILURE: Trivy HIGH/CRIT findings" — trivy never
ran, but the failure read exactly like a finding. The very next section
(Trivy Config) pulled the same image successfully, proving the outage was
transient, not a real trivy failure.

scripts/security_scan.sh factors the fix into two sourceable functions
(trivy_pull_with_retry, trivy_run_and_classify) plus a TRIVY_IMAGE pin,
guarded by CB_SECURITY_SCAN_SOURCE_ONLY so this suite can reach them without
running bandit/semgrep/gitleaks/eslint/hadolint/pip-audit/govulncheck first.
Each test sources the real script against a stub PATH that returns scripted
exit codes, exactly as a real trivy/docker failure would, and checks how the
gate classified it.
"""

from __future__ import annotations

import re
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "security_scan.sh"

# Real trivy/docker on this box live under ~/.local/bin; excluding it (rather
# than than just prepending a stub dir) is what makes `command -v trivy` and
# `docker_available` actually exercise the stubs below instead of the real
# tools happening to still win the PATH search.
_BASE_PATH = "/usr/bin:/bin"


def _write_stub(bin_dir: Path, name: str, script: str) -> None:
    stub = bin_dir / name
    stub.write_text(f"#!/usr/bin/env bash\n{script}\n")
    mode = stub.stat().st_mode
    stub.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _run(tmp_path: Path, path_dirs: list[Path], body: str) -> subprocess.CompletedProcess[str]:
    """Source security_scan.sh in source-only mode, then run `body`, against a
    PATH built from `path_dirs` (highest priority first) plus base coreutils.
    """
    report = tmp_path / "report.md"
    report.touch()
    driver = tmp_path / "driver.sh"
    driver.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -uo pipefail
            export CB_SECURITY_SCAN_SOURCE_ONLY=1
            export SECURITY_SCAN_HOME="{tmp_path}/home"
            export SECURITY_SCAN_CACHE="{tmp_path}/cache"
            export NPM_CONFIG_CACHE="{tmp_path}/npm-cache"
            export REPORT_FILE="{report}"
            source "{SCRIPT}"
            # security_scan.sh's own `set -e` (its line 2) is a shell option,
            # not a subshell boundary, so it survives `source` into this
            # driver. Without turning it back off, the bare
            # trivy_run_and_classify/trivy_pull_with_retry call below would
            # abort the driver the instant it returns non-zero -- exactly
            # the "findings"/"unavailable" case under test -- before the
            # echo lines that report the result ever run.
            set +e
            {body}
            """
        )
    )
    path = ":".join(str(p) for p in path_dirs) + ":" + _BASE_PATH
    proc = subprocess.run(
        ["bash", str(driver)],
        cwd=REPO_ROOT,
        env={"PATH": path},
        capture_output=True,
        text=True,
        timeout=30,
    )
    proc.report_text = report.read_text(encoding="utf-8")  # type: ignore[attr-defined]
    return proc


def test_trivy_image_is_pinned_not_bare_or_latest():
    """The evidence's failure was pulling `aquasec/trivy:latest` — an
    unpinned tag is exactly what lets an unannounced upstream release, or a
    registry hiccup resolving the ever-changing `latest` manifest, reach the
    gate unreviewed.
    """
    proc = _run(
        Path("/tmp"),
        [],
        'echo "IMAGE:$TRIVY_IMAGE"',
    )
    assert proc.returncode == 0, proc.stderr
    match = re.search(r"^IMAGE:(\S+)$", proc.stdout, re.MULTILINE)
    assert match, f"TRIVY_IMAGE was not printed: {proc.stdout!r} / {proc.stderr!r}"
    image = match.group(1)
    assert image != "aquasec/trivy", "TRIVY_IMAGE must not be the bare, tagless image"
    assert not image.endswith(":latest"), "TRIVY_IMAGE must not float on :latest"
    assert re.fullmatch(r"aquasec/trivy:\d+\.\d+\.\d+", image), (
        f"TRIVY_IMAGE should pin an exact trivy release, got {image!r}"
    )


@pytest.mark.parametrize("exit_code", [10])
def test_findings_exit_code_is_reported_as_findings_not_unavailable(tmp_path: Path, exit_code: int):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "trivy", f"exit {exit_code}")

    proc = _run(
        tmp_path,
        [bin_dir],
        textwrap.dedent(
            """\
            trivy_run_and_classify Trivy "filesystem scanning" \\
                trivy fs --exit-code "$TRIVY_EXIT_FINDINGS"
            fn_rc=$?
            echo "FN_RC:$fn_rc"
            echo "GATE_FAILURES:$GATE_FAILURES"
            echo "GATE_UNAVAILABLE:$GATE_UNAVAILABLE"
            """
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert "FN_RC:1" in proc.stdout
    assert "GATE_FAILURES:1" in proc.stdout
    assert "GATE_UNAVAILABLE:0" in proc.stdout, "a findings exit must not be counted as unavailable"
    assert "Trivy HIGH/CRIT findings" in proc.report_text
    assert "unavailable" not in proc.report_text.lower()


@pytest.mark.parametrize("exit_code", [1, 125])
def test_non_findings_exit_code_is_reported_as_unavailable_never_findings(
    tmp_path: Path, exit_code: int
):
    """1 is a generic trivy crash; 125 is docker's own "container did not
    start" exit code (a mistyped image, a daemon error). Neither means
    trivy looked at the tree and found nothing wrong — the dev-ci evidence is
    exactly this shape (docker's connection-reset pull failure), and it must
    fail closed as unavailable, not be misread as a clean or a findings run.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "trivy", f"exit {exit_code}")

    proc = _run(
        tmp_path,
        [bin_dir],
        textwrap.dedent(
            """\
            trivy_run_and_classify Trivy "filesystem scanning" \\
                trivy fs --exit-code "$TRIVY_EXIT_FINDINGS"
            fn_rc=$?
            echo "FN_RC:$fn_rc"
            echo "GATE_FAILURES:$GATE_FAILURES"
            echo "GATE_UNAVAILABLE:$GATE_UNAVAILABLE"
            """
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert "FN_RC:1" in proc.stdout
    # Both still fail the gate ...
    assert "GATE_FAILURES:1" in proc.stdout
    # ... but counted as unavailable, never as a finding.
    assert "GATE_UNAVAILABLE:1" in proc.stdout, (
        f"exit {exit_code} must be classified as unavailable, not findings/clean"
    )
    assert f"unavailable — cannot attest filesystem scanning" in proc.report_text
    assert "HIGH/CRIT findings" not in proc.report_text


def test_clean_exit_is_not_a_gate_failure(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_stub(bin_dir, "trivy", "exit 0")

    proc = _run(
        tmp_path,
        [bin_dir],
        textwrap.dedent(
            """\
            trivy_run_and_classify Trivy "filesystem scanning" \\
                trivy fs --exit-code "$TRIVY_EXIT_FINDINGS"
            fn_rc=$?
            echo "FN_RC:$fn_rc"
            echo "GATE_FAILURES:$GATE_FAILURES"
            echo "GATE_UNAVAILABLE:$GATE_UNAVAILABLE"
            """
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert "FN_RC:0" in proc.stdout
    assert "GATE_FAILURES:0" in proc.stdout
    assert "GATE_UNAVAILABLE:0" in proc.stdout


def test_pull_retry_succeeds_within_three_attempts(tmp_path: Path):
    """A `docker pull` that fails twice then succeeds (a transient Docker Hub
    hiccup, exactly like the dev-ci evidence) must not be treated as a
    permanent outage."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "pull_attempts"
    counter.write_text("0")
    _write_stub(
        bin_dir,
        "docker",
        textwrap.dedent(
            f"""\
            if [ "$1" != "pull" ]; then exit 0; fi
            n=$(cat "{counter}")
            n=$((n + 1))
            echo "$n" > "{counter}"
            if [ "$n" -lt 3 ]; then
                exit 1
            fi
            exit 0
            """
        ),
    )
    # sleep is stubbed to a no-op so the test does not actually wait out the
    # real 5s/15s backoff; the retry *count* and eventual success is what is
    # under test here, not wall-clock timing.
    _write_stub(bin_dir, "sleep", "exit 0")

    proc = _run(
        tmp_path,
        [bin_dir],
        textwrap.dedent(
            """\
            trivy_pull_with_retry "$TRIVY_IMAGE"
            echo "PULL_RC:$?"
            """
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert "PULL_RC:0" in proc.stdout
    assert counter.read_text().strip() == "3", "should have retried until the third attempt succeeded"


def test_pull_retry_exhausted_fails_closed(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    counter = tmp_path / "pull_attempts"
    counter.write_text("0")
    _write_stub(
        bin_dir,
        "docker",
        textwrap.dedent(
            f"""\
            if [ "$1" != "pull" ]; then exit 0; fi
            n=$(cat "{counter}")
            n=$((n + 1))
            echo "$n" > "{counter}"
            exit 1
            """
        ),
    )
    _write_stub(bin_dir, "sleep", "exit 0")

    proc = _run(
        tmp_path,
        [bin_dir],
        textwrap.dedent(
            """\
            trivy_pull_with_retry "$TRIVY_IMAGE"
            echo "PULL_RC:$?"
            """
        ),
    )
    assert proc.returncode == 0, proc.stderr
    assert "PULL_RC:1" in proc.stdout
    assert counter.read_text().strip() == "3", "must attempt exactly 3 pulls, no more, no fewer"


def test_docker_pull_failure_marks_both_trivy_sections_unavailable_end_to_end(tmp_path: Path):
    """The exact evidence shape: no native trivy, docker present, the image
    pull fails every time. Both the fs and config sections of the real
    script must report unavailable — neither may pass because a scanner
    that never ran is not a clean scan, and neither may read as a finding.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # No `trivy` stub at all: command -v trivy must fail so the script takes
    # the docker fallback, exactly as CI does (no native trivy is installed
    # there either).
    _write_stub(
        bin_dir,
        "docker",
        textwrap.dedent(
            """\
            case "$1" in
                ps) exit 0 ;;
                pull) exit 1 ;;
                *) exit 0 ;;
            esac
            """
        ),
    )
    _write_stub(bin_dir, "sleep", "exit 0")

    report = tmp_path / "report.md"
    report.touch()
    driver = tmp_path / "driver.sh"
    driver.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -uo pipefail
            export CB_SECURITY_SCAN_SOURCE_ONLY=1
            export SECURITY_SCAN_HOME="{tmp_path}/home"
            export SECURITY_SCAN_CACHE="{tmp_path}/cache"
            export NPM_CONFIG_CACHE="{tmp_path}/npm-cache"
            export REPORT_FILE="{report}"
            export XDG_CACHE_HOME="{tmp_path}/cache"
            source "{SCRIPT}"
            # See the `set +e` comment in the other driver template in this
            # file: security_scan.sh's own `set -e` survives the `source`.
            set +e
            GATE_MODE=true
            TRIVY_IGNORE=""
            TRIVY_SKIP_DIRS=""
            TRIVY_CACHE="{tmp_path}/trivy-cache"
            mkdir -p "$TRIVY_CACHE"
            TRIVY_CACHE_MOUNT=(-v "$TRIVY_CACHE:/root/.cache/trivy")

            # Reproduce the selection block from the fs/config sections
            # (scripts/security_scan.sh section 7/8) exactly, since sourcing
            # in isolation stops before reaching it.
            TRIVY_NATIVE=false
            TRIVY_DOCKER_READY=false
            TRIVY_RAN=false
            TRIVY_UNAVAILABLE_HINT="https://trivy.dev/latest/getting-started/installation/"
            if command -v trivy > /dev/null 2>&1; then
                TRIVY_NATIVE=true
                TRIVY_RAN=true
            elif docker_available; then
                if trivy_pull_with_retry "$TRIVY_IMAGE"; then
                    TRIVY_DOCKER_READY=true
                    TRIVY_RAN=true
                else
                    TRIVY_UNAVAILABLE_HINT="docker pull $TRIVY_IMAGE failed after 3 attempts — check network/Docker Hub access, or install trivy natively"
                fi
            fi

            for section in fs config; do
                if $TRIVY_NATIVE || $TRIVY_DOCKER_READY; then
                    echo "unexpected: $section considered trivy available" >&2
                    exit 90
                fi
                if ! $TRIVY_RAN; then
                    if [ "$section" = fs ]; then
                        gate_unavailable Trivy "filesystem scanning" "$TRIVY_UNAVAILABLE_HINT"
                    else
                        gate_unavailable "Trivy config" "config/IaC scanning" "$TRIVY_UNAVAILABLE_HINT"
                    fi
                fi
            done
            echo "GATE_FAILURES:$GATE_FAILURES"
            echo "GATE_UNAVAILABLE:$GATE_UNAVAILABLE"
            """
        )
    )
    path = str(bin_dir) + ":" + _BASE_PATH
    proc = subprocess.run(
        ["bash", str(driver)],
        cwd=REPO_ROOT,
        env={"PATH": path},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert "GATE_FAILURES:2" in proc.stdout
    assert "GATE_UNAVAILABLE:2" in proc.stdout
    text = report.read_text(encoding="utf-8")
    assert "Trivy unavailable" in text
    assert "Trivy config unavailable" in text
    assert "HIGH/CRIT" not in text
