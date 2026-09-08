import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { applyTheme } from '../theme/applyTheme';
import { relativeLuminance } from '../theme/tokens';

const RICH = {
  primary: '#b8bb26',
  secondary: '#0f172a',
  accent1: '#ff2d95',
  accent2: '#6bffb5',
  background: '#1d2021',
  surface: '#3c3836',
  surfaceAlt: '#504945',
  border: '#665c54',
  text: '#ebdbb2',
  textMuted: '#a89984',
  gridLine: 'rgba(0,0,0,0.07)',
};

// Only the two fields the legacy custom-colour path is guaranteed to carry.
const SPARSE = { primary: '#7c3aed', surface: '#ffffff' };

function token(name) {
  return document.documentElement.style.getPropertyValue(name).trim();
}

beforeEach(() => {
  document.documentElement.removeAttribute('data-theme');
  document.documentElement.style.cssText = '';
  localStorage.clear();
});

afterEach(() => {
  document.documentElement.style.cssText = '';
  localStorage.clear();
});

describe('applyTheme derived tokens', () => {
  it('resolves the raised surface from the active palette', () => {
    applyTheme(RICH);
    expect(token('--color-surface-raised')).not.toBe('');
    expect(token('--color-surface-raised')).not.toBe('#32302f');
    expect(relativeLuminance(token('--color-surface-raised'))).toBeGreaterThan(
      relativeLuminance('#3c3836')
    );
  });

  it('gives a bright primary a dark foreground', () => {
    applyTheme(RICH);
    expect(token('--color-primary-fg')).toBe('#000000');
  });

  it('sets all four status tokens', () => {
    applyTheme(RICH);
    for (const name of ['--color-success', '--color-warning', '--color-danger', '--color-info']) {
      expect(token(name)).toMatch(/^#[0-9a-f]{6}$/i);
    }
  });

  it('picks light-mode status colours for a light surface', () => {
    applyTheme(RICH);
    const darkDanger = token('--color-danger');
    applyTheme({ ...RICH, surface: '#ffffff', background: '#f8f8f8', text: '#1d2021' });
    expect(token('--color-danger')).not.toBe(darkDanger);
  });

  it('clears stale properties when moving to a sparser palette', () => {
    // The bug plan 00 names: `if (variant.x)` means an absent field keeps the
    // PREVIOUS theme's value, so a custom two-colour palette used to inherit
    // Cyberpunk's borders and text.
    applyTheme(RICH);
    expect(token('--accent-1')).toBe('#ff2d95');
    applyTheme(SPARSE);
    expect(token('--accent-1')).toBe('');
    expect(token('--color-text')).toBe('');
  });

  it('still derives raised surface and status from a sparse palette', () => {
    applyTheme(SPARSE);
    expect(token('--color-surface-raised')).not.toBe('');
    expect(token('--color-primary-fg')).toBe('#ffffff');
    expect(token('--color-success')).not.toBe('');
  });

  it('honours the light variant of a dark/light preset pair', () => {
    document.documentElement.setAttribute('data-theme', 'light');
    applyTheme({ dark: RICH, light: { ...RICH, surface: '#ffffff' } });
    expect(relativeLuminance(token('--color-surface-raised'))).toBeLessThan(
      relativeLuminance('#ffffff')
    );
  });

  it('does nothing and throws nothing when handed no variant', () => {
    expect(() => applyTheme(null)).not.toThrow();
    expect(token('--color-surface-raised')).toBe('');
  });

  it('still persists the preset key for the cold-load pre-apply', () => {
    applyTheme(RICH, 'gruvbox');
    expect(localStorage.getItem('cb-theme-preset')).toBe('gruvbox');
  });
});
