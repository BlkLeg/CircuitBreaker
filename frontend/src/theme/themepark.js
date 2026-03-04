/**
 * Vendored theme.park palettes translated to Circuit Breaker's theme object
 * shape.  All six are dark-only palettes so their `light` variant mirrors
 * `dark`.  They are registered in presets.js alongside the native themes.
 *
 * Color field mapping from the theme.park palette table:
 *   primary    ← Accent (main interactive colour)
 *   secondary  ← Surface 2 (used as panel / sidebar background)
 *   accent1    ← Warning colour (secondary highlight)
 *   accent2    ← Success colour (positive accent)
 *   background ← Background
 *   surface    ← Surface
 *   surfaceAlt ← Surface 2
 *   border     ← Border
 *   text       ← Text primary
 *   textMuted  ← Text muted
 *   gridLine   ← Primary at 0.1 opacity
 */

const tp = (primary, bg, surface, surfaceAlt, border, text, textMuted, accent1, accent2, gridLine) => ({
  dark: { primary, secondary: surfaceAlt, accent1, accent2, background: bg, surface, surfaceAlt, border, text, textMuted, gridLine },
  light: { primary, secondary: surfaceAlt, accent1, accent2, background: bg, surface, surfaceAlt, border, text, textMuted, gridLine },
});

export const THEMEPARK_PRESETS = {
  'tp-maroon': tp(
    '#c0392b',  // primary  (Accent)
    '#2b0011',  // background
    '#3d0018',  // surface
    '#4d001f',  // surfaceAlt / secondary
    '#6b0030',  // border
    '#f5c6d0',  // text
    '#9e6070',  // textMuted
    '#e67e22',  // accent1  (Warning)
    '#27ae60',  // accent2  (Success)
    'rgba(192,57,43,0.1)',
  ),
  'tp-hotline': tp(
    '#e040fb',  // primary
    '#1a0533',
    '#2b0d4f',
    '#3a1566',
    '#5b3098',
    '#e8d4ff',
    '#8870b0',
    '#ff6d00',  // accent1 (Warning)
    '#7c4dff',  // accent2 (Success – violet to differentiate)
    'rgba(224,64,251,0.1)',
  ),
  'tp-aquamarine': tp(
    '#00e5ff',  // primary
    '#00303d',
    '#004d63',
    '#005f7a',
    '#007fa8',
    '#c8f0ff',
    '#7ab8cc',
    '#ffea00',  // accent1 (Warning – gold on teal)
    '#00e676',  // accent2 (Success)
    'rgba(0,229,255,0.1)',
  ),
  'tp-space-gray': tp(
    '#6e6e6e',  // primary
    '#1f1f1f',
    '#2d2d2d',
    '#383838',
    '#4a4a4a',
    '#e0e0e0',
    '#9a9a9a',
    '#ff9800',  // accent1 (Warning)
    '#4caf50',  // accent2 (Success)
    'rgba(110,110,110,0.12)',
  ),
  'tp-hotpink': tp(
    '#ff40aa',  // primary
    '#1a0028',
    '#2d004a',
    '#3d0060',
    '#5e0080',
    '#f0c8ff',
    '#9060aa',
    '#ff6d00',  // accent1 (Warning)
    '#c040ff',  // accent2 (Success – purple)
    'rgba(255,64,170,0.1)',
  ),
  'tp-overseer': tp(
    '#6366f1',  // primary
    '#111827',
    '#1f2937',
    '#374151',
    '#4b5563',
    '#f9fafb',
    '#9ca3af',
    '#f59e0b',  // accent1 (Warning)
    '#10b981',  // accent2 (Success)
    'rgba(99,102,241,0.1)',
  ),
};

export const THEMEPARK_LABELS = {
  'tp-maroon':     'Maroon',
  'tp-hotline':    'Hotline',
  'tp-aquamarine': 'Aquamarine',
  'tp-space-gray': 'Space Gray',
  'tp-hotpink':    'Hotpink',
  'tp-overseer':   'Overseer',
};
