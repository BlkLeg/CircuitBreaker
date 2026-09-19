import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Tabs, { panelPropsFor } from '../components/common/Tabs';

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'telemetry', label: 'Telemetry' },
  { key: 'events', label: 'Events' },
];

function renderTabs(props = {}) {
  const onChange = props.onChange ?? vi.fn();
  const utils = render(
    <Tabs
      tabs={TABS}
      active={props.active ?? 'overview'}
      onChange={onChange}
      label="Agent sections"
    />
  );
  return { ...utils, onChange };
}

// A bare vi.fn() never updates `active`, so it cannot exercise whether DOM
// focus actually follows a selection change — this wrapper holds real state
// and wires a real onChange, the way every caller of Tabs will.
function StatefulTabs({ initial }) {
  const [active, setActive] = React.useState(initial);
  return <Tabs tabs={TABS} active={active} onChange={setActive} label="Agent sections" />;
}

describe('Tabs', () => {
  it('marks only the active tab as selected', () => {
    renderTabs({ active: 'telemetry' });
    expect(screen.getByRole('tab', { name: 'Telemetry' }).getAttribute('aria-selected')).toBe(
      'true'
    );
    expect(screen.getByRole('tab', { name: 'Overview' }).getAttribute('aria-selected')).toBe(
      'false'
    );
  });

  it('reports the key of the tab that was clicked', async () => {
    const { onChange } = renderTabs();
    await userEvent.click(screen.getByRole('tab', { name: 'Events' }));
    expect(onChange).toHaveBeenCalledWith('events');
  });

  it('keeps only the active tab in the tab order', () => {
    // Roving tabindex: one Tab keystroke enters the tablist, then arrow keys
    // move within it. Without this, a five-tab bar costs five Tab presses to
    // step over.
    renderTabs({ active: 'overview' });
    expect(screen.getByRole('tab', { name: 'Overview' }).tabIndex).toBe(0);
    expect(screen.getByRole('tab', { name: 'Telemetry' }).tabIndex).toBe(-1);
  });

  it('moves to the next tab on ArrowRight', async () => {
    const { onChange } = renderTabs({ active: 'overview' });
    screen.getByRole('tab', { name: 'Overview' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onChange).toHaveBeenCalledWith('telemetry');
  });

  it('wraps from the last tab to the first on ArrowRight', async () => {
    const { onChange } = renderTabs({ active: 'events' });
    screen.getByRole('tab', { name: 'Events' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(onChange).toHaveBeenCalledWith('overview');
  });

  it('wraps backwards from the first tab on ArrowLeft', async () => {
    const { onChange } = renderTabs({ active: 'overview' });
    screen.getByRole('tab', { name: 'Overview' }).focus();
    await userEvent.keyboard('{ArrowLeft}');
    expect(onChange).toHaveBeenCalledWith('events');
  });

  it('jumps to the first and last tab on Home and End', async () => {
    const { onChange } = renderTabs({ active: 'telemetry' });
    screen.getByRole('tab', { name: 'Telemetry' }).focus();
    await userEvent.keyboard('{Home}');
    expect(onChange).toHaveBeenCalledWith('overview');
    await userEvent.keyboard('{End}');
    expect(onChange).toHaveBeenCalledWith('events');
  });

  it('announces a boolean indicator in the accessible name, not by colour alone', () => {
    render(
      <Tabs
        tabs={[{ key: 'telemetry', label: 'Telemetry', indicator: true }]}
        active="overview"
        onChange={() => {}}
        label="Agent sections"
      />
    );
    expect(screen.getByRole('tab', { name: 'Telemetry — new activity' })).toBeTruthy();
  });

  it('announces a numeric indicator as a count', () => {
    render(
      <Tabs
        tabs={[{ key: 'events', label: 'Events', indicator: 3 }]}
        active="overview"
        onChange={() => {}}
        label="Agent sections"
      />
    );
    expect(screen.getByRole('tab', { name: 'Events — 3 new' })).toBeTruthy();
  });

  it('links each tab to the panel it controls', () => {
    renderTabs({ active: 'overview' });
    const tab = screen.getByRole('tab', { name: 'Overview' });
    expect(tab.getAttribute('aria-controls')).toBe('cb-panel-overview');
    expect(tab.id).toBe('cb-tab-overview');
  });

  it('moves DOM focus to the newly active tab when selection follows an ArrowRight', async () => {
    // A mocked onChange never updates `active`, so the earlier ArrowRight
    // tests only prove the key handler *reports* the right key — not that
    // focus actually lands where aria-selected and tabIndex say it should.
    render(<StatefulTabs initial="overview" />);
    screen.getByRole('tab', { name: 'Overview' }).focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Telemetry' }));
  });

  it('does not steal focus into the tablist merely because it rendered', () => {
    render(<StatefulTabs initial="telemetry" />);
    expect(document.activeElement).not.toBe(screen.getByRole('tab', { name: 'Telemetry' }));
  });
});

describe('panelPropsFor', () => {
  it('produces panel attributes matching the tab id convention', () => {
    expect(panelPropsFor('telemetry')).toEqual({
      id: 'cb-panel-telemetry',
      role: 'tabpanel',
      'aria-labelledby': 'cb-tab-telemetry',
      tabIndex: 0,
    });
  });
});
