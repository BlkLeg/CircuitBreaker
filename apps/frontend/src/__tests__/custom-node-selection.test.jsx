import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';
import CustomNode from '../components/map/CustomNode';

vi.mock('reactflow', () => ({
  Handle: (props) => <div data-testid="rf-handle" {...props} />,
  Position: { Top: 'top', Right: 'right', Bottom: 'bottom', Left: 'left' },
  useStore: (selector) => selector({ transform: [0, 0, 1] }),
}));

describe('CustomNode selected geometry', () => {
  it('does not apply scale transform when selected', () => {
    const { container } = render(
      <CustomNode
        selected
        data={{
          label: 'Node 1',
          nodeShape: 'server',
          status: 'active',
          telemetry_status: 'healthy',
          glowColor: '#4a7fa5',
        }}
      />
    );

    const scaledElements = Array.from(container.querySelectorAll('*')).filter((el) =>
      String(el.style?.transform || '').includes('scale(1.1)')
    );
    expect(scaledElements).toHaveLength(0);
  });
});
