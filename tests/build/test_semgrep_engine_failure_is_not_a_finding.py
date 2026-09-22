"""A scanner that crashed did not find anything.

Two defects, one symptom. `make verify` failed the pre-push gate with

    ❌ GATE FAILED: 1 gate failure(s).
       1 scanner(s) reported HIGH/CRIT findings — review security_scan_report.md

on a tree with no findings at all. What actually happened was in the report:

    UnixExit(2): unknown exception Multiple exceptions:
    - Unix_error: Cannot allocate memory io_uring_queue_init
      Raised by primitive operation at Uring.create in "lib/uring/uring.ml"

Semgrep's engine is OCaml on eio, whose Linux backend is io_uring, and
io_uring_queue_init locks memory. RLIMIT_MEMLOCK here is 8192 KB with the hard
limit equal to the soft one, so it cannot be raised without root. The engine
died before evaluating a rule.

  * security_scan.sh took any non-zero semgrep exit as findings. semgrep exits 1
    for findings and >=2 when it could not finish, and the script has had a
    `gate_unavailable` path for exactly this distinction since issue #106 — it
    just never covered a scanner that is installed and crashes.
  * Nothing selected eio's portable backend, so the crash recurred every push.

Both still fail the gate. A scanner that did not run attests nothing. But
"install/fix this tool" and "fix this vulnerability" are different instructions,
and printing the second when the first is true is what sends someone hunting a
vulnerability that does not exist — or reaching for --no-verify, which pushes
security-relevant changes with the gate genuinely unrun.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "security_scan.sh"

IO_URING_CRASH = (
    "UnixExit(2): unknown exception Multiple exceptions:\n"
    "- Unix_error: Cannot allocate memory io_uring_queue_init \n"
    '  Raised by primitive operation at Uring.create in file "lib/uring/uring.ml"\n'
)


def _function(name: str) -> str:
    """Lift a function out of the shipped script, so the test exercises the
    implementation rather than a copy of it."""
    text = SCRIPT.read_text(encoding="utf-8")
    body = re.search(rf"^{re.escape(name)}\(\)\s*\{{.*?^\}}", text, re.DOTALL | re.MULTILINE)
    assert body, f"{SCRIPT.name} no longer defines {name}"
    return body.group(0)


def _gate_block() -> str:
    """The semgrep classification block, from the temp file to its cleanup."""
    text = SCRIPT.read_text(encoding="utf-8")
    start = text.index('_semgrep_out="$(mktemp)"')
    end = text.index('rm -f "$_semgrep_out"') + len('rm -f "$_semgrep_out"')
    return text[start:end]


def _semgrep_stub(tmp_path: Path, first_exit: int, first_output: str, second_exit: int = 0) -> Path:
    """A fake semgrep whose behaviour changes between invocations, so the retry
    is observable."""
    scan_bin = tmp_path / "scanbin"
    scan_bin.mkdir()
    stub = scan_bin / "semgrep"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            count_file="{tmp_path}/invocations"
            echo "EIO_BACKEND=${{EIO_BACKEND:-<unset>}}" >> "$count_file"
            if [ "$(wc -l < "$count_file")" -eq 1 ]; then
              cat <<'CRASH'
            {textwrap.indent(first_output, "            ")}
            CRASH
              exit {first_exit}
            fi
            echo "Scanning 1102 files tracked by git with 310 Code rules"
            exit {second_exit}
            """
        ),
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return scan_bin


def _run(script: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(tmp_path),
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )


def _harness(scan_bin: Path, tmp_path: Path, gate: str = "true") -> str:
    return textwrap.dedent(
        f"""
        set -e
        SCAN_BIN="{scan_bin}"
        REPORT_FILE="{tmp_path}/report.md"
        : > "$REPORT_FILE"
        GATE_MODE={gate}
        GATE_FAILURES=0
        GATE_UNAVAILABLE=0
        GATE_MISSING_TOOLS=()
        gate_unavailable() {{
          GATE_FAILURES=$((GATE_FAILURES + 1))
          GATE_UNAVAILABLE=$((GATE_UNAVAILABLE + 1))
          echo "UNAVAILABLE:$1" >> "$REPORT_FILE"
        }}
        """
    )


def _report_tail(script: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], str]:
    result = _run(script, tmp_path)
    report = (tmp_path / "report.md").read_text(encoding="utf-8")
    return result, report


def test_an_io_uring_crash_is_retried_with_the_posix_backend(tmp_path):
    scan_bin = _semgrep_stub(tmp_path, first_exit=2, first_output=IO_URING_CRASH)
    script = (
        _harness(scan_bin, tmp_path)
        + _function("_semgrep_scan")
        + '\n_semgrep_scan "'
        + str(tmp_path / "out.txt")
        + '" --config=p/default . || echo "RC=$?"\n'
    )
    result = _run(script, tmp_path)
    assert result.returncode == 0, result.stderr

    invocations = (tmp_path / "invocations").read_text(encoding="utf-8").split()
    assert invocations == ["EIO_BACKEND=<unset>", "EIO_BACKEND=posix"], (
        "semgrep must be retried exactly once, with the portable eio backend "
        f"selected; got {invocations}"
    )
    out = (tmp_path / "out.txt").read_text(encoding="utf-8")
    assert "310 Code rules" in out, "the retry's output must replace the crash trace"
    assert "EIO_BACKEND=posix" in out, "the report must say the fallback was used"
    assert "RC=" not in result.stdout, "a successful retry means the scan succeeded"


def test_a_caller_supplied_backend_is_never_second_guessed(tmp_path):
    """An operator who sets EIO_BACKEND has made a decision."""
    scan_bin = _semgrep_stub(tmp_path, first_exit=2, first_output=IO_URING_CRASH)
    script = (
        _harness(scan_bin, tmp_path)
        + "export EIO_BACKEND=uring\n"
        + _function("_semgrep_scan")
        + '\n_semgrep_scan "'
        + str(tmp_path / "out.txt")
        + '" --config=p/default . || echo "RC=$?"\n'
    )
    result = _run(script, tmp_path)
    invocations = (tmp_path / "invocations").read_text(encoding="utf-8").split()
    assert invocations == ["EIO_BACKEND=uring"], f"no retry expected; got {invocations}"
    assert "RC=2" in result.stdout, "the failure must surface rather than be silently retried"


def test_an_unrecoverable_engine_error_counts_as_unavailable_not_findings(tmp_path):
    """Exit >=2 is 'could not scan'. This is the classification that failed."""
    scan_bin = _semgrep_stub(
        tmp_path, first_exit=2, first_output="Fatal error: out of memory", second_exit=2
    )
    script = _harness(scan_bin, tmp_path) + _function("_semgrep_scan") + "\n" + _gate_block() + '\necho "FAILURES=$GATE_FAILURES UNAVAILABLE=$GATE_UNAVAILABLE"\n'
    result, report = _report_tail(script, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "FAILURES=1 UNAVAILABLE=1" in result.stdout, (
        "an engine error must fail the gate as an unavailable scanner:\n" + result.stdout
    )
    assert "UNAVAILABLE:Semgrep" in report
    assert "GATE FAILURE: Semgrep ERROR findings" not in report, (
        "a crashed engine must not be reported as HIGH/CRIT findings — that is "
        "the message that blocked a push over a memlock limit"
    )


def test_real_findings_still_fail_the_gate_as_findings(tmp_path):
    """The inverse. Exit 1 means semgrep ran and found something."""
    scan_bin = _semgrep_stub(tmp_path, first_exit=1, first_output="found 3 issues", second_exit=1)
    script = _harness(scan_bin, tmp_path) + _function("_semgrep_scan") + "\n" + _gate_block() + '\necho "FAILURES=$GATE_FAILURES UNAVAILABLE=$GATE_UNAVAILABLE"\n'
    result, report = _report_tail(script, tmp_path)

    assert result.returncode == 0, result.stderr
    assert "FAILURES=1 UNAVAILABLE=0" in result.stdout, result.stdout
    assert "GATE FAILURE: Semgrep ERROR findings" in report
    assert "UNAVAILABLE:Semgrep" not in report


def test_a_clean_scan_fails_nothing(tmp_path):
    scan_bin = _semgrep_stub(tmp_path, first_exit=0, first_output="no findings")
    script = _harness(scan_bin, tmp_path) + _function("_semgrep_scan") + "\n" + _gate_block() + '\necho "FAILURES=$GATE_FAILURES UNAVAILABLE=$GATE_UNAVAILABLE"\n'
    result, report = _report_tail(script, tmp_path)

    assert "FAILURES=0 UNAVAILABLE=0" in result.stdout, result.stdout
    assert "GATE FAILURE" not in report
