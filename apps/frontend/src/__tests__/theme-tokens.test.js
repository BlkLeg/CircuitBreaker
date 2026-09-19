import { describe, expect, it } from 'vitest';
import {
  DERIVED_TOKEN_NAMES,
  STATUS_DEFAULTS,
  contrastRatio,
  contrastingForeground,
  deriveReadableText,
  deriveSurfaceRaised,
  isLightColor,
  mixHex,
  relativeLuminance,
} from '../theme/tokens';
import { THEME_PRESETS } from '../theme/presets';

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

describe('contrastRatio', () => {
  it('brackets the WCAG range', () => {
    expect(contrastRatio('#000000', '#ffffff')).toBeCloseTo(21, 2);
    expect(contrastRatio('#777777', '#777777')).toBeCloseTo(1, 5);
  });

  it('does not care which way round the pair is given', () => {
    expect(contrastRatio('#123456', '#fedcba')).toBeCloseTo(
      contrastRatio('#fedcba', '#123456'),
      10
    );
  });
});

describe('deriveReadableText', () => {
  it('returns a colour that already passes, untouched', () => {
    // The palette's hue is kept wherever it was legible to begin with.
    expect(deriveReadableText('#ffffff', ['#000000'])).toBe('#ffffff');
    expect(deriveReadableText('#0f172a', ['#ffffff'])).toBe('#0f172a');
  });

  it('lifts unreadable text off a dark surface until it clears AA', () => {
    const lifted = deriveReadableText('#75715e', ['#272822']);

    expect(lifted).not.toBe('#75715e');
    expect(contrastRatio(lifted, '#272822')).toBeGreaterThanOrEqual(4.5);
  });

  it('darkens unreadable text on a light surface instead of lightening it', () => {
    const darkened = deriveReadableText('#c0c0c0', ['#ffffff']);

    expect(relativeLuminance(darkened)).toBeLessThan(relativeLuminance('#c0c0c0'));
    expect(contrastRatio(darkened, '#ffffff')).toBeGreaterThanOrEqual(4.5);
  });

  it('clears every surface it is given, not just the first', () => {
    const surfaces = ['#0a0e1a', '#020617', '#10162a'];
    const readable = deriveReadableText('#4a6a7a', surfaces);

    for (const surface of surfaces) {
      expect(contrastRatio(readable, surface)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('moves as little as it can get away with', () => {
    // A floor, not a repaint: the result should not overshoot to pure white
    // when a small nudge clears the bar.
    const nudged = deriveReadableText('#6272a4', ['#282a36']);

    expect(nudged).not.toBe('#ffffff');
    expect(contrastRatio(nudged, '#282a36')).toBeGreaterThanOrEqual(4.5);
  });

  it('leaves input it cannot parse alone', () => {
    expect(deriveReadableText('not-a-color', ['#000000'])).toBe('not-a-color');
    expect(deriveReadableText('#ffffff', [])).toBe('#ffffff');
  });
});

describe('every shipped preset is readable on its own surfaces', () => {
  // Measured without this floor: 20 of 28 preset/mode pairs put muted
  // text below 4.5:1 against the surface it sits on, 8 below 3:1, and
  // monokai/dark at 1.74:1 — in the DOM and invisible. The navigator showed it
  // worst because it is almost entirely secondary text, but nothing about it
  // was navigator-specific.
  const cases = [];
  for (const [name, preset] of Object.entries(THEME_PRESETS)) {
    for (const mode of ['dark', 'light']) {
      if (preset[mode]?.surface) cases.push([`${name}/${mode}`, preset[mode]]);
    }
  }

  it.each(cases)('%s keeps both text tokens at AA', (_id, variant) => {
    const surfaces = [
      variant.surface,
      variant.background,
      variant.surfaceAlt,
      deriveSurfaceRaised(variant.surface),
    ].filter(Boolean);

    for (const token of [variant.text, variant.textMuted].filter(Boolean)) {
      const readable = deriveReadableText(token, surfaces);
      for (const surface of surfaces) {
        expect(contrastRatio(readable, surface)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });
});
