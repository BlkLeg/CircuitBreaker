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
