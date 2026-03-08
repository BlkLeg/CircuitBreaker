import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PortsEditor from '../components/PortsEditor';

function renderEditor(ports = [], onChange = vi.fn()) {
  return render(<PortsEditor value={ports} onChange={onChange} />);
}

describe('PortsEditor', () => {
  it('renders empty state with Add port button', () => {
    renderEditor([]);
    expect(screen.getByRole('button', { name: /add port/i })).toBeInTheDocument();
  });

  it('renders existing ports from props', () => {
    const ports = [{ port: 8080, protocol: 'tcp', label: 'web' }];
    renderEditor(ports);
    expect(screen.getByDisplayValue('8080')).toBeInTheDocument();
  });

  it('adds new empty row on Add port click', () => {
    const onChange = vi.fn();
    renderEditor([], onChange);
    fireEvent.click(screen.getByRole('button', { name: /add port/i }));
    expect(onChange).toHaveBeenCalled();
    const newPorts = onChange.mock.calls[0][0];
    expect(newPorts.length).toBe(1);
  });

  it('removes row on delete button click', () => {
    const onChange = vi.fn();
    const ports = [{ port: 8080, protocol: 'tcp', label: '' }];
    renderEditor(ports, onChange);

    const deleteBtn = screen.getByRole('button', { name: /remove|delete|×/i });
    fireEvent.click(deleteBtn);
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('updates port value on input change', () => {
    const onChange = vi.fn();
    const ports = [{ port: 8080, protocol: 'tcp', label: '' }];
    renderEditor(ports, onChange);

    const portInput = screen.getByDisplayValue('8080');
    fireEvent.change(portInput, { target: { value: '9090' } });
    expect(onChange).toHaveBeenCalled();
    const updated = onChange.mock.calls[0][0];
    expect(updated[0].port).toBe(9090);
  });

  it('updates protocol on dropdown change', () => {
    const onChange = vi.fn();
    const ports = [{ port: 53, protocol: 'tcp', label: '' }];
    renderEditor(ports, onChange);

    const select = screen.getByDisplayValue('tcp');
    fireEvent.change(select, { target: { value: 'udp' } });
    expect(onChange).toHaveBeenCalled();
    const updated = onChange.mock.calls[0][0];
    expect(updated[0].protocol).toBe('udp');
  });

  it('passes structured ports array to onChange prop', () => {
    const onChange = vi.fn();
    renderEditor([], onChange);
    fireEvent.click(screen.getByRole('button', { name: /add port/i }));

    const calls = onChange.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    expect(Array.isArray(calls[0][0])).toBe(true);
  });
});
