import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import EmptyState from '../common/EmptyState';
import { describeAgentEvent } from '../../lib/agentErrors';
import { formatTimestamp } from '../../lib/time';
import '../../styles/agents.css';

/**
 * The agent's event history.
 *
 * AGT-15: every row goes through describeAgentEvent, which allow-lists the
 * keys it will show per event type and redacts what it does show. This list
 * once rendered JSON.stringify(event.detail), which put frame types, sequence
 * numbers and raw validation text straight off the wire in front of an
 * operator — and would have carried whatever a future payload added with it.
 * Nothing here may reach into `event.detail` directly.
 */
export default function AgentEventsPanel({ events }) {
  return (
    <Panel title="Events" summary={String(events.length)}>
      {events.length === 0 ? (
        <EmptyState icon="≡" message="No events recorded yet" />
      ) : (
        <ul className="agent-events">
          {events.map((event) => {
            const described = describeAgentEvent(event);
            return (
              <li key={event.id}>
                <time>{formatTimestamp(event.created_at)}</time>
                <strong>{described.label}</strong>
                {described.detail ? <span>{described.detail}</span> : null}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

AgentEventsPanel.propTypes = { events: PropTypes.array.isRequired };
