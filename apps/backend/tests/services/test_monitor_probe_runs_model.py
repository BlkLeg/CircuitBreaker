"""The two lifecycle rules §1 pushes down into the database itself (Task 6).

`monitor_probe_runs` is the durable lease behind a remote check, so "one
in-flight run per monitor" and "an agent with assignments cannot be deleted"
are enforced by constraints rather than by whichever caller remembers to look.
The dispatcher's pre-check (D-6) and the delete-409 wrapper (Task 14) sit on
top of these; both would be defeated by a concurrent second caller if the
database were not the backstop.
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Agent


def test_two_active_runs_for_one_monitor_violate_the_partial_unique_index(db_session, factories):
    agent = factories.agent(status="active")
    monitor = factories.monitor_item(probe_agent_id=agent.id)
    factories.monitor_probe_run(monitor, agent, status="queued")

    factories.monitor_probe_run(monitor, agent, status="dispatched")
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_completed_run_does_not_block_a_new_active_run(db_session, factories):
    """The index is partial for exactly this reason: history accumulates, and
    a monitor checked every 60s would otherwise wedge after its first run."""
    agent = factories.agent(status="active")
    monitor = factories.monitor_item(probe_agent_id=agent.id)
    factories.monitor_probe_run(monitor, agent, status="completed", outcome="completed")
    factories.monitor_probe_run(monitor, agent, status="expired")
    factories.monitor_probe_run(monitor, agent, status="cancelled")

    fresh = factories.monitor_probe_run(monitor, agent, status="queued")
    db_session.flush()

    assert fresh.id is not None


def test_deleting_an_agent_with_assignments_raises_integrity_error(db_session, factories):
    """`probe_agent_id` is RESTRICT, unlike every other agents FK. Without it a
    delete would silently unassign monitors — the one vantage change §1 says
    must never happen implicitly."""
    agent = factories.agent(status="active")
    factories.monitor_item(probe_agent_id=agent.id)
    db_session.flush()

    db_session.delete(db_session.get(Agent, agent.id))
    with pytest.raises(IntegrityError):
        db_session.flush()
