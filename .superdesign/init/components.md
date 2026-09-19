# Shared UI components

Framework: React 18 with PropTypes. Styling is custom vanilla CSS; shared primitives use the `cb-*` namespace from `apps/frontend/src/styles/panels.css`.

## Panel

- Path: `apps/frontend/src/components/common/Panel.jsx`
- Props: `title`, `summary`, `tone`, `actions`, `bodyless`, `children`
- Purpose: titled bordered surface used throughout agent, monitor, discovery, and settings views.

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const TONES = ['default', 'ok', 'warn', 'danger', 'info'];

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
```

## StatTile

- Path: `apps/frontend/src/components/common/StatTile.jsx`
- Props: `label`, `value`, `points`, `hot`, `flash`
- Purpose: compact current-value tile with zero-baselined sparkline.

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const ABSENT = '—';
const VIEW_W = 120;
const VIEW_H = 26;
const MIN_POINTS = 2;

function polylinePoints(points) {
  const max = Math.max(...points) * 1.12 || 1;
  return points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * VIEW_W;
      const y = VIEW_H - (value / max) * (VIEW_H - 2);
      return `${x.toFixed(1)},${Math.max(1, Math.min(VIEW_H - 1, y)).toFixed(1)}`;
    })
    .join(' ');
}

export default function StatTile({ label, value, points = [], hot = false, flash = false }) {
  const hasSeries = points.length >= MIN_POINTS;
  return (
    <div className="cb-tile" data-hot={String(hot)} data-flash={String(flash)}>
      <div className="cb-tile__label">{label}</div>
      <div className="cb-tile__value">{value == null ? ABSENT : value}</div>
      {hasSeries ? (
        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="none" aria-hidden="true">
          <polyline points={polylinePoints(points)} />
        </svg>
      ) : null}
    </div>
  );
}

StatTile.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string,
  points: PropTypes.arrayOf(PropTypes.number),
  hot: PropTypes.bool,
  flash: PropTypes.bool,
};
```

## Tabs

- Path: `apps/frontend/src/components/common/Tabs.jsx`
- Props: `tabs`, `active`, `onChange`, `label`
- Purpose: accessible tablist with roving focus and activity indicators.

```jsx
import React, { useCallback, useEffect, useRef } from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const tabId = (key) => `cb-tab-${key}`;
const panelId = (key) => `cb-panel-${key}`;

export function panelPropsFor(key) {
  return { id: panelId(key), role: 'tabpanel', 'aria-labelledby': tabId(key), tabIndex: 0 };
}

function indicatorSuffix(indicator) {
  if (indicator === null || indicator === undefined || indicator === false) return '';
  if (indicator === true) return ' — new activity';
  return ` — ${indicator} new`;
}

export default function Tabs({ tabs, active, onChange, label }) {
  const tablistRef = useRef(null);
  const activeButtonRef = useRef(null);
  useEffect(() => {
    const tablist = tablistRef.current;
    const activeButton = activeButtonRef.current;
    if (tablist?.contains(document.activeElement)) activeButton?.focus();
  }, [active]);
  const onKeyDown = useCallback((event) => {
    const index = tabs.findIndex((tab) => tab.key === active);
    let next = null;
    if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    if (next === null) return;
    event.preventDefault();
    onChange(tabs[next].key);
  }, [tabs, active, onChange]);
  return (
    <div className="cb-tabs" role="tablist" aria-label={label} onKeyDown={onKeyDown} ref={tablistRef}>
      {tabs.map((tab) => {
        const selected = tab.key === active;
        const indicator = tab.indicator ?? null;
        const isCount = typeof indicator === 'number';
        return (
          <button key={tab.key} ref={selected ? activeButtonRef : null} type="button" role="tab"
            id={tabId(tab.key)} aria-controls={panelId(tab.key)} aria-selected={selected}
            aria-label={`${tab.label}${indicatorSuffix(indicator)}`} tabIndex={selected ? 0 : -1}
            className="cb-tab" onClick={() => onChange(tab.key)}>
            <span aria-hidden="true">{tab.label}</span>
            {indicator === null || indicator === false ? null : (
              <i aria-hidden="true" className={`cb-tab__indicator${isCount ? ' cb-tab__indicator--count' : ''}`}>
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
  tabs: PropTypes.arrayOf(PropTypes.shape({ key: PropTypes.string.isRequired, label: PropTypes.string.isRequired,
    indicator: PropTypes.oneOfType([PropTypes.bool, PropTypes.number]) })).isRequired,
  active: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  label: PropTypes.string.isRequired,
};
```

## Banner

- Path: `apps/frontend/src/components/common/Banner.jsx`
- Props: `tone`, `title`, `body`, `detail`, `actions`, `icon`
- Purpose: operator-facing condition and remediation callout.

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const TONES = ['ok', 'warn', 'danger', 'info'];
export default function Banner({ tone, title, body, detail = null, actions = null, icon = null }) {
  return (
    <div className="cb-banner" data-tone={tone} role="status">
      <p className="cb-banner__title">{icon === null ? null : <span aria-hidden="true">{icon}</span>}{title}</p>
      <p className="cb-banner__body">{body}</p>
      {detail === null ? null : <details className="cb-banner__why"><summary>Why?</summary><div className="cb-banner__why-body">{detail}</div></details>}
      {actions === null ? null : <div className="cb-banner__actions">{actions}</div>}
    </div>
  );
}
Banner.propTypes = { tone: PropTypes.oneOf(TONES).isRequired, title: PropTypes.string.isRequired,
  body: PropTypes.node.isRequired, detail: PropTypes.node, actions: PropTypes.node, icon: PropTypes.node };
```

## EmptyState

- Path: `apps/frontend/src/components/common/EmptyState.jsx`
- Props: `icon`, `message`, `hint`

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';
export default function EmptyState({ icon = null, message, hint = null }) {
  return <div className="cb-empty">
    {icon === null ? null : <span className="cb-empty__icon" aria-hidden="true">{icon}</span>}
    <div className="cb-empty__message">{message}</div>
    {hint === null ? null : <div className="cb-empty__hint">{hint}</div>}
  </div>;
}
EmptyState.propTypes = { icon: PropTypes.node, message: PropTypes.string.isRequired, hint: PropTypes.node };
```

## DetailHeader

- Path: `apps/frontend/src/components/common/DetailHeader.jsx`
- Props: `backTo`, `backLabel`, `title`, `chips`, `meta`, `actions`, `strip`
- Purpose: sticky detail-page identity header with global metric strip slot.

```jsx
import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import '../../styles/panels.css';
export default function DetailHeader({ backTo, backLabel, title, chips = null, meta = [], actions = null, strip = null }) {
  return <header className="cb-detail-head">
    <Link className="cb-detail-head__back" to={backTo}>← {backLabel}</Link>
    <div className="cb-detail-head__row"><h1 className="cb-detail-head__title">{title}</h1>
      {chips === null ? null : <div className="cb-detail-head__chips">{chips}</div>}
      {actions === null ? null : <div className="cb-detail-head__actions">{actions}</div>}</div>
    {meta.length === 0 ? null : <div className="cb-meta">{meta.map((item, index) => <span className="cb-meta__item" key={index}>{item}</span>)}</div>}
    {strip === null ? null : <div className="cb-detail-head__strip">{strip}</div>}
  </header>;
}
DetailHeader.propTypes = { backTo: PropTypes.string.isRequired, backLabel: PropTypes.string.isRequired,
  title: PropTypes.string.isRequired, chips: PropTypes.node, meta: PropTypes.arrayOf(PropTypes.node),
  actions: PropTypes.node, strip: PropTypes.node };
```
