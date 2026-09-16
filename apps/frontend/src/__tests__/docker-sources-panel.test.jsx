import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import DockerSourcesPanel from '../components/discovery/DockerSourcesPanel';
import * as discoveryApi from '../api/discovery';

vi.mock('../api/discovery', () => ({
  listDockerSources: vi.fn(),
  getDockerSourceContainers: vi.fn(),
  syncDocker: vi.fn(),
  getDockerRun: vi.fn(),
  assignDockerSourceParent: vi.fn(),
}));

vi.mock('../components/common/EntityPicker', () => ({ default: () => null }));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

const source = {
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
};

describe('DockerSourcesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    discoveryApi.listDockerSources.mockResolvedValue({ data: [source] });
    discoveryApi.getDockerSourceContainers.mockResolvedValue({ data: [] });
  });

  it('shows a loading state before the sources arrive', () => {
    let resolve;
    discoveryApi.listDockerSources.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      })
    );
    render(<DockerSourcesPanel />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    resolve({ data: [] });
  });

  it('reports a failure to load rather than rendering an empty panel', async () => {
    discoveryApi.listDockerSources.mockRejectedValue(new Error('Boom'));
    render(<DockerSourcesPanel />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it('says when no source is configured instead of looking broken', async () => {
    discoveryApi.listDockerSources.mockResolvedValue({ data: [] });
    render(<DockerSourcesPanel />);

    await waitFor(() => expect(screen.getByText(/no docker source/i)).toBeInTheDocument());
  });

  it('renders a card per configured source', async () => {
    render(<DockerSourcesPanel />);
    await waitFor(() => expect(screen.getByText('Local daemon')).toBeInTheDocument());
  });

  it('starts a sync and reports that it was queued, not that it finished', async () => {
    discoveryApi.syncDocker.mockResolvedValue({
      data: { status: 'queued', source_id: 1, run_id: 'run-9' },
    });
    discoveryApi.getDockerRun.mockResolvedValue({
      data: { id: 'run-9', source_id: 1, status: 'running', containers_complete: false },
    });

    render(<DockerSourcesPanel />);
    await waitFor(() => screen.getByText('Local daemon'));
    fireEvent.click(screen.getByRole('button', { name: /sync/i }));

    await waitFor(() => expect(discoveryApi.syncDocker).toHaveBeenCalled());
    expect(mockToast.success).not.toHaveBeenCalled();
    expect(mockToast.info).toHaveBeenCalledWith(expect.stringMatching(/queued/i));
  });

  it('surfaces a refused duplicate sync without pretending it started', async () => {
    discoveryApi.syncDocker.mockRejectedValue({
      response: { status: 409, data: { detail: 'A sync is already running.' } },
      message: 'A sync is already running.',
    });

    render(<DockerSourcesPanel />);
    await waitFor(() => screen.getByText('Local daemon'));
    fireEvent.click(screen.getByRole('button', { name: /sync/i }));

    await waitFor(() => expect(mockToast.error).toHaveBeenCalled());
    expect(mockToast.info).not.toHaveBeenCalledWith(expect.stringMatching(/queued/i));
  });

  it('refetches when the caller signals a completed run', async () => {
    const { rerender } = render(<DockerSourcesPanel reloadToken={0} />);
    await waitFor(() => expect(discoveryApi.listDockerSources).toHaveBeenCalledTimes(1));

    rerender(<DockerSourcesPanel reloadToken={1} />);
    await waitFor(() => expect(discoveryApi.listDockerSources).toHaveBeenCalledTimes(2));
  });
});
