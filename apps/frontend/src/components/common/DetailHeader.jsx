import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import '../../styles/panels.css';

/**
 * The identity header of a detail page.
 *
 * `meta` entries are wrapped here, not by the caller. The separator between
 * them is an adjacent-sibling CSS rule, and a caller passing a bare string
 * would produce a text node that no sibling selector can match — which is
 * exactly how the fleet table's pending row came to render its fields run
 * together. Owning the wrapper makes that unreachable.
 *
 * `strip` is a slot for content that is shared by every tab. It is
 * omitted entirely when null rather than rendered empty: reserved space that
 * never fills reads as something failing to load.
 */
export default function DetailHeader({
  backTo,
  backLabel,
  title,
  chips = null,
  meta = [],
  actions = null,
  strip = null,
}) {
  return (
    <header className="cb-detail-head">
      <Link className="cb-detail-head__back" to={backTo}>
        ← {backLabel}
      </Link>
      <div className="cb-detail-head__row">
        <h1 className="cb-detail-head__title">{title}</h1>
        {chips === null ? null : <div className="cb-detail-head__chips">{chips}</div>}
        {actions === null ? null : <div className="cb-detail-head__actions">{actions}</div>}
      </div>
      {meta.length === 0 ? null : (
        <div className="cb-meta">
          {meta.map((item, index) => (
            // Index as key is fine here: meta entries are positional fields
            // of one record (status, platform, version), have no identity of
            // their own, and this list never reorders.
            <span className="cb-meta__item" key={index}>
              {item}
            </span>
          ))}
        </div>
      )}
      {strip === null ? null : <div className="cb-detail-head__strip">{strip}</div>}
    </header>
  );
}

DetailHeader.propTypes = {
  backTo: PropTypes.string.isRequired,
  backLabel: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired,
  chips: PropTypes.node,
  meta: PropTypes.arrayOf(PropTypes.node),
  actions: PropTypes.node,
  strip: PropTypes.node,
};
