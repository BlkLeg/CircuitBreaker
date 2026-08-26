import React, { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { listProbeEligibleAgents } from '../../api/agents';

/**
 * Prose for `probe_eligibility`'s machine-readable denial vocabulary. The
 * backend returns the same string on the check-now 409 and in
 * `monitor_items.probe_execution_reason`, so the UI switches on it rather than
 * parsing sentences. A Map, not an object literal, so a reason that arrives
 * from the wire can never index into Object.prototype.
 */
const REASON_TEXT = new Map([
  ['agent_missing', 'the agent no longer exists'],
  ['agent_inactive', 'the agent is not active'],
  ['capability_disabled', 'remote probing is not enabled for this agent'],
  ['agent_offline', 'the agent is offline'],
  ['no_link_owner', 'the agent has no live control link'],
  ['readiness_unknown', 'the agent has not reported probe readiness yet'],
  ['readiness_unavailable', 'the agent reports this probe type as unavailable'],
  ['tenant_mismatch', 'the agent is not registered to this deployment'],
  ['unresolved_host', 'the target host does not resolve'],
  ['out_of_scope', 'the target is outside the agent network scope'],
  ['previous_run_in_flight', 'a previous run is still in flight'],
]);

export function reasonText(reason) {
  if (!reason) return null;
  return REASON_TEXT.get(reason) || reason.replace(/_/g, ' ');
}

export function agentDisplayName(agent) {
  return agent?.name || `Agent ${agent?.agent_id}`;
}

/** "branch-office — online · ready · in scope" — §7's online/readiness/scope indicators. */
export function agentOptionLabel(agent) {
  const indicators = [
    agent.online ? 'online' : 'offline',
    agent.readiness ? agent.readiness : 'readiness unknown',
    agent.in_scope ? 'in scope' : 'out of scope',
  ];
  return `${agentDisplayName(agent)} — ${indicators.join(' · ')}`;
}

/**
 * Everything §7 wants warned about for the *currently selected* vantage.
 * Exported so the rules are unit-testable without a network round trip.
 */
export function warningsFor(agent, host) {
  if (!agent) return [];
  const name = agentDisplayName(agent);
  const warnings = [];
  if (!agent.online) {
    warnings.push(`${name} is offline — assigned checks will not run until it reconnects.`);
  }
  if (!agent.granted) {
    warnings.push(`${name} does not have remote probing enabled.`);
  }
  if (!agent.in_scope) {
    warnings.push(
      `${name}'s network vantage has changed — ${host || 'this target'} is no longer inside its ` +
        `derived scope (${agent.scope_version || 'unknown version'}). Reassign the monitor or ` +
        `update the agent's scope.`
    );
  }
  if (warnings.length === 0 && !agent.eligible) {
    warnings.push(`${name} cannot run this check: ${reasonText(agent.reason)}.`);
  }
  return warnings;
}

/**
 * Identity-level refusals: the named agent is not a vantage this deployment can
 * offer at all, as opposed to one that is momentarily unusable.
 *
 * The distinction is what makes AGT-13's "reject stale or unauthorized
 * identifiers after server validation" safe to act on automatically. A
 * `probe_agent_id` arriving in a deep link is unvalidated input — the link may
 * have been bookmarked before the agent was deleted, or point at an agent in a
 * deployment the viewer cannot see — and honouring it silently would seed a
 * create form with a vantage the save is going to refuse. An agent that is
 * merely offline or out of scope is a different matter entirely: it exists, the
 * operator may well have meant it, and the warnings below say what is wrong.
 */
const UNUSABLE_PRESELECTION_REASONS = new Set([
  'agent_missing',
  'agent_inactive',
  'tenant_mismatch',
]);

/**
 * RunFromSelect — §7's "Run from" vantage picker.
 *
 * Deliberately **not** `disabled={!!initial}` the way the check-type select is:
 * §7/§8 make reassignment (and return-to-server) an explicit user action, which
 * has to be reachable from the edit form.
 *
 * The list shows eligible agents plus whichever agent is currently assigned,
 * even when it has become ineligible — dropping the current selection out of
 * the list would silently reassign the monitor to the server on the next save.
 */
export default function RunFromSelect({
  value = null,
  onChange,
  monitorId = null,
  assignedAgentName = null,
  host = '',
  checkType = 'icmp',
  targetType = null,
  targetId = null,
  preselectedAgentId = null,
}) {
  const [agents, setAgents] = useState([]);
  const [loadError, setLoadError] = useState(null);
  // Set only when a deep-link preselection was dropped, so the note below can
  // say the vantage went away rather than leaving the form silently on
  // "Circuit Breaker server" with no explanation for the change.
  const [rejectedPreselection, setRejectedPreselection] = useState(null);

  useEffect(() => {
    // Scope compatibility is a property of the (agent, destination) pair, so
    // there is nothing to ask until we have a destination.
    const query = monitorId
      ? { monitor_id: monitorId }
      : host
        ? {
            host,
            check_type: checkType,
            ...(targetType ? { target_type: targetType } : {}),
            ...(targetId != null ? { target_id: targetId } : {}),
          }
        : null;
    if (!query) {
      setAgents([]);
      setLoadError(null);
      return undefined;
    }
    let cancelled = false;
    listProbeEligibleAgents(query)
      .then(({ data }) => {
        if (cancelled) return;
        const rows = Array.isArray(data) ? data : [];
        setAgents(rows);
        setLoadError(null);
        // AGT-13, slice step 2. The endpoint returns every *active* agent, so
        // an id that is absent from the answer names one that does not exist,
        // is not active, or is not visible to this caller — the server's own
        // verdict, not a guess made here.
        //
        // Only a deep-link preselection on a CREATE is dropped. On an edit
        // (monitorId set) the currently-assigned agent deliberately stays in
        // the list even when it has become ineligible: clearing it there would
        // silently reassign the monitor to the server on the next save.
        if (preselectedAgentId != null && monitorId == null) {
          const match = rows.find((agent) => agent.agent_id === preselectedAgentId);
          if (!match || UNUSABLE_PRESELECTION_REASONS.has(match.reason)) {
            setRejectedPreselection(
              `Agent ${preselectedAgentId} is no longer available as a vantage, so this monitor will run from the Circuit Breaker server. Pick another agent if you need one.`
            );
            onChange(null);
          } else {
            setRejectedPreselection(null);
          }
        }
      })
      .catch(() => {
        if (cancelled) return;
        setAgents([]);
        setLoadError('Could not load agents — the monitor will run from the server.');
      });
    return () => {
      cancelled = true;
    };
    // `onChange` is deliberately not a dependency: MonitorForm passes an inline
    // arrow, so including it would re-run this validation — and its request —
    // on every keystroke in the form.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monitorId, host, checkType, targetType, targetId, preselectedAgentId]);

  const options = useMemo(() => {
    const rows = agents.filter((a) => a.eligible || a.agent_id === value);
    if (value != null && !rows.some((a) => a.agent_id === value)) {
      rows.push({
        agent_id: value,
        name: assignedAgentName,
        online: false,
        granted: false,
        readiness: null,
        in_scope: false,
        eligible: false,
        reason: 'agent_missing',
      });
    }
    return rows;
  }, [agents, value, assignedAgentName]);

  const selected = options.find((a) => a.agent_id === value) || null;
  const warnings = warningsFor(selected, host);
  // AGT-13: "the discovering agent visibly preselected". The <select> shows it,
  // but a default that was chosen for the operator has to announce itself —
  // otherwise the one fact that makes this form different from an ordinary
  // create is carried entirely by a value that looks like it was always there.
  // `role="status"` so it reaches a screen reader when the form opens.
  const preselectionNote =
    preselectedAgentId != null && selected?.agent_id === preselectedAgentId
      ? `Vantage preselected: ${agentDisplayName(selected)}, the agent that found this device. You can change it.`
      : null;

  return (
    <div className="form-group">
      <label htmlFor="mf-probe-agent">Run from</label>
      <select
        id="mf-probe-agent"
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      >
        <option value="">Circuit Breaker server</option>
        {options.map((agent) => (
          <option key={agent.agent_id} value={String(agent.agent_id)}>
            {agentOptionLabel(agent)}
          </option>
        ))}
      </select>
      {preselectionNote && (
        <p className="mon-run-from-note text-muted" role="status">
          {preselectionNote}
        </p>
      )}
      {rejectedPreselection && (
        <p className="mon-run-from-warning" role="status">
          {rejectedPreselection}
        </p>
      )}
      {loadError && (
        <p className="mon-run-from-note text-muted" role="status">
          {loadError}
        </p>
      )}
      {warnings.map((text) => (
        <p key={text} className="mon-run-from-warning" role="status">
          {text}
        </p>
      ))}
    </div>
  );
}

RunFromSelect.propTypes = {
  value: PropTypes.number,
  onChange: PropTypes.func.isRequired,
  monitorId: PropTypes.number,
  assignedAgentName: PropTypes.string,
  host: PropTypes.string,
  checkType: PropTypes.string,
  targetType: PropTypes.string,
  targetId: PropTypes.number,
  // The vantage this form was OPENED with, when it came from a deep link
  // ("Create monitor from this agent"). Distinct from `value`, which is
  // whatever is currently chosen: the two are equal until the operator changes
  // the selection, and only their equality justifies the preselection note.
  preselectedAgentId: PropTypes.number,
};
