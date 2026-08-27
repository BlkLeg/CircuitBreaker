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
