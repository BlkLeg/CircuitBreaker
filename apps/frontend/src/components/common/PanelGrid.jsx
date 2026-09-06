import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/**
 * Auto-fit grid of Panels. `min` is the narrowest a column may get before the
 * grid drops one — it is passed as a custom property rather than an inline
 * grid-template so the responsive behaviour stays in CSS where it can be read.
 */
export default function PanelGrid({ min = 232, children }) {
  return (
    <div className="cb-panel-grid" style={{ '--cb-grid-min': `${min}px` }}>
      {children}
    </div>
  );
}

PanelGrid.propTypes = {
  min: PropTypes.number,
  children: PropTypes.node,
};
