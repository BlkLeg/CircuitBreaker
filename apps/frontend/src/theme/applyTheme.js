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

  // Apply primary + accents
  if (variant.primary) {
    root.style.setProperty('--color-primary', variant.primary);
    root.style.setProperty('--color-primary-hover', darkenHex(variant.primary, 15));
    root.style.setProperty('--color-glow', hexToRgba(variant.primary, 0.35));
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
  if (variant.text) root.style.setProperty('--color-text', variant.text);
  if (variant.textMuted) root.style.setProperty('--color-text-muted', variant.textMuted);
  if (variant.gridLine) root.style.setProperty('--color-grid-line', variant.gridLine);

  // Persist preset key for next-page-load pre-apply (eliminates theme flash)
  if (presetKey) {
    localStorage.setItem('cb-theme-preset', presetKey);
  }
}
