"""M7: `write_log`'s never-raises contract has to survive its own failures.

The docstring promises "log failures must not abort the parent transaction".
The broad handler at the bottom of `write_log` catches and logs, which looks
like it delivers that — but when the failure happened on the *caller's* session,
the session was left in pending-rollback state. The original error was swallowed
and the caller's own `commit()` then raised `PendingRollbackError`: write_log
raising into its caller through a laundered exception, one frame later and with
the cause discarded.
"""

from __future__ import annotations

from app.db.models import Hardware
from app.services import log_service


def test_a_failed_audit_write_leaves_the_callers_transaction_usable(
    db_session, monkeypatch
) -> None:
    """The caller must still be able to commit its own work."""
    device = Hardware(name="cb-test-m7", status="active")
    db_session.add(device)
    db_session.flush()

    def _boom(session, lock_wait_seconds=None):
        session.execute(__import__("sqlalchemy").text("SELECT 1"))
        raise RuntimeError("audit chain unavailable")

    monkeypatch.setattr(log_service, "_do_write", _boom, raising=False)

    # Must not raise.
    log_service.write_log(
        db=db_session,
        action="cb_test_m7",
        entity_type="hardware",
        entity_id=device.id,
    )

    # And the caller's own work must still be committable — this is the
    # assertion that fails on a poisoned session.
    db_session.flush()
    assert db_session.query(Hardware).filter_by(name="cb-test-m7").count() == 1


def test_write_log_still_does_not_raise_on_an_import_failure(db_session, monkeypatch) -> None:
    """The AuditChainLockTimeout import used to sit *above* the try, so an
    ImportError from it escaped the handler whose entire job is to stop this
    function raising."""
    import builtins

    real_import = builtins.__import__

    def _fail_audit_chain(name, *args, **kwargs):
        if name == "app.core.audit_chain":
            raise ImportError("simulated")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail_audit_chain)

    log_service.write_log(db=db_session, action="cb_test_m7_import")
