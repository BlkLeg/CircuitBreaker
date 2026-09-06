import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import AgentEndpointsSection from '../components/settings/AgentEndpointsSection';

describe('AgentEndpointsSection', () => {
  it('renders the configured endpoints', () => {
    render(
      <AgentEndpointsSection
        endpoints={[{ id: 'a1', label: 'LAN', url: 'https://10.0.0.5' }]}
        onSave={vi.fn()}
      />
    );
    expect(screen.getByDisplayValue('LAN')).toBeInTheDocument();
    expect(screen.getByDisplayValue('https://10.0.0.5')).toBeInTheDocument();
  });

  it('explains what the address is for, because it is not the browser URL', () => {
    render(<AgentEndpointsSection endpoints={[]} onSave={vi.fn()} />);
    expect(screen.getByText(/agents will dial/i)).toBeInTheDocument();
  });

  it('saves an added endpoint', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(<AgentEndpointsSection endpoints={[]} onSave={onSave} />);
    fireEvent.click(screen.getByRole('button', { name: /add endpoint/i }));
    fireEvent.change(screen.getByLabelText(/label/i), { target: { value: 'Public' } });
    fireEvent.change(screen.getByLabelText(/address/i), {
      target: { value: 'https://cb.example.com' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith([{ label: 'Public', url: 'https://cb.example.com' }])
    );
  });

  it('keeps the id of an existing row, so an old install command still resolves', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    render(
      <AgentEndpointsSection
        endpoints={[{ id: 'a1', label: 'LAN', url: 'https://10.0.0.5' }]}
        onSave={onSave}
      />
    );
    fireEvent.change(screen.getByDisplayValue('LAN'), { target: { value: 'Home LAN' } });
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    await waitFor(() =>
      expect(onSave).toHaveBeenCalledWith([
        { id: 'a1', label: 'Home LAN', url: 'https://10.0.0.5' },
      ])
    );
  });

  // Spec §6 item 4: an endpoint nothing ever enrolled through is a smell the
  // operator can act on. The alternative evidence is an agent that never
  // appeared, which is the invisible failure this slice exists to end.
  it('says how many agents came through each address', () => {
    render(
      <AgentEndpointsSection
        endpoints={[
          { id: 'a1', label: 'LAN', url: 'https://10.0.0.5' },
          { id: 'a2', label: 'Public', url: 'https://cb.example.com' },
        ]}
        usage={{ 'https://10.0.0.5': 2 }}
        onSave={vi.fn()}
      />
    );
    expect(screen.getByText(/2 agents enrolled/i)).toBeInTheDocument();
    expect(
      screen.getByText(/no agents have enrolled through this address yet/i)
    ).toBeInTheDocument();
  });

  it('counts one agent in the singular', () => {
    render(
      <AgentEndpointsSection
        endpoints={[{ id: 'a1', label: 'LAN', url: 'https://10.0.0.5' }]}
        usage={{ 'https://10.0.0.5': 1 }}
        onSave={vi.fn()}
      />
    );
    expect(screen.getByText(/1 agent enrolled/i)).toBeInTheDocument();
  });

  it('claims nothing about usage while the counts have not loaded', () => {
    render(
      <AgentEndpointsSection
        endpoints={[{ id: 'a1', label: 'LAN', url: 'https://10.0.0.5' }]}
        onSave={vi.fn()}
      />
    );
    // "no agents have enrolled" would be a false statement, not a pending one.
    expect(screen.queryByText(/no agents have enrolled/i)).not.toBeInTheDocument();
  });

  it('surfaces the server rejection rather than pretending the save worked', async () => {
    const onSave = vi
      .fn()
      .mockRejectedValue({ response: { data: { detail: 'endpoint url must not have a path' } } });
    render(
      <AgentEndpointsSection
        endpoints={[{ id: 'a1', label: 'LAN', url: 'https://10.0.0.5/nope' }]}
        onSave={onSave}
      />
    );
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }));
    expect(await screen.findByRole('alert')).toHaveTextContent('endpoint url must not have a path');
  });
});
