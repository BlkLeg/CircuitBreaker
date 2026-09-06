import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const TONES = ['default', 'ok', 'warn', 'danger', 'info'];

/**
 * A titled, bordered surface.
 *
 * The title is both the visible label and the region's accessible name, so a
 * screen reader walking the page hears the same headings a sighted operator
 * scans. `summary` is for a reading of the panel's own contents ("0 of 8 in
 * use") — it is not a place for prose.
 *
 * `bodyless` exists for panels whose content is a full-bleed table: the padded
 * body would inset the table away from the border it should meet.
 */
export default function Panel({
  title,
  summary = null,
  tone = 'default',
  actions = null,
  bodyless = false,
  children,
}) {
  return (
    <section className="cb-panel" data-tone={tone} aria-label={title}>
      <div className="cb-panel__head">
        <h3 className="cb-panel__title">{title}</h3>
        {summary === null ? null : <span className="cb-panel__summary">{summary}</span>}
        {actions === null ? null : <div className="cb-panel__actions">{actions}</div>}
      </div>
      {bodyless ? children : <div className="cb-panel__body">{children}</div>}
    </section>
  );
}

Panel.propTypes = {
  title: PropTypes.string.isRequired,
  summary: PropTypes.node,
  tone: PropTypes.oneOf(TONES),
  actions: PropTypes.node,
  bodyless: PropTypes.bool,
  children: PropTypes.node,
};
