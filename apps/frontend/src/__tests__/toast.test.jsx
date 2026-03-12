import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { ToastProvider, useToast } from '../components/common/Toast';

// Helper component that exposes toast methods via buttons
function ToastTrigger() {
  const toast = useToast();
  return (
    <div>
      <button onClick={() => toast.success('Success message')}>Show Success</button>
      <button onClick={() => toast.error('Error message')}>Show Error</button>
    </div>
  );
}

describe('Toast', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('renders success toast with message', async () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Show Success'));
    });

    expect(screen.getByText('Success message')).toBeInTheDocument();
    // Success toast should display the checkmark icon
    expect(screen.getByText('\u2713')).toBeInTheDocument();
  });

  it('renders error toast with message', async () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Show Error'));
    });

    expect(screen.getByText('Error message')).toBeInTheDocument();
    // Error toast should display the X icon
    expect(screen.getByText('\u2715')).toBeInTheDocument();
  });

  it('auto-dismisses after timeout', async () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Show Success'));
    });

    expect(screen.getByText('Success message')).toBeInTheDocument();

    // Success toasts dismiss after 5000ms
    await act(async () => {
      vi.advanceTimersByTime(5100);
    });

    expect(screen.queryByText('Success message')).not.toBeInTheDocument();
  });

  it('manual dismiss on click', async () => {
    render(
      <ToastProvider>
        <ToastTrigger />
      </ToastProvider>
    );

    await act(async () => {
      fireEvent.click(screen.getByText('Show Success'));
    });

    expect(screen.getByText('Success message')).toBeInTheDocument();

    // Click the dismiss button (the x button with aria-label)
    const dismissBtn = screen.getByLabelText('Dismiss notification');
    await act(async () => {
      fireEvent.click(dismissBtn);
    });

    expect(screen.queryByText('Success message')).not.toBeInTheDocument();
  });
});
