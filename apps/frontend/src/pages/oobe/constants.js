import { THEME_PRESETS } from '../../theme/presets';

/**
 * Values the wizard's steps share with the page that drives them.
 *
 * These were module-level in `OOBEWizardPage` and are read by the steps that
 * moved out of it, so they live beside those steps rather than being exported
 * back out of the page — a step importing from the page it is rendered by is a
 * cycle waiting to happen.
 */

export const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit', test: (p) => /\d/.test(p) },
  { label: 'One special character', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

export const PRESET_KEYS = Object.keys(THEME_PRESETS);

/** Derive a human-readable city name from an IANA timezone string. */
export function timezoneToCity(tz) {
  if (!tz || tz === 'UTC' || tz === 'GMT') return '';
  const parts = tz.split('/');
  return parts[parts.length - 1].replaceAll('_', ' ');
}
