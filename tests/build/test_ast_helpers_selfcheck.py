"""The ratchet helpers must count what they claim to count.

A ratchet is only as trustworthy as its counter, and Phase 2 spent a whole
verification pass on instruments that reported clean numbers they had no way
to measure. These fixtures are deliberately adversarial: a docstring-only
handler is not any less silent, a deferred import is not a top-level one, and
an attribute access that is never called is not a session operation.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

# `tests/` has no `__init__.py` while `tests/build/` does, so the repo root must
# be on `sys.path` before `tests.build.*` resolves. This mirrors
# `tests/build/test_cb_update_recreate.py:45-48`, which imports a sibling the
# same way.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.build._ast_helpers import (
    core_to_services_imports,
    session_op_calls,
    silent_handlers,
)


def _write(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


def test_session_op_calls_counts_calls_not_attribute_reads(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        def handler(db):
            db.query(Thing).all()
            db.commit()
            fn = db.execute        # a reference, not a call
            other.query(Thing)     # not a session receiver
            return fn
        """,
    )
    assert [attr for _, attr in session_op_calls(path)] == ["query", "commit"]


def test_core_to_services_splits_top_level_from_deferred(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
        from app.services.log_service import write_log

        def later():
            from app.services.user_service import record_session
            return record_session, write_log
        """,
    )
    top, deferred = core_to_services_imports(path)
    assert [module for _, module in top] == ["app.services.log_service"]
    assert [module for _, module in deferred] == ["app.services.user_service"]


def test_silent_handlers_ignores_a_handler_that_does_something(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        '''
        def f():
            try:
                risky()
            except ValueError:
                pass
            try:
                risky()
            except KeyError:
                """Explained, but still silent."""
                pass
            try:
                risky()
            except TypeError:
                log.warning("handled")
        ''',
    )
    # Two silent handlers: the bare one and the docstring-then-pass one. The
    # logging handler is not silent and must not be counted.
    assert len(silent_handlers(path)) == 2
