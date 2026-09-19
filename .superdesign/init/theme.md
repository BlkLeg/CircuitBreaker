# Theme and token context

## Compact token summary

- Default preset: Gruvbox Dark.
- Background `#282828`; surface/secondary `#3c3836`; raised surface `#32302f`; border `#504945`.
- Primary amber `#fe8019`; primary hover `#d86d15`; danger `#fb4934`; warning `#d79921`; success `#b8bb26`; info/telemetry `#83a598`.
- Text `#ebdbb2`; muted text `#c8bfb0` (AA-conscious contrast).
- Primary font: `system-ui, -apple-system, sans-serif`; telemetry/identifiers: `ui-monospace, SFMono-Regular, Menlo, Consolas, monospace`.
- Type ramp: 9.5px micro labels, 11px supporting, 12.5px compact body, 13px standard body, 19px section display, 21px metric values.
- Spacing: 4, 8, 12, 16, 24, 32px. Radius: 6px. Header: 60px.
- Main page background uses a faint 40px amber grid over a radial surface-to-background gradient.
- Breakpoints used most often: 1440, 1279, 1100, 1024, 820, 768, 700, 640px.
- Reduced-motion disables decorative pulses and panel transitions.
- The active theme preset is runtime-configurable; all feature UI must use CSS variables, never hard-code replacement brand colors.

## Raw core custom properties

Source: `apps/frontend/src/styles/main.css` and `apps/frontend/src/styles/panels.css`.

```css
:root {
  --header-height: 60px;
  --color-bg: #282828;
  --color-surface: #3c3836;
  --color-secondary: #3c3836;
  --color-border: #504945;
  --color-primary: #fe8019;
  --color-primary-rgb: 254, 128, 25;
  --color-primary-hover: #d86d15;
  --color-danger: #fb4934;
  --color-danger-hover: #cc241d;
  --color-text: #ebdbb2;
  --color-text-muted: #c8bfb0;
  --color-online: #b8bb26;
  --color-success: #b8bb26;
  --color-warning: #d79921;
  --color-info: #83a598;
  --color-muted: var(--color-text-muted);
  --color-glow: rgba(var(--color-primary-rgb), 0.35);
  --font: system-ui, -apple-system, sans-serif;
  --font-size-base: 16px;
  --radius: 6px;
  --color-grid-line: rgba(var(--color-primary-rgb), 0.1);
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 24px;
  --space-6: 32px;
  --panel-pad: var(--space-3);
  --panel-gap: var(--space-3);
  --fs-micro: 9.5px;
  --fs-xs: 11px;
  --fs-sm: 12.5px;
  --fs-md: 13px;
  --fs-lg: 19px;
  --fs-xl: 21px;
  --color-surface-raised: #32302f;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
```

## Tailwind configuration (complete)

Source: `apps/frontend/tailwind.config.js`.

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./src/components/**/*.{js,jsx}', './src/pages/**/*.{js,jsx}', './src/lib/**/*.{js,jsx}'],
  prefix: 'tw-',
  important: false,
  corePlugins: { preflight: false },
  theme: {
    extend: {
      colors: {
        'cb-bg': 'var(--color-bg)', 'cb-surface': 'var(--color-surface)',
        'cb-secondary': 'var(--color-secondary)', 'cb-border': 'var(--color-border)',
        'cb-primary': 'var(--color-primary)', 'cb-primary-h': 'var(--color-primary-hover)',
        'cb-danger': 'var(--color-danger)', 'cb-text': 'var(--color-text)',
        'cb-muted': 'var(--color-text-muted)', 'cb-online': 'var(--color-online)',
      },
      fontFamily: { cb: 'var(--font)' },
      borderRadius: { cb: 'var(--radius)' },
      backdropBlur: { md: '12px' },
    },
  },
  plugins: [],
};
```
