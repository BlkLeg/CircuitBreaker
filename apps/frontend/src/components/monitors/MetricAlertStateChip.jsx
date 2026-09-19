import React from 'react';
import PropTypes from 'prop-types';
import { describeRuleState } from '../../lib/metricAlerts';
import '../../styles/monitors.css';

/**
 * One rule's assessment, in the evaluator's own vocabulary.
 *
 * The words come from describeRuleState rather than a local map, so a state
 * cannot be named one thing in the list and another in the editor.
 */
function MetricAlertStateChip({ assessment, reason }) {
  const described = describeRuleState({ assessment, reason_code: reason });
  return (
    <span className={`rule-chip rule-chip--${described.tone}`} title={described.detail}>
      {described.title}
    </span>
  );
}

MetricAlertStateChip.propTypes = {
  assessment: PropTypes.string,
  reason: PropTypes.string,
};

export default MetricAlertStateChip;
