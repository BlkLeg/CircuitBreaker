import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import EmptyState from '../common/EmptyState';
import { describeAgentEvent } from '../../lib/agentErrors';
import { formatTimestamp } from '../../lib/time';
import AgentOpsStrip from './AgentOpsStrip';
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
export default function AgentEventsPanel({ events, compact = false }) {
  const describedEvents = events.map((event) => ({ event, described: describeAgentEvent(event) }));
  const connected = describedEvents.filter(
    ({ described }) => described.label === 'Connected'
  ).length;
  const disconnected = describedEvents.filter(
    ({ described }) => described.label === 'Disconnected'
  ).length;
  const lifecycle = events.length - connected - disconnected;

  return (
    <div className="agent-events-workbench" data-compact={String(compact)}>
      {compact ? null : (
        <AgentOpsStrip
          label="Loaded event summary"
          items={[
            {
              label: 'Loaded events',
              value: `${events.length} events`,
              detail: 'current page',
              tone: events.length ? 'info' : 'muted',
            },
            {
              label: 'Connected',
              value: `${connected} connected`,
              detail: 'observed labels',
              tone: connected ? 'ok' : 'muted',
            },
            {
              label: 'Disconnected',
              value: `${disconnected} disconnected`,
              detail: 'observed labels',
              tone: disconnected ? 'danger' : 'muted',
            },
            {
              label: 'Lifecycle',
              value: `${lifecycle} lifecycle`,
              detail: 'other allow-listed events',
              tone: lifecycle ? 'info' : 'muted',
            },
          ]}
        />
      )}
      <Panel
        title={compact ? 'Events' : 'Chronological audit stream'}
        summary={String(events.length)}
      >
        {events.length === 0 ? (
          <EmptyState icon="≡" message="No events recorded yet" />
        ) : (
          <>
            {compact ? null : (
              <div className="agent-events__head" aria-hidden="true">
                <span>Sequence</span>
                <span>Observed</span>
                <span>Event</span>
                <span>Operator-safe detail</span>
                <span>Class</span>
              </div>
            )}
            <ul className="agent-events">
              {describedEvents.map(({ event, described }, index) => (
                <li data-event={described.label.toLowerCase().replaceAll(' ', '-')} key={event.id}>
                  {compact ? null : (
                    <span
                      className="agent-events__sequence"
                      aria-label={`Sequence ${events.length - index}`}
                    >
                      #{String(events.length - index).padStart(3, '0')}
                    </span>
                  )}
                  <time>{formatTimestamp(event.created_at)}</time>
                  <strong>{described.label}</strong>
                  <span className="agent-events__detail">{described.detail || '—'}</span>
                  {compact ? null : (
                    <span className="agent-events__kind">
                      {described.label === 'Connected'
                        ? 'Online'
                        : described.label === 'Disconnected'
                          ? 'Offline'
                          : 'Lifecycle'}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
        {compact || events.length === 0 ? null : (
          <p className="agent-events__privacy">
            Event detail is allow-listed and redacted before display. No raw wire payload is
            rendered.
          </p>
        )}
      </Panel>
    </div>
  );
}

AgentEventsPanel.propTypes = { events: PropTypes.array.isRequired, compact: PropTypes.bool };
