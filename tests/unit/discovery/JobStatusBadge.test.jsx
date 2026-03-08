import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import JobStatusBadge from '../../components/discovery/JobStatusBadge';

describe('JobStatusBadge', () => {
  it('renders "Queued" for queued status', () => {
    render(<JobStatusBadge status="queued" />);
    expect(screen.getByText('Queued')).toBeInTheDocument();
  });

  it('renders "Scanning" for running status', () => {
    render(<JobStatusBadge status="running" />);
    expect(screen.getByText('Scanning')).toBeInTheDocument();
  });

  it('renders "Completed" for done status', () => {
    render(<JobStatusBadge status="done" />);
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  it('renders "Completed" for completed status (alias)', () => {
    render(<JobStatusBadge status="completed" />);
    expect(screen.getByText('Completed')).toBeInTheDocument();
  });

  it('renders "Failed" for failed status', () => {
    render(<JobStatusBadge status="failed" />);
    expect(screen.getByText('Failed')).toBeInTheDocument();
  });

  it('renders "Cancelled" for cancelled status', () => {
    render(<JobStatusBadge status="cancelled" />);
    expect(screen.getByText('Cancelled')).toBeInTheDocument();
  });

  it('running status includes a spin animation style', () => {
    const { container } = render(<JobStatusBadge status="running" />);
    const icon = container.querySelector('svg');
    expect(icon).toHaveStyle('animation: spin 1.2s linear infinite');
  });

  it('non-running statuses do not include spin animation', () => {
    const { container } = render(<JobStatusBadge status="done" />);
    const icon = container.querySelector('svg');
    expect(icon).not.toHaveStyle('animation: spin 1.2s linear infinite');
  });
});
