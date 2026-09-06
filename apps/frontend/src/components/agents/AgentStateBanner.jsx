import React from 'react';
import PropTypes from 'prop-types';
import Banner from '../common/Banner';
import { stateDetailText } from './AgentStateChip';

// agentState.js's tone vocabulary is `critical | warn | info`, plus the
// literal 'ok' — its own, agent-specific severities. Banner's is the smaller,
// generic `ok | warn | danger | info`. `critical` is the one name that does
// not already exist on both sides, so it is translated here, at the boundary
// between the two vocabularies, rather than by widening Banner's tone list or
// editing agentState.js's wording to match a UI primitive it should not know
// about.
const TONE_MAP = { critical: 'danger' };

/**
 * The primary agent state, as a banner.
 *
 * The page this replaces rendered every holding state as a <dl> of label,
 * summary and "What to do: …" — correct, complete, and eight paragraphs deep
 * on an agent that had done nothing yet.
 *
 * The split here is positional only. The imperative (state.action) is promoted
 * to the always-visible body; the composite the <dl> used to render is
 * reproduced byte for byte in the disclosure. No wording in lib/agentState is
 * edited by this component or by anything downstream of it.
 */
export default function AgentStateBanner({ state, actions = null }) {
  // "Online" is not news. A banner present on every healthy page is chrome,
  // and chrome is what an operator learns to stop reading.
  if (!state || state.code === 'online') return null;

  const detailText = stateDetailText(state);
  const verbatim = [state.summary, detailText, `What to do: ${state.action}`]
    .filter(Boolean)
    .join(' ');

  return (
    <Banner
      tone={TONE_MAP[state.tone] ?? state.tone}
      title={state.label}
      body={state.action}
      detail={verbatim}
      actions={actions}
    />
  );
}

AgentStateBanner.propTypes = {
  state: PropTypes.shape({
    code: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    tone: PropTypes.string,
    summary: PropTypes.string,
    action: PropTypes.string,
    detail: PropTypes.object,
  }),
  actions: PropTypes.node,
};
