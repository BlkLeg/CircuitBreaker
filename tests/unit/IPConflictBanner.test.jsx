import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import IPConflictBanner from '../components/IPConflictBanner';

function renderBanner(conflicts) {
  return render(
    <MemoryRouter>
      <IPConflictBanner conflicts={conflicts} />
    </MemoryRouter>
  );
}

describe('IPConflictBanner', () => {
  it('renders nothing when conflicts array is empty', () => {
    const { container } = renderBanner([]);
    expect(container.firstChild).toBeNull();
  });

  it('renders one row per conflict', () => {
    const conflicts = [
      { entity_type: 'hardware', entity_id: 1, entity_name: 'pve-01', conflicting_ip: '10.0.0.1', conflicting_port: null, protocol: null },
      { entity_type: 'service', entity_id: 2, entity_name: 'Plex', conflicting_ip: '10.0.0.1', conflicting_port: 8080, protocol: 'tcp' },
    ];
    renderBanner(conflicts);
    expect(screen.getByText(/pve-01/)).toBeInTheDocument();
    expect(screen.getByText(/Plex/)).toBeInTheDocument();
  });

  it('shows entity type and name in each row', () => {
    const conflicts = [
      { entity_type: 'hardware', entity_id: 1, entity_name: 'pve-01', conflicting_ip: '10.0.0.1', conflicting_port: null, protocol: null },
    ];
    renderBanner(conflicts);
    expect(screen.getByText(/hardware/i)).toBeInTheDocument();
    expect(screen.getByText(/pve-01/)).toBeInTheDocument();
  });

  it('renders Open link for each conflict with entity_id', () => {
    const conflicts = [
      { entity_type: 'hardware', entity_id: 1, entity_name: 'pve-01', conflicting_ip: '10.0.0.1', conflicting_port: null, protocol: null },
    ];
    renderBanner(conflicts);
    expect(screen.getByText(/open/i)).toBeInTheDocument();
  });

  it('does not render Open link when entity_id is null', () => {
    const conflicts = [
      { entity_type: 'hardware', entity_id: null, entity_name: 'unknown', conflicting_ip: '10.0.0.1', conflicting_port: null, protocol: null },
    ];
    renderBanner(conflicts);
    expect(screen.queryByText(/open/i)).toBeNull();
  });

  it('renders ip and port correctly when both present', () => {
    const conflicts = [
      { entity_type: 'service', entity_id: 2, entity_name: 'Plex', conflicting_ip: '10.0.0.5', conflicting_port: 8080, protocol: 'tcp' },
    ];
    renderBanner(conflicts);
    expect(screen.getByText(/10\.0\.0\.5/)).toBeInTheDocument();
    expect(screen.getByText(/8080/)).toBeInTheDocument();
  });

  it('renders ip only correctly when port is null', () => {
    const conflicts = [
      { entity_type: 'hardware', entity_id: 1, entity_name: 'pve-01', conflicting_ip: '10.0.0.1', conflicting_port: null, protocol: null },
    ];
    renderBanner(conflicts);
    expect(screen.getByText(/10\.0\.0\.1/)).toBeInTheDocument();
  });
});
