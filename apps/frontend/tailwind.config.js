/**
 * A theme colour that accepts Tailwind's opacity modifier (`tw-bg-cb-border/30`).
 *
 * Declared as a bare `var(--color-…)` string, Tailwind v3 cannot split the colour
 * into channels, so every `/NN` class built on it generated no CSS at all and the
 * element silently lost that style. color-mix() with transparent applies the
 * opacity to the live CSS variable, so it still follows the user's theme.
 */
const themeColor =
  (variable) =>
  ({ opacityValue } = {}) =>
    opacityValue === undefined
      ? `var(${variable})`
      : `color-mix(in srgb, var(${variable}) calc(${opacityValue} * 100%), transparent)`;

/** @type {import('tailwindcss').Config} */
export default {
  // All of src/: a directory-by-directory list silently dropped every class in
  // src/features/ when the map moved there, which unstyled its context menus.
  content: ['./src/**/*.{js,jsx}', '!./src/__tests__/**'],
  // Restrict Tailwind to discovery bulk-actions components only.
  // This prevents Tailwind's reset/base from affecting existing CSS.
  prefix: 'tw-',
  important: false,
  corePlugins: {
    preflight: false, // Don't inject Tailwind resets — preserves existing styles
  },
  theme: {
    extend: {
      colors: {
        // Map to CSS custom properties from main.css
        'cb-bg': themeColor('--color-bg'),
        'cb-surface': themeColor('--color-surface'),
        'cb-surface-raised': themeColor('--color-surface-raised'),
        'cb-secondary': themeColor('--color-secondary'),
        'cb-border': themeColor('--color-border'),
        'cb-primary': themeColor('--color-primary'),
        'cb-primary-h': themeColor('--color-primary-hover'),
        'cb-danger': themeColor('--color-danger'),
        'cb-text': themeColor('--color-text'),
        'cb-muted': themeColor('--color-text-muted'),
        'cb-online': themeColor('--color-online'),
      },
      fontFamily: {
        cb: 'var(--font)',
      },
      borderRadius: {
        cb: 'var(--radius)',
      },
      backdropBlur: {
        md: '12px',
      },
    },
  },
  plugins: [],
};
