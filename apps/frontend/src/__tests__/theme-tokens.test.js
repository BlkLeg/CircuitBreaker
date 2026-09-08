import { describe, expect, it } from 'vitest';
import {
  DERIVED_TOKEN_NAMES,
  STATUS_DEFAULTS,
  contrastingForeground,
  deriveSurfaceRaised,
  isLightColor,
  mixHex,
  relativeLuminance,
} from '../theme/tokens';

describe('relativeLuminance', () => {
  it('brackets black and white', () => {
    expect(relativeLuminance('#000000')).toBeCloseTo(0, 5);
    expect(relativeLuminance('#ffffff')).toBeCloseTo(1, 5);
  });

  it('is 0 for input it cannot parse, rather than NaN', () => {
    // A NaN here would silently poison every downstream comparison: NaN > 0.5
    // is false, so a broken custom color would quietly be treated as dark.
    expect(relativeLuminance('not-a-color')).toBe(0);
    expect(relativeLuminance('')).toBe(0);
    expect(relativeLuminance(null)).toBe(0);
  });
});

describe('isLightColor', () => {
  it('separates the Gruvbox dark surface from a white one', () => {
    expect(isLightColor('#3c3836')).toBe(false);
    expect(isLightColor('#ffffff')).toBe(true);
  });
});

describe('contrastingForeground', () => {
  it('picks black on a bright primary and white on a dark one', () => {
    // #b8bb26 is the Gruvbox green used as a primary; white text on it is the
    // exact failure plan 00 calls out.
    expect(contrastingForeground('#b8bb26')).toBe('#000000');
    expect(contrastingForeground('#7c3aed')).toBe('#ffffff');
  });

  it("decides at the WCAG crossover, not at isLightColor's midpoint", () => {
    // #b8bb26 has luminance 0.459 -- BELOW 0.5, so isLightColor calls it dark.
    // Reusing that threshold here would put white text on Gruvbox green, which
    // is the bug this function exists to prevent. Black wins from 0.1791 up.
    expect(isLightColor('#b8bb26')).toBe(false);
    expect(contrastingForeground('#b8bb26')).toBe('#000000');
    // #00f5ff (Cyberpunk primary, luminance 0.725) is light by both measures.
    expect(contrastingForeground('#00f5ff')).toBe('#000000');
    // #3c3836 (luminance 0.041) is dark by both.
    expect(contrastingForeground('#3c3836')).toBe('#ffffff');
  });
});

describe('mixHex', () => {
  it('returns the endpoints at 0 and 100', () => {
    expect(mixHex('#3c3836', '#ffffff', 0)).toBe('#3c3836');
    expect(mixHex('#3c3836', '#ffffff', 100)).toBe('#ffffff');
  });

  it('blends channel-wise at 50', () => {
    expect(mixHex('#000000', '#ffffff', 50)).toBe('#808080');
  });
});

describe('deriveSurfaceRaised', () => {
  it('lifts a dark surface toward white', () => {
    const raised = deriveSurfaceRaised('#3c3836');
    expect(relativeLuminance(raised)).toBeGreaterThan(relativeLuminance('#3c3836'));
  });

  it('drops a light surface toward black', () => {
    const raised = deriveSurfaceRaised('#ffffff');
    expect(relativeLuminance(raised)).toBeLessThan(relativeLuminance('#ffffff'));
  });

  it('always moves, so a raised panel is never invisible against its parent', () => {
    for (const surface of ['#000000', '#ffffff', '#3c3836', '#0a0e1a', '#f1f5f9']) {
      expect(deriveSurfaceRaised(surface)).not.toBe(surface);
    }
  });
});

describe('STATUS_DEFAULTS', () => {
  it('supplies all four semantic colors for both modes', () => {
    for (const mode of ['dark', 'light']) {
      for (const name of ['success', 'warning', 'danger', 'info']) {
        expect(STATUS_DEFAULTS[mode][name]).toMatch(/^#[0-9a-f]{6}$/i);
      }
    }
  });

  it('uses different values per mode, which is the whole point', () => {
    expect(STATUS_DEFAULTS.dark.success).not.toBe(STATUS_DEFAULTS.light.success);
  });
});

describe('DERIVED_TOKEN_NAMES', () => {
  it('names every token applyTheme is responsible for, with no duplicates', () => {
    expect(new Set(DERIVED_TOKEN_NAMES).size).toBe(DERIVED_TOKEN_NAMES.length);
    for (const token of DERIVED_TOKEN_NAMES) {
      expect(token.startsWith('--')).toBe(true);
    }
    expect(DERIVED_TOKEN_NAMES).toContain('--color-surface-raised');
    expect(DERIVED_TOKEN_NAMES).toContain('--color-primary-fg');
    expect(DERIVED_TOKEN_NAMES).toContain('--color-success');
  });
});
