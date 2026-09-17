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

/** WCAG contrast ratio between two colours, 1..21. */
export function contrastRatio(a, b) {
  const [lighter, darker] = [relativeLuminance(a), relativeLuminance(b)].sort((x, y) => y - x);
  return (lighter + 0.05) / (darker + 0.05);
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
 * A palette's text colour, lightened or darkened only as far as legibility needs.
 *
 * Presets carry `text` and `textMuted` as raw values and applyTheme used to
 * write them through untouched, so how readable the app was depended entirely
 * on the palette author. Measured across the shipped presets, 20 of 28
 * preset/mode pairs put muted text below WCAG AA's 4.5:1 against the surface it
 * sits on; 8 were below 3:1, and monokai's dark muted was 1.74:1 — present in
 * the DOM and effectively invisible. `solarized-dark` managed it with its
 * *primary* text, at 3.19:1.
 *
 * Text is blended toward whichever of black/white contrasts with the surface,
 * in 2% steps, stopping at the first value that clears `minRatio` against every
 * surface it can appear on. That keeps the palette's hue wherever the hue was
 * already legible — a passing colour is returned untouched — and gives up the
 * hue only where keeping it would mean text nobody can read.
 *
 * @param {string} hex - the palette's colour.
 * @param {string[]} surfaces - every background this text may sit on.
 * @param {number} [minRatio] - 4.5:1, WCAG AA for body text.
 */
export function deriveReadableText(hex, surfaces, minRatio = 4.5) {
  const backgrounds = surfaces.filter((s) => channels(s));
  if (!channels(hex) || backgrounds.length === 0) return hex;
  const clears = (candidate) => backgrounds.every((s) => contrastRatio(candidate, s) >= minRatio);
  if (clears(hex)) return hex;
  // Direction is decided by the primary surface: on a dark panel text moves
  // toward white, on a light one toward black.
  const target = contrastingForeground(backgrounds[0]) === '#000000' ? '#000000' : '#ffffff';
  for (let pct = 2; pct < 100; pct += 2) {
    const candidate = mixHex(hex, target, pct);
    if (clears(candidate)) return candidate;
  }
  return target;
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
