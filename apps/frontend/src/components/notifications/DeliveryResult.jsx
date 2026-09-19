import React from 'react';
import PropTypes from 'prop-types';
import { describeDeliveryResult } from '../../lib/notificationDelivery';
import '../../styles/notifications.css';

/**
 * The one place a delivery test result is rendered (plan 05).
 *
 * Both the Notifications page and the settings manager render this rather than
 * their own copy. That is the point: the two surfaces drifted apart before,
 * and one of them ended up claiming "Test delivered" for any 2xx while the
 * backend had already learned to tell acceptance from receipt.
 *
 * `role="status"` rather than `role="alert"` — a test result is the answer to
 * something the operator just asked for, so it should be announced politely
 * rather than interrupting them.
 */
function DeliveryResult({ result, pending, destination }) {
  if (pending) {
    return (
      <div className="delivery-result delivery-result--pending" role="status">
        <span className="delivery-result__title">
          {destination ? `Testing ${destination}…` : 'Testing…'}
        </span>
      </div>
    );
  }

  if (!result) return null;

  const view = describeDeliveryResult(result);

  return (
    <div className={`delivery-result delivery-result--${view.tone}`} role="status">
      <span className="delivery-result__title">{view.title}</span>
      {/* Which destination answered. A provider name alone cannot identify one
          of several Slack destinations, and an outcome that names no
          destination is not an outcome the operator can act on. */}
      {destination && <span className="delivery-result__destination">{destination}</span>}
      <p className="delivery-result__detail">{view.detail}</p>

      {view.caveat && <p className="delivery-result__caveat">{view.caveat}</p>}
      {view.guidance && <p className="delivery-result__guidance">{view.guidance}</p>}

      {view.facts.length > 0 && (
        <dl className="delivery-result__facts">
          {view.facts.map((fact) => (
            <div className="delivery-result__fact" key={fact.label}>
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

DeliveryResult.propTypes = {
  /** The server's TestResult. Absent until a test has actually been run. */
  result: PropTypes.shape({
    state: PropTypes.string,
    reason_code: PropTypes.string,
    message: PropTypes.string,
    error: PropTypes.string,
    provider: PropTypes.string,
    attempt_count: PropTypes.number,
    http_status: PropTypes.number,
    retry_after: PropTypes.number,
  }),
  /** A test is in flight; the outcome is not known yet. */
  pending: PropTypes.bool,
  /** The name of the destination this result belongs to. */
  destination: PropTypes.string,
};

DeliveryResult.defaultProps = {
  result: null,
  pending: false,
  destination: null,
};

export default DeliveryResult;
