import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MapErrorBanner, ScanImportBanner } from '../components/map/MapStatusBanners';

describe('ScanImportBanner', () => {
  const pending = { scanId: 3, newCount: 2, results: [] };

  it('renders nothing without a pending scan', () => {
    const { container } = render(
      <ScanImportBanner pending={null} onReview={vi.fn()} onDismiss={vi.fn()} />
    );

    expect(container).toBeEmptyDOMElement();
  });

  it('pluralizes the discovered device count', () => {
    render(<ScanImportBanner pending={pending} onReview={vi.fn()} onDismiss={vi.fn()} />);

    expect(screen.getByText(/2 new devices discovered/)).toBeInTheDocument();
  });

  it('uses the singular form for a single device', () => {
    render(
      <ScanImportBanner
        pending={{ ...pending, newCount: 1 }}
        onReview={vi.fn()}
        onDismiss={vi.fn()}
      />
    );

    expect(screen.getByText(/1 new device discovered/)).toBeInTheDocument();
  });

  it('calls onReview and onDismiss from their controls', async () => {
    const onReview = vi.fn();
    const onDismiss = vi.fn();
    render(<ScanImportBanner pending={pending} onReview={onReview} onDismiss={onDismiss} />);

    await userEvent.click(screen.getByRole('button', { name: /Review/ }));
    await userEvent.click(screen.getByRole('button', { name: 'Dismiss' }));

    expect(onReview).toHaveBeenCalledTimes(1);
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});

describe('MapErrorBanner', () => {
  it('renders nothing without an error', () => {
    const { container } = render(<MapErrorBanner error={null} onRetry={vi.fn()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('shows the error message and retries on dismiss', async () => {
    const onRetry = vi.fn();
    render(<MapErrorBanner error="Failed to load topology" onRetry={onRetry} />);

    expect(screen.getByText('Failed to load topology')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /dismiss|retry/i }));

    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
