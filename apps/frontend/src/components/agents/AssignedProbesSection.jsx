import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { listProbeEligibleAgents } from '../../api/agents';
import { runCheck, updateMonitor } from '../../api/monitor';
// AGT-15: no agent surface echoes a server `detail` unredacted — lib/agentErrors.js.
import { operatorErrorMessage, redactSensitive } from '../../lib/agentErrors';
import { useToast } from '../common/Toast';

// `monitor_items.probe_execution_status` (db/models.py:272) — the *vantage's*
// condition, which is orthogonal to `last_status` (whether the target is up).
// Rendering these two in separate cells is the load-bearing rule of §7: the
// UP/DOWN pill shows target state only, and a monitor whose agent went offline
// keeps its last known target state while turning probe-unavailable here.
const EXECUTION_LABELS = {
  ready: 'Ready',
  queued: 'Queued',
  running: 'Running',
  stale: 'Stale',
  unavailable: 'Probe unavailable',
};

// The reason vocabulary lives on the backend
// (`monitoring/probe_eligibility.py`'s REASON_* constants, plus
// `dispatch_failed` / `result_timeout` from the reconcile pass) and is
// deliberately *not* copied here: a second list would be one more thing to
// drift, and every value in it is already a readable snake_case phrase.
const humanizeReason = (reason) => (reason ? String(reason).replaceAll('_', ' ') : null);

const formatTimestamp = (value) => (value ? new Date(value).toLocaleString() : 'Never');

function ExecutionCondition({ assignment }) {
  const label = EXECUTION_LABELS[assignment.probe_execution_status];
  if (!label) return <span className="agent-probes__execution">—</span>;
  const reason = humanizeReason(assignment.probe_execution_reason);
  return (
    <span className="agent-probes__execution" data-state={assignment.probe_execution_status}>
      {label}
      {reason ? ` — ${reason}` : ''}
    </span>
  );
}

ExecutionCondition.propTypes = { assignment: PropTypes.object.isRequired };

/**
 * §7's Assigned Probes section on Agent Detail.
 *
 * Extracted rather than inlined: AgentDetailPage is already far past the
 * 150-line component budget, and this is a self-contained surface with its own
 * mutations.
 *
 * `children` is the remote-probe config editor, rendered inside this section so
 * the whole vantage story — what the agent is responsible for, and the limits
 * it runs under — lives behind one `aria-label`.
 */
export default function AssignedProbesSection({ agentId, probes, granted, onChanged, children }) {
  const toast = useToast();
  const [reassignFor, setReassignFor] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [busyMonitorId, setBusyMonitorId] = useState(null);

  const assignments = probes?.assignments ?? [];

  const withBusy = async (monitorId, action) => {
    setBusyMonitorId(monitorId);
    try {
      await action();
    } finally {
      setBusyMonitorId(null);
    }
  };

  // D-14: the agent path answers 409 with the machine-readable eligibility
  // reason rather than silently accepting a check it cannot run, so the detail
  // is the message worth showing.
  const handleCheckNow = (assignment) =>
    withBusy(assignment.monitor_id, async () => {
      try {
        await runCheck(assignment.monitor_id);
        toast.success('Check queued');
        onChanged?.();
      } catch (error) {
        const detail = error?.response?.data?.detail;
        // AGT-15: `humanizeReason` maps the machine-readable eligibility
        // vocabulary; anything it does not recognise falls through as the
        // server's own words, so it is redacted before it is shown.
        toast.error(
          detail
            ? `Cannot check now: ${redactSensitive(humanizeReason(detail))}`
            : 'Could not run the check'
        );
      }
    });

  const handleOpenReassign = async (assignment) => {
    setReassignFor(assignment.monitor_id);
    setCandidates([]);
    try {
      // Judged against this monitor's own destination — scope compatibility is
      // a property of the (agent, target) pair, so there is no such thing as a
      // globally eligible agent to cache.
      const { data } = await listProbeEligibleAgents({ monitor_id: assignment.monitor_id });
      setCandidates((data ?? []).filter((row) => row.agent_id !== Number(agentId)));
    } catch {
      toast.error('Could not load eligible agents');
    }
  };

  const handleReassign = (assignment, nextAgentId) =>
    withBusy(assignment.monitor_id, async () => {
      try {
        await updateMonitor(assignment.monitor_id, { probe_agent_id: nextAgentId });
        toast.success('Monitor reassigned');
        setReassignFor(null);
        onChanged?.();
      } catch (error) {
        toast.error(operatorErrorMessage(error, { fallback: 'Could not reassign the monitor' }));
      }
    });

  // §7 acceptance 10: a monitor returns to server execution only through an
  // explicit user action — never as an automatic fallback when the agent is
  // unavailable.
  const handleReturnToServer = (assignment) =>
    withBusy(assignment.monitor_id, async () => {
      try {
        await updateMonitor(assignment.monitor_id, { probe_agent_id: null });
        toast.success('Monitor returned to server execution');
        onChanged?.();
      } catch (error) {
        toast.error(
          operatorErrorMessage(error, { fallback: 'Could not return the monitor to the server' })
        );
      }
    });

  return (
    <section aria-label="Assigned probes" className="agent-probes">
      <h2>Assigned probes</h2>
      {!granted && (
        <p className="agent-probes__disabled">
          Remote probing is disabled for this agent. Assigned monitors keep their last known target
          state and stay probe-unavailable until it is re-enabled.
        </p>
      )}
      <p className="agent-probes__concurrency">
        {probes ? (
          <>
            {probes.active_runs} of {probes.max_concurrent} concurrent checks in use ·{' '}
            {assignments.length} assigned
          </>
        ) : (
          'Loading assigned probes…'
        )}
      </p>
      {probes && assignments.length === 0 && (
        <p>
          No monitors run from this agent. Assign one with &ldquo;Run from&rdquo; on a
          monitor&apos;s form.
        </p>
      )}
      {assignments.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Monitor</th>
                <th>Type</th>
                <th>Target</th>
                <th>Interval</th>
                <th>Target state</th>
                <th>Execution</th>
                <th>Last result</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {assignments.map((assignment) => (
                <tr key={assignment.monitor_id}>
                  <td>
                    <Link to={`/monitors/${assignment.monitor_id}`}>{assignment.name}</Link>
                  </td>
                  <td>{assignment.check_type}</td>
                  <td>{assignment.host}</td>
                  <td>{assignment.interval_secs}s</td>
                  {/* Target state, straight from `last_status`. Never merged
                      with the execution condition beside it. */}
                  <td>
                    <span className="agent-probes__status" data-status={assignment.status}>
                      {assignment.status}
                    </span>
                  </td>
                  <td>
                    <ExecutionCondition assignment={assignment} />
                  </td>
                  <td>{formatTimestamp(assignment.probe_last_result_at)}</td>
                  <td className="agent-probes__actions">
                    <Link to={`/monitors/${assignment.monitor_id}`}>Open</Link>
                    <button
                      type="button"
                      disabled={busyMonitorId === assignment.monitor_id}
                      onClick={() => handleCheckNow(assignment)}
                    >
                      Check now
                    </button>
                    <button
                      type="button"
                      disabled={busyMonitorId === assignment.monitor_id}
                      onClick={() => handleOpenReassign(assignment)}
                    >
                      Reassign
                    </button>
                    <button
                      type="button"
                      disabled={busyMonitorId === assignment.monitor_id}
                      onClick={() => handleReturnToServer(assignment)}
                    >
                      Return to server
                    </button>
                    {reassignFor === assignment.monitor_id && (
                      <select
                        aria-label={`Reassign ${assignment.name}`}
                        value=""
                        onChange={(event) => handleReassign(assignment, Number(event.target.value))}
                      >
                        <option value="" disabled>
                          {candidates.length ? 'Choose an agent…' : 'No other agents'}
                        </option>
                        {candidates.map((candidate) => (
                          <option
                            key={candidate.agent_id}
                            value={candidate.agent_id}
                            disabled={!candidate.eligible}
                          >
                            {candidate.name ?? `Agent ${candidate.agent_id}`}
                            {candidate.eligible ? '' : ` — ${humanizeReason(candidate.reason)}`}
                          </option>
                        ))}
                      </select>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {children}
    </section>
  );
}

AssignedProbesSection.propTypes = {
  agentId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
  probes: PropTypes.object,
  granted: PropTypes.bool,
  onChanged: PropTypes.func,
  children: PropTypes.node,
};
