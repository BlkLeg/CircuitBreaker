import {
  DERIVED_TOKEN_NAMES,
  STATUS_DEFAULTS,
  contrastingForeground,
  deriveReadableText,
  deriveSurfaceRaised,
  isLightColor,
} from './tokens';

function darkenHex(hex, pct) {
  const f = 1 - pct / 100;
  const r = Math.round(parseInt(hex.slice(1, 3), 16) * f);
  const g = Math.round(parseInt(hex.slice(3, 5), 16) * f);
  const b = Math.round(parseInt(hex.slice(5, 7), 16) * f);
  return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
}

function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

export function applyTheme(presetOrColors, presetKey) {
  const root = document.documentElement;
  const isLight = root.getAttribute('data-theme') === 'light';

  // Support legacy format or flat custom colors during migration
  const variant =
    presetOrColors && presetOrColors.dark && presetOrColors.light
      ? isLight
        ? presetOrColors.light
        : presetOrColors.dark
      : presetOrColors;

  if (!variant) return;

  // Every assignment below is conditional, because a palette may omit any
  // field. That made the old implementation leak: an omitted field kept the
  // PREVIOUS theme's value forever. Clearing the full set first turns each
  // apply into a complete statement of the theme rather than a patch on top
  // of whatever happened to be there. The static :root definitions in
  // styles/*.css are untouched by removeProperty, so clearing falls back to
  // the stylesheet baseline rather than to nothing.
  for (const name of DERIVED_TOKEN_NAMES) {
    root.style.removeProperty(name);
  }

  // Apply primary + accents
  if (variant.primary) {
    root.style.setProperty('--color-primary', variant.primary);
    root.style.setProperty('--color-primary-hover', darkenHex(variant.primary, 15));
    root.style.setProperty('--color-glow', hexToRgba(variant.primary, 0.35));
    // Selected rows and primary buttons paint text ON the primary colour.
    // Presets run from #00f5ff to #7c3aed, so the label colour has to follow.
    root.style.setProperty('--color-primary-fg', contrastingForeground(variant.primary));
    const pr = Number.parseInt(variant.primary.slice(1, 3), 16);
    const pg = Number.parseInt(variant.primary.slice(3, 5), 16);
    const pb = Number.parseInt(variant.primary.slice(5, 7), 16);
    root.style.setProperty('--color-primary-rgb', `${pr}, ${pg}, ${pb}`);
  }
  if (variant.accent1) root.style.setProperty('--accent-1', variant.accent1);
  if (variant.accent2) {
    root.style.setProperty('--accent-2', variant.accent2);
    root.style.setProperty('--accent-3', variant.accent2);
  }

  // Always apply surface and background variables now
  if (variant.background) root.style.setProperty('--color-bg', variant.background);
  if (variant.surface) root.style.setProperty('--color-surface', variant.surface);
  if (variant.surfaceAlt) root.style.setProperty('--color-surface-alt', variant.surfaceAlt);
  if (variant.secondary) root.style.setProperty('--color-secondary', variant.secondary);
  if (variant.border) root.style.setProperty('--color-border', variant.border);
  // Text is floored to WCAG AA against every surface it can land on, rather
  // than written through as the palette supplied it. A preset's muted colour is
  // chosen for looks, and across the shipped presets most of them chose one
  // that cannot be read on their own panels — see deriveReadableText. The floor
  // only ever raises contrast: a palette whose text already passes is written
  // through unchanged.
  const textSurfaces = [
    variant.surface,
    variant.background,
    variant.surfaceAlt,
    variant.surface ? deriveSurfaceRaised(variant.surface) : null,
  ].filter(Boolean);
  if (variant.text) {
    root.style.setProperty('--color-text', deriveReadableText(variant.text, textSurfaces));
  }
  if (variant.textMuted) {
    root.style.setProperty(
      '--color-text-muted',
      deriveReadableText(variant.textMuted, textSurfaces)
    );
  }
  if (variant.gridLine) root.style.setProperty('--color-grid-line', variant.gridLine);

  // Raised surfaces and status colours: no preset carries either, so they are
  // derived centrally rather than left as the fixed Gruvbox values that used
  // to sit in panels.css and main.css.
  const surface = variant.surface;
  if (surface) {
    root.style.setProperty('--color-surface-raised', deriveSurfaceRaised(surface));
  }

  // The mode that decides status colours is read from the surface actually in
  // use, not from the data-theme attribute. theme.park presets deliberately
  // mirror their dark colours into their light entries; plan 00 requires that
  // documented behaviour be preserved, and reading the surface preserves it.
  const effectiveMode = isLightColor(surface ?? (isLight ? '#ffffff' : '#000000'))
    ? 'light'
    : 'dark';
  const status = STATUS_DEFAULTS[effectiveMode];
  root.style.setProperty('--color-success', status.success);
  root.style.setProperty('--color-warning', status.warning);
  root.style.setProperty('--color-danger', status.danger);
  root.style.setProperty('--color-danger-hover', darkenHex(status.danger, 15));
  root.style.setProperty('--color-info', status.info);

  // Persist preset key for next-page-load pre-apply (eliminates theme flash)
  if (presetKey) {
    localStorage.setItem('cb-theme-preset', presetKey);
  }
}
