import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import Toggle from '../common/Toggle';
import { normalizeCapability } from '../../api/agents';

/** Moved here from AgentDetailPage; this is the only component that needs it. */
export const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

/** Why a toggle cannot be used, in the operator's terms. */
const BLOCKED_NOTES = {
  approval: 'locked until approved',
  revocation: 'credential revoked',
};

// eslint-disable-next-line security/detect-object-injection -- `key` is always an element of CAPABILITY_LABELS' own literal key list
const grantFor = (capabilities, key) => normalizeCapability(capabilities?.[key]);

/**
 * The three capability switches.
 *
 * When the agent's lifecycle state makes these unusable, each switch says why
 * rather than simply appearing dim. A control that silently does nothing is a
 * worse answer than one that names its precondition — and the note is folded
 * into the accessible name by Toggle, so the reason is not colour-only.
 */
export default function AgentCapabilitiesPanel({
  capabilities,
  locked = false,
  blockedReason = null,
  onToggle,
  children = null,
}) {
  const keys = Object.keys(CAPABILITY_LABELS);
  const enabled = keys.filter((key) => grantFor(capabilities, key).enabled).length;
  // eslint-disable-next-line security/detect-object-injection -- blockedReason is constrained by PropTypes to the two literal keys of this module-level map
  const note = locked ? (BLOCKED_NOTES[blockedReason] ?? null) : null;

  return (
    <Panel title="Capabilities" summary={`${enabled} of ${keys.length} on`}>
      {keys.map((key) => (
        <Toggle
          key={key}
          // eslint-disable-next-line security/detect-object-injection -- `key` is an element of this module's own literal map
          label={CAPABILITY_LABELS[key]}
          note={note}
          disabled={locked}
          checked={grantFor(capabilities, key).enabled}
          onChange={(next) => onToggle(key, next)}
        />
      ))}
      {children}
    </Panel>
  );
}

AgentCapabilitiesPanel.propTypes = {
  capabilities: PropTypes.object,
  locked: PropTypes.bool,
  blockedReason: PropTypes.oneOf(['approval', 'revocation', null]),
  onToggle: PropTypes.func.isRequired,
  children: PropTypes.node,
};
