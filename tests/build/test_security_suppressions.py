from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/validate_security_suppressions.py"
_SPEC = importlib.util.spec_from_file_location("validate_security_suppressions", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_security_suppression_metadata_is_current() -> None:
    """Today, not a pinned date.

    This asserted against `date(2026, 8, 11)` — the day the manifest was
    written — so it could never observe an expiry passing, which is the one
    thing it exists to catch. Every suppression expired on 2026-08-17 and this
    test stayed green while the security gate went red for three days. The
    validator uses today's date in CI, so the repo policy suite has to as well.
    """
    _MODULE.validate(_MODULE.DEFAULT_MANIFEST, datetime.now(UTC).date())
