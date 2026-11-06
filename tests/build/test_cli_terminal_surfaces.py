"""Gallery presentation must retain native evidence and streaming semantics."""

import importlib.util
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "cb_terminal", ROOT / "deploy/cli/cb_terminal.py"
)
terminal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(terminal)


def test_doctor_counts_skipped_as_skipped_and_shows_real_remediation():
    rows = [
        {"check": "Backend readiness", "status": "pass", "evidence": "readyz answered"},
        {
            "check": "Data filesystem",
            "status": "fail",
            "evidence": "512 MiB free",
            "remediation": "df -h /data",
        },
        {
            "check": "Admin diagnostics",
            "status": "skipped",
            "evidence": "CB_ADMIN_TOKEN unset",
            "remediation": "cb doctor --json",
        },
    ]
    for width in (40, 100):
        text = terminal.doctor(rows, width=width)
        assert "1 passed" in text and "1 failed" in text and "1 skipped" in text
        assert "All checks passed" not in text
        assert "df -h /data" in text and "No repairs made · Exit 1" in text
        assert "512 MiB free" in text
        assert max(map(len, text.splitlines())) <= width


def test_logs_preserve_multiline_unstructured_partial_and_oversized_entries():
    raw = (
        "2026-10-02T12:01:00.124Z ERROR backend Timeout\n  Retry in 30s\n\n"
        + "x" * 200000
        + "\nunterminated"
    )
    output = io.StringIO()
    terminal.logs(io.StringIO(raw), output, width=100)
    text = output.getvalue()
    assert "Timeout\n  Retry in 30s\n\n" in text
    assert "x" * 200000 + "\nunterminated" in text
    assert text.index("Timeout") < text.index("Retry") < text.index("unterminated")
    assert "\033" not in text
    output = io.StringIO()
    terminal.logs(io.StringIO(raw), output, width=40)
    assert output.getvalue() == raw


def test_status_separates_shared_services_without_claiming_readiness():
    text = terminal.status(
        [
            ["circuitbreaker-backend", "active", "2026-10-02 12:00:00 UTC"],
            ["nginx", "active", "2026-10-01 10:00:00 UTC"],
        ],
        width=40,
    )
    assert "1 / 1 app units active" in text
    assert "SHARED SERVICES" in text and "nginx" in text
    assert "readiness checks" in text
    assert max(map(len, text.splitlines())) <= 40


def test_native_journal_multiline_message_and_actual_severity_are_preserved():
    import json

    record = {
        "__REALTIME_TIMESTAMP": "1790942521124000",
        "PRIORITY": "3",
        "_SYSTEMD_UNIT": "circuitbreaker-backend.service",
        "MESSAGE": "Timeout\n  Retry in 30s",
    }
    text = terminal.log_record(json.dumps(record) + "\n")
    assert "ERROR" in text and "Timeout" in text and "Retry in 30s" in text
    assert "circuitbreaker-backend.service" in text
    assert text.splitlines()[1].endswith("  Retry in 30s")


def test_terminal_helper_is_installed_in_each_distribution_channel():
    for path in ("nfpm.yaml", "Dockerfile.mono", "install.sh", "deploy/setup.sh"):
        assert "cb_terminal.py" in (ROOT / path).read_text()
