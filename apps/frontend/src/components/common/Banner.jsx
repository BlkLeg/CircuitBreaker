import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const TONES = ['ok', 'warn', 'danger', 'info'];

/**
 * A toned callout carrying a condition and what to do about it.
 *
 * `body` is the short imperative an operator acts on. `detail` is the full
 * explanation — on the agent pages that is the AGT-14/15/16 prose, reproduced
 * verbatim. It is rendered inside a collapsed <details> rather than mounted on
 * demand so that the text stays in the DOM: searchable with the browser's own
 * find, and reachable by a screen reader walking the document.
 *
 * role="status" and not role="alert": these conditions are already true when
 * the page loads, and an alert would interrupt on every navigation.
 */
export default function Banner({ tone, title, body, detail = null, actions = null, icon = null }) {
  return (
    <div className="cb-banner" data-tone={tone} role="status">
      <p className="cb-banner__title">
        {icon === null ? null : <span aria-hidden="true">{icon}</span>}
        {title}
      </p>
      <p className="cb-banner__body">{body}</p>
      {detail === null ? null : (
        <details className="cb-banner__why">
          <summary>Why?</summary>
          <div className="cb-banner__why-body">{detail}</div>
        </details>
      )}
      {actions === null ? null : <div className="cb-banner__actions">{actions}</div>}
    </div>
  );
}

Banner.propTypes = {
  tone: PropTypes.oneOf(TONES).isRequired,
  title: PropTypes.string.isRequired,
  body: PropTypes.node.isRequired,
  detail: PropTypes.node,
  actions: PropTypes.node,
  icon: PropTypes.node,
};
