import React from 'react';
import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import Panel from '../components/common/Panel';
import PanelGrid from '../components/common/PanelGrid';

describe('Panel', () => {
  it('labels itself with its title so a screen reader can find the region', () => {
    render(<Panel title="Capabilities">body text</Panel>);
    const region = screen.getByRole('region', { name: 'Capabilities' });
    expect(region).toBeTruthy();
    expect(region.textContent).toContain('body text');
  });

  it('renders a summary and actions in the header', () => {
    render(
      <Panel title="Probes" summary="0 of 8 in use" actions={<button type="button">Add</button>}>
        body
      </Panel>
    );
    expect(screen.getByText('0 of 8 in use')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Add' })).toBeTruthy();
  });

  it('carries its tone as a data attribute rather than a colour class', () => {
    const { container } = render(
      <Panel title="Scope" tone="warn">
        x
      </Panel>
    );
    expect(container.querySelector('.cb-panel').getAttribute('data-tone')).toBe('warn');
  });

  it('defaults to the neutral tone', () => {
    const { container } = render(<Panel title="Scope">x</Panel>);
    expect(container.querySelector('.cb-panel').getAttribute('data-tone')).toBe('default');
  });

  it('omits the padded body when bodyless, so a table can reach the panel edge', () => {
    const { container } = render(
      <Panel title="Jobs" bodyless>
        <table />
      </Panel>
    );
    expect(container.querySelector('.cb-panel__body')).toBeNull();
    expect(container.querySelector('table')).toBeTruthy();
  });
});

describe('PanelGrid', () => {
  it('passes its minimum column width through as a custom property', () => {
    const { container } = render(
      <PanelGrid min={300}>
        <Panel title="A">a</Panel>
      </PanelGrid>
    );
    const grid = container.querySelector('.cb-panel-grid');
    expect(grid.style.getPropertyValue('--cb-grid-min')).toBe('300px');
  });

  it('defaults to a 232px minimum', () => {
    const { container } = render(
      <PanelGrid>
        <Panel title="A">a</Panel>
      </PanelGrid>
    );
    expect(container.querySelector('.cb-panel-grid').style.getPropertyValue('--cb-grid-min')).toBe(
      '232px'
    );
  });
});
