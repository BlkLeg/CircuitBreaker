import React from 'react';
import PropTypes from 'prop-types';
import {
  Activity,
  Ban,
  CircleDot,
  Clock,
  CloudOff,
  Database,
  Download,
  HelpCircle,
  Hourglass,
  PowerOff,
  ShieldAlert,
  TriangleAlert,
  XCircle,
} from 'lucide-react';

/**
 * One agent state, rendered so that it is legible three ways at once
 * (AGT-14: "a distinct, unambiguous visual treatment and accessible text — not
 * just a colour").
 *
 *   - **Shape.** A different glyph per state. Two states that share a tone —
 *     `revoked`, `rejected` and `update_failed` are all critical — never share
 *     an icon, so the chips stay separable in greyscale and to an operator who
 *     cannot tell the red from the amber.
 *   - **Text.** The label is always rendered, never replaced by the icon. The
 *     icon is `aria-hidden`; it decorates a word that is already there.
 *   - **Reason and remedy.** The state's `summary` and `action` are put in the
 *     accessible name via `title` plus an `.sr-only` span, so a screen reader
 *     reaches the operator action without a hover the reader cannot perform.
 *
 * `tone` drives colour through the existing `.fleet-chip[data-tone]` ladder in
 * styles/agents.css — no new colour vocabulary, and this component picks no
 * colour itself.
 */

// Explicit map, not a dynamic `lucide[state.icon]` lookup: every glyph this
// component can render is then visible in one list and reachable by the
// bundler's tree shaking, and an icon key with no entry degrades to text
// rather than to a crash.
const ICONS = new Map([
  ['Activity', Activity],
  ['Ban', Ban],
  ['CircleDot', CircleDot],
  ['Clock', Clock],
  ['CloudOff', CloudOff],
  ['Database', Database],
  ['Download', Download],
  ['HelpCircle', HelpCircle],
  ['Hourglass', Hourglass],
  ['PowerOff', PowerOff],
  ['ShieldAlert', ShieldAlert],
  ['TriangleAlert', TriangleAlert],
  ['XCircle', XCircle],
]);

const ICON_PX = 11;

/** Extra clause naming the specifics, when the state carries any. */
export function stateDetailText(state) {
  const detail = state?.detail;
  if (!detail) return null;
  if (state.code === 'clock_skew' && Number.isFinite(detail.offsetSeconds)) {
    const seconds = Math.round(Math.abs(detail.offsetSeconds));
    const direction = detail.offsetSeconds > 0 ? 'ahead of' : 'behind';
    return `This browser is about ${seconds}s ${direction} the server.`;
  }
  if (state.code === 'spool_pressure' && Number.isFinite(detail.depth)) {
    return `${detail.depth} samples are buffered on the agent.`;
  }
  if (state.code === 'capability_degraded' && detail.collectors?.length) {
    return `Affected: ${detail.collectors.join(', ')}.`;
  }
  if ((state.code === 'update_pending' || state.code === 'update_failed') && detail.version) {
    return `Target version ${detail.version}.`;
  }
  if (state.code === 'stale_telemetry' && Number.isFinite(detail.ageSeconds)) {
    return `Newest sample is ${Math.round(detail.ageSeconds)}s old; the cadence allows ${Math.round(detail.windowSeconds)}s.`;
  }
  return null;
}

export default function AgentStateChip({ state, showAction = true }) {
  if (!state) return null;
  const Icon = ICONS.get(state.icon);
  const detailText = stateDetailText(state);
  // One string for both the tooltip and the accessible name, so a sighted
  // operator and a screen-reader user are told the same thing.
  const explanation = [state.summary, detailText, showAction ? `What to do: ${state.action}` : null]
    .filter(Boolean)
    .join(' ');
  return (
    <span className="fleet-chip" data-tone={state.tone} data-state={state.code} title={explanation}>
      {Icon ? <Icon size={ICON_PX} aria-hidden="true" /> : null}
      {state.label}
      <span className="sr-only"> — {explanation}</span>
    </span>
  );
}

AgentStateChip.propTypes = {
  state: PropTypes.shape({
    code: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    icon: PropTypes.string,
    tone: PropTypes.string,
    summary: PropTypes.string,
    action: PropTypes.string,
    detail: PropTypes.object,
  }),
  showAction: PropTypes.bool,
};
