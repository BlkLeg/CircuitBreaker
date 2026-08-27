"""Retention must not break the audit chain, and verifying it must not read the
whole logs table into memory.

Two defects live here, and they meet in the same walk:

B14 — the retention purge deleted the oldest rows, which are the *head* of the
hash chain. Every surviving row still names its deleted predecessor in
``previous_hash``, while ``verify_audit_chain`` seeds its walk from NULL (the
genesis value). So the first row after a purge always mismatched and the
verifier reported tampering on every install that lived past its retention
window — the alarm that is supposed to mean "somebody edited the audit log"
fired on the product's own scheduled housekeeping instead.

B26 — the verifier loaded whole ``Log`` ORM rows, including ``old_value``,
``new_value``, ``details`` and ``user_agent``: unbounded body text the hash
payload never covers. On a mature logs table that is a multi-gigabyte
materialisation for a read that only needs ten columns.

The tests below pin both the behaviour (a purged chain verifies, a tampered one
still does not) and the mechanism (the walk selects only hashed columns and
streams them; the repair locks only the damaged suffix). The mechanism
assertions are the ones that matter for B26 — "the chain still verifies" passes
just as happily against the version that materialises the table.
"""

import threading
import time
from contextlib import contextmanager
from datetime import timedelta

import pytest
from sqlalchemy import delete, event, select, update

from app.core import audit_chain
from app.core.audit_chain import (
    REPAIR_AUTHORIZATION,
    repair_audit_chain,
    verify_audit_chain,
)
from app.core.time import utcnow
from app.db.models import AppSettings, Log
from app.db.session import SessionLocal, engine
from app.services import log_purge
from app.services.log_purge import purge_old_audit_logs
from app.services.log_service import write_log
from app.services.settings_service import get_or_create_settings


@pytest.fixture
def clean_audit_chain(setup_db):
    """Empty `logs` and clear the chain checkpoint either side of the test.

    Depends on setup_db rather than db_session because purge_old_audit_logs
    opens its own SessionLocal and commits: the SAVEPOINT isolation db_session
    provides would hide the very cross-connection behaviour under test. The
    checkpoint has to be cleared on the way out too — it is global state, and a
    stale one left behind would make every other module's verify_audit_chain
    call report a broken chain.
    """

    def _clear():
        with SessionLocal() as session:
            session.execute(delete(Log))
            row = session.query(AppSettings).first()
            if row is not None:
                row.audit_chain_checkpoint_hash = None
            session.commit()

    _clear()
    yield
    _clear()


@pytest.fixture
def retention_days(clean_audit_chain):
    """Set audit_log_retention_days for the test and put the original back."""
    original: list[int] = []

    def _set(days: int) -> None:
        with SessionLocal() as session:
            row = get_or_create_settings(session)
            original.append(row.audit_log_retention_days)
            row.audit_log_retention_days = days
            session.commit()

    yield _set

    if original:
        with SessionLocal() as session:
            row = get_or_create_settings(session)
            row.audit_log_retention_days = original[0]
            session.commit()


def _write(actions: list[str], **kwargs) -> None:
    with SessionLocal() as session:
        for action in actions:
            write_log(session, action=action, category="audit", **kwargs)


def _log_ids() -> list[int]:
    with SessionLocal() as session:
        return list(session.execute(select(Log.id).order_by(Log.id.asc())).scalars())


def _age(ids: list[int], *, days: int) -> None:
    """Backdate rows past the retention cutoff.

    `timestamp` is deliberately the column moved: it is what the purge selects
    on and it is *not* part of the hashed payload (that carries
    `created_at_utc`), so aging a row cannot itself break the chain and the
    test stays a test of the purge rather than of the edit.
    """
    with SessionLocal() as session:
        session.execute(
            update(Log).where(Log.id.in_(ids)).values(timestamp=utcnow() - timedelta(days=days))
        )
        session.commit()


def _checkpoint() -> str | None:
    with SessionLocal() as session:
        return session.execute(select(AppSettings.audit_chain_checkpoint_hash)).scalars().first()


@contextmanager
def _captured_sql():
    """Record (statement, server_side_cursor_name) for everything the engine runs."""
    seen: list[tuple[str, str | None]] = []

    def _before(conn, cursor, statement, parameters, context, executemany):
        seen.append((statement, getattr(cursor, "name", None)))

    event.listen(engine, "before_cursor_execute", _before)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _before)


def _chain_walk_statements(seen: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    return [
        (statement, name)
        for statement, name in seen
        if "FROM logs" in statement and "ORDER BY logs.id ASC" in statement
    ]


def _indexes(seen: list[tuple[str, str | None]], *needles: str) -> list[int]:
    """Positions of every captured statement containing all of *needles*."""
    return [i for i, (statement, _name) in enumerate(seen) if all(n in statement for n in needles)]


def _brief(seen: list[tuple[str, str | None]]) -> list[str]:
    """One short line per captured statement — the full column lists are 4KB
    each and turn an assertion message into an unreadable wall."""
    return [statement.replace("\n", " ")[:72] for statement, _name in seen]


def _repair_lock_statements(seen: list[tuple[str, str | None]]) -> list[str]:
    """The repair's own FOR UPDATE reads of the damaged suffix.

    write_log's tail read is also a FOR UPDATE on logs, but it is ORDER BY id
    DESC; the repair walks forwards. Selecting on the direction rather than on
    the presence of a LIMIT keeps this filter honest now that the repair walks
    in bounded windows and therefore carries a LIMIT of its own.
    """
    return [
        statement
        for statement, _name in seen
        if "FROM logs" in statement
        and "FOR UPDATE" in statement
        and "ORDER BY logs.id ASC" in statement
    ]


# ── B14: retention purge vs. the chain ────────────────────────────────────────


def test_chain_still_verifies_after_the_retention_purge(retention_days):
    """The regression itself: purge the head of the chain, verify what is left."""
    retention_days(1)
    _write([f"b14_entry_{i}" for i in range(4)])
    ids = _log_ids()
    assert len(ids) == 4
    _age(ids[:3], days=30)

    assert purge_old_audit_logs() == 3

    with SessionLocal() as session:
        result = verify_audit_chain(session)
    assert result["valid"] is True, result


def test_purge_records_the_hash_of_the_row_it_cut(retention_days):
    """The checkpoint must be the deleted tip, i.e. exactly what the first
    surviving row names in previous_hash — not merely 'some non-NULL value'."""
    retention_days(1)
    _write([f"b14_checkpoint_{i}" for i in range(4)])
    ids = _log_ids()
    with SessionLocal() as session:
        cut_tip_hash = session.get(Log, ids[2]).log_hash
    _age(ids[:3], days=30)

    purge_old_audit_logs()

    assert _checkpoint() == cut_tip_hash
    with SessionLocal() as session:
        first_surviving = session.execute(select(Log).order_by(Log.id.asc())).scalars().first()
        assert first_surviving.previous_hash == cut_tip_hash


def test_a_purge_does_not_mask_tampering_in_a_surviving_row(retention_days):
    """The checkpoint must not become a blanket 'anything goes' seed."""
    retention_days(1)
    _write([f"b14_tamper_{i}" for i in range(5)])
    ids = _log_ids()
    _age(ids[:3], days=30)
    purge_old_audit_logs()

    surviving = _log_ids()
    with SessionLocal() as session:
        row = session.get(Log, surviving[1])
        row.action = "b14_tamper_edited_after_the_fact"
        session.commit()

    with SessionLocal() as session:
        result = verify_audit_chain(session)
    assert result["valid"] is False, result
    assert result["first_failure_id"] == surviving[1]


def test_an_unrecorded_deletion_of_the_head_still_reads_as_tampering(retention_days):
    """Two head-cuts of the same shape, opposite verdicts — and the pair is the
    point, because either half alone pins nothing.

    Cut the head *through the purge* and what is left must verify: that is B14,
    and it is the half that fails against the version which seeds the walk from
    NULL. Cut a head *behind the purge's back* and the orphaned first row must
    still read as tampering: that is the half that fails against a "fix" which
    seeds the walk from the surviving head's own previous_hash, which would make
    every deletion of the head self-justifying. The checkpoint has to buy the
    first without costing the second.
    """
    retention_days(1)

    # Arm 1 — recorded. The purge cuts the two oldest rows and records the tip
    # it cut, so the row that is now first can still name its predecessor.
    _write([f"b14_recorded_{i}" for i in range(4)])
    ids = _log_ids()
    _age(ids[:2], days=30)
    assert purge_old_audit_logs() == 2

    with SessionLocal() as session:
        recorded = verify_audit_chain(session)
    assert recorded["valid"] is True, recorded

    # Arm 2 — unrecorded. The same cut applied straight to the table, with the
    # checkpoint left describing the *earlier* purge.
    surviving = _log_ids()
    with SessionLocal() as session:
        session.execute(delete(Log).where(Log.id <= surviving[0]))
        session.commit()

    with SessionLocal() as session:
        unrecorded = verify_audit_chain(session)
    assert unrecorded["valid"] is False, unrecorded
    assert unrecorded["first_failure_id"] == surviving[1]


def test_purge_deletes_only_a_contiguous_prefix_of_the_chain(retention_days):
    """A row can carry an old `timestamp` and a high `id` — audit_spool.drain
    chains deferred entries late but keeps the time the event happened. A purge
    that selects purely on timestamp therefore punches a hole in the *middle*
    of the chain, which no checkpoint can repair. Only the prefix goes."""
    retention_days(1)
    _write([f"b14_prefix_{i}" for i in range(5)])
    ids = _log_ids()
    _age([ids[0], ids[1], ids[4]], days=30)

    assert purge_old_audit_logs() == 2

    remaining = _log_ids()
    assert ids[4] in remaining, "an old row behind a kept row must survive: deleting it forks"
    with SessionLocal() as session:
        result = verify_audit_chain(session)
    assert result["valid"] is True, result


def test_repair_after_a_purge_relinks_onto_the_checkpoint(retention_days):
    """A repair must seed from the checkpoint too. Re-anchoring the surviving
    head to NULL would rewrite every hash in the table and still not verify."""
    retention_days(1)
    _write([f"b14_repair_{i}" for i in range(5)])
    ids = _log_ids()
    _age(ids[:2], days=30)
    purge_old_audit_logs()
    checkpoint = _checkpoint()
    assert checkpoint is not None

    surviving = _log_ids()
    with SessionLocal() as session:
        session.execute(
            update(Log).where(Log.id == surviving[0]).values(previous_hash="not-the-checkpoint")
        )
        session.commit()

    with SessionLocal() as session:
        report = repair_audit_chain(
            session,
            authorization=REPAIR_AUTHORIZATION,
            actor_id=None,
            reason="test repair of a purged chain",
        )
        assert report["repaired"] is True
        assert report["after"]["valid"] is True, report
        head = session.get(Log, surviving[0])
        assert head.previous_hash == checkpoint


# ── B26: the verifier's read shape ────────────────────────────────────────────


def test_verify_reads_only_the_hashed_columns(clean_audit_chain):
    """The body columns are not covered by the hash, so loading them is pure
    cost — and on a real logs table it is the difference between a bounded read
    and pulling the whole table into the Python heap."""
    _write(
        ["b26_body"],
        old_value="o" * 4096,
        new_value="n" * 4096,
        details="d" * 4096,
        user_agent="u" * 512,
    )

    with SessionLocal() as session, _captured_sql() as seen:
        assert verify_audit_chain(session)["valid"] is True

    walk = _chain_walk_statements(seen)
    assert walk, f"no chain walk statement captured: {_brief(seen)}"
    for statement, _name in walk:
        for column in ("logs.old_value", "logs.new_value", "logs.details", "logs.user_agent"):
            assert column not in statement, f"{column} is not hashed but is still selected"
        for column in ("logs.log_hash", "logs.previous_hash", "logs.created_at_utc"):
            assert column in statement, f"{column} is hashed and must still be selected"


def test_verify_streams_the_chain_instead_of_materialising_it(clean_audit_chain):
    """A server-side cursor is what makes peak memory the yield_per window
    rather than the table. psycopg2 names a server-side cursor and leaves a
    client-side one unnamed, so the cursor name is the observable proof."""
    _write([f"b26_stream_{i}" for i in range(3)])

    with SessionLocal() as session, _captured_sql() as seen:
        assert verify_audit_chain(session)["valid"] is True

    walk = _chain_walk_statements(seen)
    assert walk, f"no chain walk statement captured: {_brief(seen)}"
    assert any(name for _statement, name in walk), (
        "the chain walk ran on a client-side cursor: the whole logs table is buffered"
    )


def test_verify_reports_the_number_of_rows_it_actually_walked(clean_audit_chain, monkeypatch):
    """The count has to come *from the walk*, one row at a time.

    Six is six either way, so `checked_count == 6` on its own pins nothing —
    it was equally true of the version that counted `len(logs)` off a fully
    materialised list. The load-bearing assertion is the second one. With the
    yield window shrunk to two rows, the session must never be holding more
    than a window of Log instances while it hashes, and in particular must not
    already be holding all six when it hashes the first: `list(session.execute(
    select(Log)).scalars())` fetches every row before a single hash is
    computed, and that read — the whole logs table resident at once — is B26.
    """
    window = 2
    monkeypatch.setattr(audit_chain, "_VERIFY_YIELD_PER", window, raising=False)
    _write([f"b26_count_{i}" for i in range(6)])

    resident: list[int] = []
    real_compute_log_hash = audit_chain.compute_log_hash

    with SessionLocal() as session:

        def _counting_compute(log, previous_hash):
            resident.append(
                sum(1 for obj in list(session.identity_map.values()) if isinstance(obj, Log))
            )
            return real_compute_log_hash(log, previous_hash)

        monkeypatch.setattr(audit_chain, "compute_log_hash", _counting_compute)
        result = verify_audit_chain(session)

    assert result["valid"] is True, result
    assert result["checked_count"] == 6
    assert "6 entries" in result["message"]

    assert len(resident) == 6, f"the walk hashed {len(resident)} rows, not 6"
    assert resident[0] <= window, (
        f"{resident[0]} of 6 rows were already resident before the first hash: "
        "the walk buffered the table instead of streaming it"
    )
    assert max(resident) < 6, (
        f"peak resident rows was {max(resident)} of 6 — the walk is not bounded by its yield window"
    )


def test_repair_locks_and_loads_only_the_damaged_suffix(clean_audit_chain):
    """verify_audit_chain has already proved every row before the first failure
    recomputes to its stored hash, so replaying and FOR UPDATE-locking that
    prefix buys nothing and blocks every concurrent append for its duration.

    The second half of this is the half B26 names and the first fix left open:
    the repair's read must also be column-restricted. When the failure is at the
    head the "damaged suffix" is the entire table, and a full-entity select
    drags old_value, new_value, details and user_agent — none of them covered by
    the hash — into the heap along with it.
    """
    _write(
        [f"b26_suffix_{i}" for i in range(6)],
        old_value="o" * 2048,
        new_value="n" * 2048,
        details="d" * 2048,
        user_agent="u" * 512,
    )
    ids = _log_ids()
    with SessionLocal() as session:
        session.execute(update(Log).where(Log.id == ids[3]).values(previous_hash="tampered"))
        session.commit()

    with SessionLocal() as session, _captured_sql() as seen:
        report = repair_audit_chain(
            session,
            authorization=REPAIR_AUTHORIZATION,
            actor_id=None,
            reason="test repair suffix scope",
        )
    assert report["repaired"] is True
    assert report["after"]["valid"] is True, report

    locking = _repair_lock_statements(seen)
    assert locking, f"no repair FOR UPDATE captured: {_brief(seen)}"
    for statement in locking:
        assert "logs.id >=" in statement, (
            "the repair locked the whole logs table, not just the damaged suffix"
        )
        for column in ("logs.old_value", "logs.new_value", "logs.details", "logs.user_agent"):
            assert column not in statement, (
                f"{column} is not covered by the hash but the repair still loads it"
            )


def test_repair_walks_the_suffix_in_bounded_windows(clean_audit_chain, monkeypatch):
    """A repair that starts at the head has the whole table as its suffix, so
    one unbounded select is the same materialisation B26 is about, minus the
    body columns. Shrink the window and the walk must issue more than one read.
    """
    monkeypatch.setattr(audit_chain, "_REPAIR_BATCH_ROWS", 2, raising=False)
    _write([f"b26_window_{i}" for i in range(6)])
    ids = _log_ids()
    with SessionLocal() as session:
        session.execute(update(Log).where(Log.id == ids[0]).values(previous_hash="tampered"))
        session.commit()

    with SessionLocal() as session, _captured_sql() as seen:
        report = repair_audit_chain(
            session,
            authorization=REPAIR_AUTHORIZATION,
            actor_id=None,
            reason="test repair window",
        )
    assert report["repaired"] is True
    assert report["after"]["valid"] is True, report

    locking = _repair_lock_statements(seen)
    assert len(locking) > 1, (
        f"the repair read its {len(ids)}-row suffix in {len(locking)} statement(s) with a "
        "window of 2: it is not walking in bounded windows"
    )
    for statement in locking:
        assert "LIMIT" in statement, "a repair window read with no LIMIT is not bounded"


# ── Lock ordering: the purge must not deadlock the settings write path ───────


def test_purge_never_takes_the_audit_chain_advisory_lock_before_its_delete(retention_days):
    """The advisory lock is the request path's *second* lock, and the purge has
    no business holding it.

    Holding it across the DELETE stalls every audit write in the process:
    request-path writers queue for it with no deadline while holding
    log_service._AUDIT_CHAIN_LOCK, so the background writers whose one-second
    deadline exists precisely to fall through to the durable spool never reach
    the database at all, never time out, and never spool. The purge does not
    need it — it never appends, it deletes only a contiguous id prefix, and it
    never deletes the chain tip, which is the only row write_log reads.
    """
    retention_days(1)
    _write([f"lockorder_{i}" for i in range(5)])
    ids = _log_ids()
    _age(ids[:4], days=30)

    with _captured_sql() as seen:
        assert purge_old_audit_logs() == 4

    deletes = _indexes(seen, "DELETE FROM logs")
    assert deletes, f"no delete captured: {_brief(seen)}"
    advisory = _indexes(seen, "pg_advisory_xact_lock")
    early_advisory = [i for i in advisory if i < deletes[-1]]
    assert not early_advisory, (
        "the purge acquired the audit-chain advisory lock and held it across its "
        f"delete: {[_brief(seen)[i] for i in early_advisory]}"
    )


def test_purge_locks_app_settings_before_it_touches_logs(retention_days):
    """Lock order, and it is not optional.

    Every settings-mutating request takes app_settings first and the audit chain
    second, without meaning to: update_settings dirties the AppSettings row and
    the log_audit that follows autoflushes that UPDATE — taking the row lock —
    on its way into lock_audit_chain. A purge that touched logs first and wrote
    the checkpoint afterwards inverted that order and deadlocked against any
    concurrent settings write.
    """
    retention_days(1)
    _write([f"lockorder2_{i}" for i in range(5)])
    ids = _log_ids()
    _age(ids[:4], days=30)

    with _captured_sql() as seen:
        assert purge_old_audit_logs() == 4

    deletes = _indexes(seen, "DELETE FROM logs")
    assert deletes, f"no delete captured: {_brief(seen)}"
    first_logs_write = deletes[0]

    settings_locks = _indexes(seen, "FROM app_settings", "FOR UPDATE")
    assert [i for i in settings_locks if i < first_logs_write], (
        f"the purge modified logs without first taking the app_settings row lock: {_brief(seen)}"
    )

    settings_updates = _indexes(seen, "UPDATE app_settings")
    assert settings_updates, "the purge never recorded the checkpoint"
    assert settings_updates[0] < first_logs_write, (
        "the checkpoint UPDATE lands after the DELETE, so the purge takes the "
        "app_settings row lock last — the reverse of the request path's order"
    )


def test_purge_deletes_in_bounded_batches(retention_days, monkeypatch):
    """Each batch holds the app_settings row lock for its own duration, so the
    batch — not the retention window — is what a concurrent settings write can
    be made to wait for. One transaction spanning a full window of rows is the
    same stall by another name.
    """
    monkeypatch.setattr(log_purge, "_PURGE_BATCH_ROWS", 2, raising=False)
    retention_days(1)
    _write([f"batched_{i}" for i in range(6)])
    ids = _log_ids()
    _age(ids[:5], days=30)

    with _captured_sql() as seen:
        assert purge_old_audit_logs() == 5

    deletes = _indexes(seen, "DELETE FROM logs")
    assert len(deletes) >= 3, (
        f"5 rows were removed in {len(deletes)} delete(s) with a batch size of 2: "
        "the purge is not batching"
    )
    with SessionLocal() as session:
        assert verify_audit_chain(session)["valid"] is True


def test_purge_never_deletes_the_chain_tip(retention_days):
    """write_log chains a new entry by reading exactly one row — the highest id,
    FOR UPDATE. Leaving that row alone is what lets the purge run without the
    advisory lock: the two never contend for a row, so an append can never link
    onto something this purge is removing. The row outlives its retention window
    by one purge cycle; that is the price of not stalling every audit write.
    """
    retention_days(1)
    _write([f"tip_{i}" for i in range(4)])
    ids = _log_ids()
    _age(ids, days=30)

    assert purge_old_audit_logs() == 3, "the purge deleted the chain tip"

    remaining = _log_ids()
    assert ids[3] in remaining, "the chain tip must survive its own retention window"
    with SessionLocal() as session:
        assert verify_audit_chain(session)["valid"] is True


def test_a_concurrent_settings_write_and_purge_do_not_deadlock(retention_days):
    """The deadlock, reproduced end to end.

    One thread does what a settings PATCH does — dirty the AppSettings row, then
    write an audit entry on the same session, which autoflushes that UPDATE and
    then asks for the audit-chain lock. The other runs the purge. With the purge
    taking the advisory lock first and the checkpoint UPDATE last, the two sit
    on each other and PostgreSQL kills one of them: if it kills the purge the
    scheduled job raises, and if it kills the writer, write_log catches bare
    Exception and the audit entry is lost without a sound.
    """
    retention_days(1)
    _write([f"deadlock_{i}" for i in range(6)])
    ids = _log_ids()
    _age(ids[:5], days=30)

    failures: list[str] = []
    settings_row_locked = threading.Event()

    def _settings_writer() -> None:
        try:
            with SessionLocal() as session:
                row = (
                    session.execute(select(AppSettings).order_by(AppSettings.id.asc()).limit(1))
                    .scalars()
                    .first()
                )
                row.updated_at = utcnow()
                session.flush()  # takes the app_settings row lock
                settings_row_locked.set()
                # Give the purge time to get as far as it is going to get before
                # this thread asks for the audit-chain lock.
                time.sleep(0.5)
                write_log(session, action="deadlock_settings_write", category="settings")
                session.commit()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"settings writer: {exc!r}")

    def _purger() -> None:
        try:
            settings_row_locked.wait(timeout=10)
            purge_old_audit_logs()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"purge: {exc!r}")

    writer = threading.Thread(target=_settings_writer)
    purger = threading.Thread(target=_purger)
    writer.start()
    purger.start()
    writer.join(timeout=60)
    purger.join(timeout=60)
    assert not writer.is_alive() and not purger.is_alive(), "a thread never finished"

    assert not failures, failures
    with SessionLocal() as session:
        actions = set(session.execute(select(Log.action)).scalars())
    assert "deadlock_settings_write" in actions, (
        "the settings write's audit entry never landed — write_log swallowed the "
        "deadlock and dropped it"
    )
    with SessionLocal() as session:
        assert verify_audit_chain(session)["valid"] is True
