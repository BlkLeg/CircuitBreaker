/**
 * Pure colour derivation for the theme pipeline.
 *
 * Everything here is a function of the active palette alone. No DOM, no
 * module-level cache: plan 00 forbids "JS caches of the initial palette",
 * and a cache is exactly how the old fixed --color-surface-raised survived
 * every theme change.
 *
 * theme/applyTheme.js is the only consumer that writes these to the DOM.
 */

const HEX = /^#([0-9a-f]{6})$/i;

function channels(hex) {
  const match = typeof hex === 'string' ? HEX.exec(hex.trim()) : null;
  if (!match) return null;
  const value = match[1];
  return [
    Number.parseInt(value.slice(0, 2), 16),
    Number.parseInt(value.slice(2, 4), 16),
    Number.parseInt(value.slice(4, 6), 16),
  ];
}

function toHex(rgb) {
  return `#${rgb
    .map((c) =>
      Math.max(0, Math.min(255, Math.round(c)))
        .toString(16)
        .padStart(2, '0')
    )
    .join('')}`;
}

/**
 * WCAG relative luminance, 0..1.
 *
 * Unparseable input answers 0 rather than NaN. NaN would compare false against
 * every threshold, so a malformed custom colour would be silently classified
 * as dark instead of loudly wrong.
 */
export function relativeLuminance(hex) {
  const rgb = channels(hex);
  if (!rgb) return 0;
  const [r, g, b] = rgb.map((c) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * True when a colour reads as a light SURFACE.
 *
 * The midpoint is right for "which way should a raised panel move" and wrong
 * for "what colour should text on this be" -- see contrastingForeground.
 */
export function isLightColor(hex) {
  return relativeLuminance(hex) > 0.5;
}

/**
 * The luminance at which black text overtakes white text.
 *
 * From the WCAG contrast formula: black wins once (L+0.05)/0.05 exceeds
 * 1.05/(L+0.05), i.e. once L > sqrt(1.05*0.05) - 0.05 = 0.1791. It is NOT the
 * 0.5 midpoint, and using 0.5 here is a real bug rather than a rounding
 * preference: Gruvbox green (#b8bb26) has luminance 0.459, so a midpoint test
 * calls it dark and paints white text on it -- 1.9:1, unreadable -- when black
 * on it is 9.1:1.
 */
const BLACK_TEXT_THRESHOLD = 0.1791;

/**
 * Black or white, whichever contrasts more with `hex`.
 *
 * This is the token plan 00 permits "only if existing primitives cannot
 * express it safely". They cannot: a selected navigator row paints
 * --color-primary behind its label, and presets range from #00f5ff to
 * #7c3aed, so neither a fixed white nor a fixed black label works.
 */
export function contrastingForeground(hex) {
  return relativeLuminance(hex) > BLACK_TEXT_THRESHOLD ? '#000000' : '#ffffff';
}

/** Linear channel-wise blend from `hex` toward `towardHex`, `pct` in 0..100. */
export function mixHex(hex, towardHex, pct) {
  const from = channels(hex);
  const to = channels(towardHex);
  if (!from || !to) return hex;
  const f = Math.max(0, Math.min(100, pct)) / 100;
  return toHex(from.map((c, i) => c + (to[i] - c) * f));
}

/**
 * The surface one step above the panel surface.
 *
 * Direction follows the surface, not the theme name: a "light" theme.park
 * preset whose light entry mirrors its dark colours still gets a lighter
 * raised surface, because the decision reads the colour it was handed.
 */
export function deriveSurfaceRaised(surfaceHex) {
  if (!channels(surfaceHex)) return surfaceHex;
  return isLightColor(surfaceHex)
    ? mixHex(surfaceHex, '#000000', 6)
    : mixHex(surfaceHex, '#ffffff', 8);
}

/**
 * Semantic status colours per effective mode.
 *
 * No preset carries these — presets.js variants stop at gridLine — so they are
 * supplied centrally rather than invented per screen. Plan 00: "Never treat
 * accent2 as automatically meaning success."
 */
export const STATUS_DEFAULTS = {
  dark: {
    success: '#4ade80',
    warning: '#fbbf24',
    danger: '#f87171',
    info: '#60a5fa',
  },
  light: {
    success: '#15803d',
    warning: '#a16207',
    danger: '#b91c1c',
    info: '#1d4ed8',
  },
};

/**
 * Every custom property applyTheme writes.
 *
 * Task 2 clears this exact list before each apply, so switching from a rich
 * palette to a sparse one cannot leave a stale value behind. Task 10's token
 * gate reads it to know which tokens count as runtime-defined.
 */
export const DERIVED_TOKEN_NAMES = [
  '--color-primary',
  '--color-primary-hover',
  '--color-primary-fg',
  '--color-primary-rgb',
  '--color-glow',
  '--accent-1',
  '--accent-2',
  '--accent-3',
  '--color-bg',
  '--color-surface',
  '--color-surface-alt',
  '--color-surface-raised',
  '--color-secondary',
  '--color-border',
  '--color-text',
  '--color-text-muted',
  '--color-grid-line',
  '--color-success',
  '--color-warning',
  '--color-danger',
  '--color-danger-hover',
  '--color-info',
];
