from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts/validate_security_suppressions.py"
_SPEC = importlib.util.spec_from_file_location("validate_security_suppressions", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def test_security_suppression_metadata_is_current() -> None:
    _MODULE.validate(_MODULE.DEFAULT_MANIFEST, date(2026, 8, 11))
