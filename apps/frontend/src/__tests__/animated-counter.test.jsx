import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import AnimatedCounter from '../components/discovery/AnimatedCounter.jsx';

describe('AnimatedCounter', () => {
  let originalRequestAnimationFrame;
  let originalCancelAnimationFrame;

  beforeEach(() => {
    vi.useFakeTimers();
    originalRequestAnimationFrame = globalThis.requestAnimationFrame;
    originalCancelAnimationFrame = globalThis.cancelAnimationFrame;

    globalThis.requestAnimationFrame = (callback) =>
      globalThis.setTimeout(() => callback(performance.now()), 16);
    globalThis.cancelAnimationFrame = (id) => {
      globalThis.clearTimeout(id);
    };
  });

  afterEach(() => {
    globalThis.requestAnimationFrame = originalRequestAnimationFrame;
    globalThis.cancelAnimationFrame = originalCancelAnimationFrame;
    vi.useRealTimers();
  });

  it('renders an em dash when value is zero', () => {
    render(<AnimatedCounter value={0} />);
    expect(screen.getByText('\u2014')).toBeInTheDocument();
  });

  it('animates from current to target value', () => {
    const { rerender } = render(<AnimatedCounter value={0} duration={120} />);
    expect(screen.getByText('\u2014')).toBeInTheDocument();

    rerender(<AnimatedCounter value={5} duration={120} />);

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.getByText('5')).toBeInTheDocument();
  });
});
