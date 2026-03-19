import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';

const viewportState = { viewport: { x: 0, y: 0, zoom: 1 } };
const projectPosition = (position) => position;

vi.mock('reactflow', () => ({
  useStore: (selector) => selector(viewportState),
  useReactFlow: () => ({
    project: projectPosition,
  }),
}));

vi.mock('framer-motion', () => ({
  AnimatePresence: ({ children }) => <>{children}</>,
  motion: {
    div: ({ children, ...props }) => <div {...props}>{children}</div>,
  },
}));

import WifiOverlay from '../components/map/WifiOverlay';

describe('WifiOverlay', () => {
  it('renders when node is missing positionAbsolute', () => {
    const nodes = [
      {
        id: 'router-1',
        position: { x: 100, y: 200 },
        width: 120,
        height: 80,
        data: { _hwRole: 'router', download_speed_mbps: 250 },
      },
    ];

    expect(() => render(<WifiOverlay nodes={nodes} />)).not.toThrow();
  });
});
