import React from 'react';
import PropTypes from 'prop-types';
import { Check } from 'lucide-react';

const STEPS = [
  { key: 'validate', label: 'Validate' },
  { key: 'resolve', label: 'Resolve' },
  { key: 'review', label: 'Review' },
  { key: 'result', label: 'Apply' },
];

const ORDER = STEPS.map((step) => step.key);

/**
 * The four-step indicator. "Apply" is the terminal step: it is active while
 * the operation runs and done once the result is in.
 */
export default function ImportSteps({ current, hasDocument, applying }) {
  return (
    <ol className="inv-steps" aria-label="Import progress">
      {STEPS.map((step, index) => {
        const position = ORDER.indexOf(current);
        const done =
          (step.key === 'validate' && hasDocument) ||
          (step.key !== 'validate' && position > index) ||
          (step.key === 'result' && current === 'result');
        const active =
          step.key === current || (step.key === 'result' && applying && current === 'review');
        return (
          <li
            key={step.key}
            className="inv-step"
            data-state={done ? 'done' : active ? 'active' : 'todo'}
            aria-current={active ? 'step' : undefined}
          >
            <span className="inv-step__badge" aria-hidden="true">
              {done ? <Check size={12} /> : index + 1}
            </span>
            <span className="inv-step__label">{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}

ImportSteps.propTypes = {
  current: PropTypes.oneOf(ORDER).isRequired,
  hasDocument: PropTypes.bool,
  applying: PropTypes.bool,
};
