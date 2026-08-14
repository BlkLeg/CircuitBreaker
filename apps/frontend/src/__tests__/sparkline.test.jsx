import React from 'react';
import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';
import Sparkline from '../components/agents/Sparkline';
import { SPARKLINE_HEIGHT_PX, SPARKLINE_WIDTH_PX } from '../lib/constants';

/**
 * Design §5 names three cases for this component — zero, one and N points —
 * plus the head-value append. They are not edge cases padded onto a happy path:
 * an agent that just enrolled has no series at all, an agent one tick old has
 * exactly one sample, and a flat series (an idle box pinned at the same 3%) is
 * the common shape in a homelab fleet. Each of the three has its own way of
 * going wrong: a row of zeros the operator reads as "idle", an invisible line,
 * and a division by zero that writes NaN into the DOM.
 *
 * The assertions read the polyline's coordinates rather than string-matching
 * the `points` attribute: the exact rounding is an implementation detail, but
 * "the maximum is drawn above the minimum" and "the last point sits on the
 * right edge" are the properties the fleet table actually depends on.
 */

/** Index of the highest-drawn point — the smallest y, since SVG y grows down. */
function highestPointIndex(coords) {
  let bestIndex = 0;
  let bestY = coords[0].y;
  coords.forEach((point, index) => {
    if (point.y < bestY) {
      bestY = point.y;
      bestIndex = index;
    }
  });
  return bestIndex;
}

const MID_Y = SPARKLINE_HEIGHT_PX / 2;

/** The rendered polyline's coordinates as [{x, y}], in draw order. */
function coordsOf(container) {
  const polyline = container.querySelector('polyline');
  if (!polyline) return null;
  return polyline
    .getAttribute('points')
    .split(' ')
    .map((pair) => {
      const [x, y] = pair.split(',').map(Number);
      return { x, y };
    });
}

describe('Sparkline point counts', () => {
  it('renders nothing at all when there is no usable series', () => {
    // An agent that just came online has no samples yet. A flat line at zero
    // would be a claim about the host that nobody has measured.
    const { container } = render(<Sparkline points={[]} ariaLabel="CPU" />);

    expect(container.querySelector('svg')).toBeNull();
  });

  it('treats gaps as unknown rather than as zeros', () => {
    // null/undefined/NaN are missed samples, not readings of 0 — dropping them
    // keeps the shape honest instead of drawing a cliff to the floor.
    const { container } = render(<Sparkline points={[null, undefined, NaN, Infinity]} />);

    expect(container.querySelector('svg')).toBeNull();
  });

  it('draws a single sample as a flat line across the full width', () => {
    // One point is a fact, not a trend: level, visible, no implied direction.
    const { container } = render(<Sparkline points={[42]} ariaLabel="CPU" />);

    expect(coordsOf(container)).toEqual([
      { x: 0, y: MID_Y },
      { x: SPARKLINE_WIDTH_PX, y: MID_Y },
    ]);
  });

  it('spreads N points across the width and inverts them against their own min..max', () => {
    // 30 is the maximum and must be drawn nearest the top (SVG y grows down);
    // 10 is the minimum and sits nearest the bottom. Scaling against the
    // series' own range is what lets a box idling between 3% and 5% still show
    // a shape instead of a flat line at the bottom of the cell.
    const { container } = render(<Sparkline points={[10, 30, 20]} ariaLabel="CPU" />);
    const coords = coordsOf(container);

    expect(coords).toHaveLength(3);
    expect(coords.map((point) => point.x)).toEqual([0, SPARKLINE_WIDTH_PX / 2, SPARKLINE_WIDTH_PX]);
    expect(coords[1].y).toBeLessThan(coords[2].y);
    expect(coords[2].y).toBeLessThan(coords[0].y);
    // Inset by half the stroke, so neither the top nor the bottom of the line
    // is clipped by the viewBox edge.
    coords.forEach(({ y }) => {
      expect(y).toBeGreaterThan(0);
      expect(y).toBeLessThan(SPARKLINE_HEIGHT_PX);
    });
  });

  it('centres a flat series instead of dividing by zero', () => {
    // min === max, so the scaling ratio has no denominator. The failure mode
    // this pins is `NaN,NaN` reaching the DOM, which renders as nothing at all
    // and silently loses the row's CPU line.
    const { container } = render(<Sparkline points={[5, 5, 5, 5]} ariaLabel="CPU" />);
    const coords = coordsOf(container);

    expect(coords).toHaveLength(4);
    coords.forEach(({ x, y }) => {
      expect(Number.isFinite(x)).toBe(true);
      expect(y).toBe(MID_Y);
    });
    expect(container.querySelector('polyline').getAttribute('points')).not.toMatch(/NaN/);
  });
});

describe('Sparkline head-value append', () => {
  // Series/head coherence (design §3): useFleetMetrics appends the current head
  // value as the series' final point, because the 120s series lags the 30s head
  // by up to a tick and a row reading "81%" beside a line ending at 74% is a
  // contradiction the operator has to resolve themselves. These two tests pin
  // the half of that contract Sparkline owns — the appended point is the one
  // drawn at the right edge, and it changes the picture.
  const FETCHED_SERIES = [40, 42, 41];
  const HEAD_VALUE = 81;

  it('draws the appended head value at the right edge of the cell', () => {
    const { container } = render(
      <Sparkline points={[...FETCHED_SERIES, HEAD_VALUE]} ariaLabel="CPU" />
    );
    const coords = coordsOf(container);

    expect(coords).toHaveLength(FETCHED_SERIES.length + 1);
    const rightEdge = coords[coords.length - 1];
    expect(rightEdge.x).toBe(SPARKLINE_WIDTH_PX);
    // The head is the series maximum here, so the right edge is its highest
    // point — the line visibly ends where the number beside it says it does.
    expect(rightEdge.y).toBe(Math.min(...coords.map((point) => point.y)));
  });

  it('moves the right edge when the head moves, without touching the earlier points', () => {
    const { container: before } = render(<Sparkline points={FETCHED_SERIES} ariaLabel="CPU" />);
    const { container: after } = render(
      <Sparkline points={[...FETCHED_SERIES, HEAD_VALUE]} ariaLabel="CPU" />
    );

    const beforeCoords = coordsOf(before);
    const afterCoords = coordsOf(after);
    expect(afterCoords).toHaveLength(beforeCoords.length + 1);
    // The appended point is added, never substituted: the fetched samples are
    // all still on the line, just re-scaled against the new maximum.
    expect(highestPointIndex(afterCoords.slice(0, -1))).toBe(highestPointIndex(beforeCoords));
    expect(afterCoords[afterCoords.length - 1].y).toBeLessThan(
      Math.min(...afterCoords.slice(0, -1).map((point) => point.y))
    );
  });
});

describe('Sparkline accessibility and tone', () => {
  it('announces itself as an image when it carries a label', () => {
    const { getByRole } = render(<Sparkline points={[1, 2]} ariaLabel="CPU for box2" />);

    expect(getByRole('img', { name: 'CPU for box2' })).toBeInTheDocument();
  });

  it('hides itself when the number beside it already says everything', () => {
    // An unlabelled role="img" is an announced blank. Where the cell already
    // prints "62%", the line is decoration and is hidden rather than narrated.
    const { container } = render(<Sparkline points={[1, 2]} />);
    const svg = container.querySelector('svg');

    expect(svg).toHaveAttribute('aria-hidden', 'true');
    expect(svg).not.toHaveAttribute('role');
  });

  it('exposes its tone as an attribute so CSS colours it, never an inline style', () => {
    const { container } = render(<Sparkline points={[1, 2]} tone="critical" />);
    const svg = container.querySelector('svg');

    expect(svg).toHaveAttribute('data-tone', 'critical');
    expect(svg.getAttribute('style')).toBeNull();
  });

  it('defaults to the ok tone and keeps its own class alongside a caller class', () => {
    const { container } = render(<Sparkline points={[1, 2]} className="fleet-cell__spark" />);
    const svg = container.querySelector('svg');

    expect(svg).toHaveAttribute('data-tone', 'ok');
    expect(svg).toHaveClass('fleet-spark');
    expect(svg).toHaveClass('fleet-cell__spark');
  });
});
