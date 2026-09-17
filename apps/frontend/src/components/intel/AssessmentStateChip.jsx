import React from 'react';
import PropTypes from 'prop-types';
import { describeAssessment } from '../../lib/vulnerabilityAssessment';
import '../../styles/intel.css';

/**
 * One row's assessment state, in the same words the entity panel uses.
 *
 * The vocabulary comes from describeAssessment rather than a local map, so a
 * state cannot be named one thing here and another thing on the detail page.
 *
 * `hasFindings` is not decoration. describeAssessment titles a completed
 * assessment with no findings "No matches in this assessment", and it decides
 * that from the findings array it is handed — so a chip that always passed an
 * empty array would label an entity with twelve findings as having none.
 */
function AssessmentStateChip({ state, reason, hasFindings = false }) {
  const described = describeAssessment({
    state,
    reason_code: reason,
    findings: hasFindings ? [{}] : [],
    limitations: [],
  });
  return (
    <span className={`intel-chip intel-chip--${described.tone}`} title={described.detail}>
      {described.title}
    </span>
  );
}

AssessmentStateChip.propTypes = {
  state: PropTypes.string.isRequired,
  reason: PropTypes.string,
  hasFindings: PropTypes.bool,
};

export default AssessmentStateChip;
