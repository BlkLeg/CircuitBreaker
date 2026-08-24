import { describe, expect, it } from 'vitest';
import { normalizeMacPrefix, isValidMacPrefix, formatMacPrefix } from '../utils/validation';

describe('normalizeMacPrefix', () => {
  it('strips colons and uppercases', () => {
    expect(normalizeMacPrefix('b8:27:eb')).toBe('B827EB');
  });

  it('strips hyphens and dots', () => {
    expect(normalizeMacPrefix('b8-27-eb')).toBe('B827EB');
    expect(normalizeMacPrefix('b827.eb')).toBe('B827EB');
  });

  it('truncates a full MAC to its OUI', () => {
    expect(normalizeMacPrefix('B8:27:EB:12:34:56')).toBe('B827EB');
  });

  it('trims surrounding whitespace', () => {
    expect(normalizeMacPrefix('  001122  ')).toBe('001122');
  });

  it('returns empty string for nullish input', () => {
    expect(normalizeMacPrefix('')).toBe('');
    expect(normalizeMacPrefix(null)).toBe('');
    expect(normalizeMacPrefix(undefined)).toBe('');
  });
});

describe('isValidMacPrefix', () => {
  it('accepts six hex characters in any separator style', () => {
    expect(isValidMacPrefix('001122')).toBe(true);
    expect(isValidMacPrefix('b8:27:eb')).toBe(true);
  });

  it('rejects too few characters', () => {
    expect(isValidMacPrefix('0011')).toBe(false);
  });

  it('rejects non-hex characters', () => {
    expect(isValidMacPrefix('00zz22')).toBe(false);
  });

  it('rejects empty input', () => {
    expect(isValidMacPrefix('')).toBe(false);
  });
});

describe('formatMacPrefix', () => {
  it('inserts colons every two characters', () => {
    expect(formatMacPrefix('001122')).toBe('00:11:22');
  });

  it('returns the input unchanged when it is not six hex characters', () => {
    expect(formatMacPrefix('nonsense')).toBe('nonsense');
    expect(formatMacPrefix('')).toBe('');
  });
});
