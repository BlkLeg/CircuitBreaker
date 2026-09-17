import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DockerSourceCard from '../components/discovery/DockerSourceCard';

vi.mock('../components/common/EntityPicker', () => ({
  default: ({ isOpen, onSelect }) =>
    isOpen ? (
      <button
        data-testid="entity-picker"
        onClick={() => onSelect({ ref: { entity_type: 'hardware', entity_id: 9 } })}
      >
        pick host
      </button>
    ) : null,
}));

const source = (over = {}) => ({
  id: 1,
  name: 'Local daemon',
  connection_kind: 'socket',
  endpoint_hint: '/var/run/docker.sock',
  enabled: true,
  revision: 3,
  parent_type: null,
  parent_id: null,
  parent_provenance: 'unresolved',
  last_attempt_at: null,
  last_success_at: null,
  ...over,
});

const run = (over = {}) => ({
  id: 'run-1',
  source_id: 1,
  status: 'succeeded',
  containers_complete: true,
  networks_complete: true,
  containers_observed: 2,
  ...over,
});

function renderCard(props = {}) {
  return render(
    <DockerSourceCard
      source={source()}
      run={null}
      containers={[]}
      onSync={vi.fn()}
      onAssignParent={vi.fn()}
      {...props}
    />
  );
}

describe('DockerSourceCard', () => {
  it('names the source and where it connects', () => {
    renderCard();
    expect(screen.getByText('Local daemon')).toBeInTheDocument();
    expect(screen.getByText(/var\/run\/docker\.sock/)).toBeInTheDocument();
  });

  it('shows last attempt and last success as separate rows', () => {
    renderCard({
      source: source({
        last_attempt_at: '2026-09-15T10:00:00Z',
        last_success_at: '2026-09-14T09:00:00Z',
      }),
      run: run({ status: 'failed', containers_complete: false }),
    });

    expect(screen.getByText('Last attempt')).toBeInTheDocument();
    expect(screen.getByText('Last success')).toBeInTheDocument();
  });

  it('warns that the inventory shown is the last good one after a failure', () => {
    renderCard({
      source: source({
        last_attempt_at: '2026-09-15T10:00:00Z',
        last_success_at: '2026-09-14T09:00:00Z',
      }),
      run: run({ status: 'failed', containers_complete: false }),
      containers: [{ id: 1, name: 'web', native_id: 'abc', parent_provenance: 'automatic' }],
    });

    expect(screen.getByText(/last good picture|not the current one/i)).toBeInTheDocument();
  });

  it('says a reachable daemon reported nothing, rather than showing a bare empty list', () => {
    renderCard({ run: run({ containers_observed: 0 }), containers: [] });
    expect(screen.getByText(/reachable and reported no containers/i)).toBeInTheDocument();
  });

  it('will not call an attempted source synced when no run explains it', () => {
    renderCard({
      source: source({ last_attempt_at: '2026-09-17T10:00:00Z' }),
      run: null,
    });

    expect(screen.getByText('Outcome unknown')).toBeInTheDocument();
    expect(screen.queryByText('Synced')).not.toBeInTheDocument();
    expect(screen.queryByText(/reachable and reported no containers/i)).not.toBeInTheDocument();
  });

  it('separates a container list it could not read from one that is empty', () => {
    renderCard({
      source: source({
        last_attempt_at: '2026-09-17T10:00:00Z',
        last_success_at: '2026-09-17T10:00:00Z',
      }),
      run: run({ containers_observed: 3 }),
      containers: [],
      containersUnreadable: true,
    });

    expect(screen.getByText(/container list could not be loaded/i)).toBeInTheDocument();
    expect(screen.queryByText(/reachable and reported no containers/i)).not.toBeInTheDocument();
  });

  it('blocks a second sync while one is running and says why', () => {
    const onSync = vi.fn();
    renderCard({ run: run({ status: 'running' }), onSync });

    const button = screen.getByRole('button', { name: /sync/i });
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onSync).not.toHaveBeenCalled();
    expect(screen.getByText(/already running/i)).toBeInTheDocument();
  });

  it('allows a retry after a failure', () => {
    const onSync = vi.fn();
    renderCard({ run: run({ status: 'failed', containers_complete: false }), onSync });

    fireEvent.click(screen.getByRole('button', { name: /sync/i }));
    expect(onSync).toHaveBeenCalledWith(1);
  });

  it('explains that a manual parent survives rediscovery', () => {
    renderCard({
      source: source({ parent_type: 'hardware', parent_id: 4, parent_provenance: 'manual' }),
    });
    expect(screen.getByText(/will not overwrite it/i)).toBeInTheDocument();
  });

  it('sends the revision it last saw when a parent is corrected', () => {
    const onAssignParent = vi.fn();
    renderCard({ source: source({ revision: 7 }), onAssignParent });

    fireEvent.click(screen.getByRole('button', { name: /assign host|change host/i }));
    fireEvent.click(screen.getByTestId('entity-picker'));

    expect(onAssignParent).toHaveBeenCalledWith(1, {
      parent_type: 'hardware',
      parent_id: 9,
      expected_revision: 7,
    });
  });

  it('marks a partial result as incomplete coverage', () => {
    renderCard({
      run: run({ status: 'partial', containers_complete: false }),
      containers: [{ id: 1, name: 'web', native_id: 'abc', parent_provenance: 'automatic' }],
    });
    // Both the status line and the list note qualify the result; the list note
    // is the one that says what the list itself can be trusted to mean.
    expect(screen.getByText(/may be missing containers/i)).toBeInTheDocument();
  });

  it('uses theme tokens rather than baked-in colours', () => {
    const { container } = renderCard({
      run: run({ status: 'failed', containers_complete: false }),
    });
    expect(container.innerHTML).not.toMatch(/#[0-9a-f]{3,8}\b/i);
  });
});
