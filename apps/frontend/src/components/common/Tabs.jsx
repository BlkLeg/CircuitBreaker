import React, { useCallback } from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const tabId = (key) => `cb-tab-${key}`;
const panelId = (key) => `cb-panel-${key}`;

/**
 * The attributes a tab's panel must carry. Exported so consumers do not
 * re-derive the id convention and drift out of agreement with the tablist.
 */
export function panelPropsFor(key) {
  return {
    id: panelId(key),
    role: 'tabpanel',
    'aria-labelledby': tabId(key),
    tabIndex: 0,
  };
}

/** The indicator, stated in words, for the tab's accessible name. */
function indicatorSuffix(indicator) {
  if (indicator === null || indicator === undefined || indicator === false) return '';
  if (indicator === true) return ' — new activity';
  return ` — ${indicator} new`;
}

/**
 * An ARIA tablist with roving focus.
 *
 * Selection follows focus (arrow keys change the active tab, not merely the
 * focused one), which is the correct pattern when panels are cheap to render.
 * Every panel here is already-fetched state, so there is no cost to landing on
 * one while arrowing past.
 */
export default function Tabs({ tabs, active, onChange, label }) {
  const onKeyDown = useCallback(
    (event) => {
      const index = tabs.findIndex((tab) => tab.key === active);
      let next = null;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      if (next === null) return;
      event.preventDefault();
      onChange(tabs[next].key);
    },
    [tabs, active, onChange]
  );

  return (
    <div className="cb-tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown}>
      {tabs.map((tab) => {
        const selected = tab.key === active;
        const indicator = tab.indicator ?? null;
        const isCount = typeof indicator === 'number';
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            id={tabId(tab.key)}
            aria-controls={panelId(tab.key)}
            aria-selected={selected}
            aria-label={`${tab.label}${indicatorSuffix(indicator)}`}
            tabIndex={selected ? 0 : -1}
            className="cb-tab"
            onClick={() => onChange(tab.key)}
          >
            <span aria-hidden="true">{tab.label}</span>
            {indicator === null || indicator === false ? null : (
              <i
                aria-hidden="true"
                className={`cb-tab__indicator${isCount ? ' cb-tab__indicator--count' : ''}`}
              >
                {isCount ? indicator : ''}
              </i>
            )}
          </button>
        );
      })}
    </div>
  );
}

Tabs.propTypes = {
  tabs: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      indicator: PropTypes.oneOfType([PropTypes.bool, PropTypes.number]),
    })
  ).isRequired,
  active: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  label: PropTypes.string.isRequired,
};
