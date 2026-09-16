import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import IpConflictAlert from '../components/common/IpConflictAlert';

describe('IpConflictAlert', () => {
  it('renders the conflicting asset label and inspect action', () => {
    const onInspect = vi.fn();
    render(
      <IpConflictAlert
        conflictContext={{
          conflicts: [
            {
              entity_type: 'hardware',
              entity_id: 9,
              entity_name: 'nas-01',
              conflicting_ip: '192.168.10.20',
            },
          ],
        }}
        onInspect={onInspect}
      />
    );
    expect(screen.getAllByText(/nas-01/).length).toBeGreaterThan(0);
    expect(screen.getByText(/192\.168\.10\.20/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Inspect nas-01/i }));
    expect(onInspect).toHaveBeenCalledWith(
      expect.objectContaining({ entity_id: 9, entity_name: 'nas-01' })
    );
  });

  it('renders nothing without conflicts', () => {
    const { container } = render(<IpConflictAlert conflictContext={{ conflicts: [] }} />);
    expect(container.firstChild).toBeNull();
  });
});
