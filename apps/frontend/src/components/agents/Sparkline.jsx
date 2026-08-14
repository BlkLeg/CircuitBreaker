import PropTypes from 'prop-types';
import {
  SPARKLINE_HEIGHT_PX,
  SPARKLINE_STROKE_WIDTH,
  SPARKLINE_WIDTH_PX,
} from '../../lib/constants';

/**
 * Sparkline — a hand-rolled inline SVG trend line for one fleet-table cell.
 *
 * Deliberately NOT Recharts, even though Recharts is the house chart library
 * (components/monitors/LatencyChart.jsx and the three privacy charts). Recharts
 * draws through a <ResponsiveContainer>, which mounts its own ResizeObserver
 * per instance: the fleet table shows ~16 rows with three sparklines each, so
 * the "obvious" reuse would put dozens of observers on the page, all of them
 * re-measuring and re-rendering on every 30s presence tick. This component has
 * no dependency, no observer and no state — fixed width/height from
 * lib/constants, one <polyline>, done. Recharts remains the right tool for the
 * detail page's real charts, which are single instances with axes and tooltips.
 *
 * The three cases are all real and all reachable:
 *   0 usable points — an agent that just came online has no series yet. Render
 *                     nothing; a flat line at zero would be a claim we cannot make.
 *   1 usable point  — a fact, not a trend. Flat line at mid-height.
 *   N usable points — scaled against the series' own min..max, so a box idling
 *                     between 3% and 5% still shows its shape.
 */

const SPARKLINE_CLASS = 'fleet-spark';
const LINE_CLASS = 'fleet-spark__line';
const DEFAULT_TONE = 'ok';

// Named once so the two "half of" computations below — the stroke inset and the
// mid-height baseline — visibly read as the same idea rather than a stray 2.
const HALF = 0.5;
// Half the stroke straddles either side of the path, so the drawable band is
// inset by that much top and bottom; otherwise a point at the series maximum
// gets its top half clipped by the viewBox edge.
const STROKE_INSET_PX = SPARKLINE_STROKE_WIDTH * HALF;
// Below this a series has no direction to draw, only a level.
const MIN_POINTS_FOR_TREND = 2;
// Coordinates are rounded before they reach the DOM: 1/3 of 64px is
// 21.333333333333332 in full, and three of those per row per tick is a lot of
// string churn for sub-pixel detail nobody can see at 16px tall.
const COORD_DECIMALS = 2;

const roundCoord = (value) => Number(value.toFixed(COORD_DECIMALS));

// Gaps are dropped rather than interpolated or zero-filled: a missed sample
// means "we do not know", and the shape of the surrounding samples is the
// honest answer. Covers null, undefined, NaN and Infinity in one test.
const toUsableValues = (points) =>
  Array.isArray(points) ? points.filter((value) => Number.isFinite(value)) : [];

/**
 * Map values onto a `points` attribute for the polyline.
 *
 * x is spread evenly across the full width (the series is evenly sampled by
 * construction — the backend buckets it onto a fixed 75s grid). y is scaled
 * against the series' own min..max and inverted, because SVG's y axis grows
 * downward and the maximum has to land at the top.
 */
function buildPolylinePoints(values, width, height) {
  const midY = roundCoord(height * HALF);
  if (values.length < MIN_POINTS_FOR_TREND) {
    return `0,${midY} ${roundCoord(width)},${midY}`;
  }

  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min;
  const topY = STROKE_INSET_PX;
  const bottomY = height - STROKE_INSET_PX;
  const stepX = width / (values.length - 1);

  return values
    .map((value, index) => {
      // A flat series has no min..max to scale against; centring it beats
      // dividing by zero and rendering NaN into the DOM.
      const ratio = span === 0 ? HALF : (value - min) / span;
      const x = roundCoord(index * stepX);
      const y = roundCoord(bottomY - ratio * (bottomY - topY));
      return `${x},${y}`;
    })
    .join(' ');
}

export default function Sparkline({
  points,
  width = SPARKLINE_WIDTH_PX,
  height = SPARKLINE_HEIGHT_PX,
  ariaLabel,
  className,
  tone = DEFAULT_TONE,
}) {
  const values = toUsableValues(points);
  if (values.length === 0) return null;

  const rootClassName = className ? `${SPARKLINE_CLASS} ${className}` : SPARKLINE_CLASS;

  // An aria-label is what makes a line meaningful without sight of it; an
  // unlabelled role="img" is just an announced blank. Callers that already say
  // the number next to the line pass no label, and the graphic is hidden.
  const labelProps = ariaLabel
    ? { role: 'img', 'aria-label': ariaLabel }
    : { 'aria-hidden': 'true' };

  // preserveAspectRatio="none" stretches the viewBox to the cell instead of
  // letterboxing it — with a fixed 34px row and fixed column widths there is
  // nothing to measure, which is the whole point of not using a container that
  // observes its own size. vectorEffect keeps the stroke an honest 1.25px
  // despite that uneven scaling; focusable="false" keeps IE-era SVG out of the
  // tab order of a table that already has real controls in it.
  return (
    <svg
      className={rootClassName}
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      data-tone={tone}
      focusable="false"
      {...labelProps}
    >
      <polyline
        className={LINE_CLASS}
        fill="none"
        strokeWidth={SPARKLINE_STROKE_WIDTH}
        vectorEffect="non-scaling-stroke"
        points={buildPolylinePoints(values, width, height)}
      />
    </svg>
  );
}

Sparkline.propTypes = {
  // Nulls and non-finite entries are gaps, not zeros — see toUsableValues.
  points: PropTypes.arrayOf(PropTypes.number),
  width: PropTypes.number,
  height: PropTypes.number,
  ariaLabel: PropTypes.string,
  className: PropTypes.string,
  // Drives colour via CSS `[data-tone=...]`, never an inline style.
  tone: PropTypes.oneOf(['ok', 'warn', 'critical']),
};
