import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import NodeHandles from '../components/map/nodes/NodeHandles';

vi.mock('reactflow', () => ({
  Handle: (props) => <div data-testid="rf-handle" {...props} />,
  Position: { Top: 'top', Right: 'right', Bottom: 'bottom', Left: 'left' },
}));

describe('NodeHandles', () => {
  it('renders all handle points but hides unconnected ones by default', () => {
    const { getAllByTestId } = render(
      <NodeHandles connectedHandleIds={new Set(['right', 'bottom'])} isConnecting={false} />
    );

    const handles = getAllByTestId('rf-handle');
    expect(handles).toHaveLength(16);

    // Each visible handle point renders both source and target handles.
    const visibleHandles = handles.filter((h) => h.style.opacity === '1');
    expect(visibleHandles).toHaveLength(4);
  });

  it('renders all 8 handle points while connecting', () => {
    const { getAllByTestId } = render(
      <NodeHandles connectedHandleIds={new Set()} isConnecting={true} />
    );

    // 8 points * (source + target) = 16 handles.
    expect(getAllByTestId('rf-handle')).toHaveLength(16);
  });
});
