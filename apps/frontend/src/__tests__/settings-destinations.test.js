import { describe, expect, it } from 'vitest';
import {
  LEGACY_SECTION_TO_TAB,
  SETTINGS_TABS,
  allowedSettingsTabs,
  normalizeSettingsPath,
  resolveSettingsTab,
  settingsTabMatches,
  settingsDestinations,
} from '../data/settingsDestinations';

const ADMIN = { role: 'admin' };
const EDITOR = { role: 'editor' };
const VIEWER = { role: 'viewer' };

describe('allowedSettingsTabs', () => {
  it('gives an admin every tab', () => {
    expect(allowedSettingsTabs(ADMIN).map((t) => t.id)).toEqual(SETTINGS_TABS.map((t) => t.id));
  });

  it('narrows a non-admin to Integrations, matching SettingsPage', () => {
    // SettingsPage.jsx:54 is the authority. Parent access to /settings does not
    // imply access to every tab, and the navigator must not advertise more.
    expect(allowedSettingsTabs(EDITOR).map((t) => t.id)).toEqual(['integrations']);
  });

  it('gives a viewer nothing, because /settings is editor-guarded', () => {
    expect(allowedSettingsTabs(VIEWER)).toEqual([]);
  });

  it('gives an anonymous caller nothing', () => {
    expect(allowedSettingsTabs(null)).toEqual([]);
  });
});

describe('settingsDestinations', () => {
  it('emits ?tab= links, never the palette stale ?section=', () => {
    for (const dest of settingsDestinations(ADMIN)) {
      expect(dest.path).toMatch(/^\/settings\?tab=[a-z-]+$/);
    }
  });

  it('has no Experimental destination', () => {
    // The former palette offered "Settings: Experimental" pointing at
    // ?section=experimental. No such tab exists in SETTINGS_TABS.
    const ids = settingsDestinations(ADMIN).map((d) => d.id);
    expect(ids).not.toContain('settings:experimental');
  });

  it('routes the old keyword labels to their real owners', () => {
    const byId = Object.fromEntries(settingsDestinations(ADMIN).map((d) => [d.id, d]));
    expect(byId['settings:appearance'].keywords).toContain('timezone');
    expect(byId['settings:appearance'].keywords).toContain('branding');
    expect(byId['settings:appearance'].keywords).toContain('icons');
    expect(byId['settings:resources'].keywords).toContain('categories');
    expect(byId['settings:resources'].keywords).toContain('environments');
    expect(byId['settings:resources'].keywords).toContain('locations');
    expect(byId['settings:security'].keywords).toContain('authentication');
    expect(byId['settings:integrations'].keywords).toContain('docker');
    expect(byId['settings:system'].keywords).toContain('backup');
  });

  it('respects the same narrowing as allowedSettingsTabs', () => {
    expect(settingsDestinations(EDITOR).map((d) => d.id)).toEqual(['settings:integrations']);
    expect(settingsDestinations(VIEWER)).toEqual([]);
  });

  it('uses stable ids a pin can be stored against', () => {
    const first = settingsDestinations(ADMIN);
    const second = settingsDestinations(ADMIN);
    expect(first.map((d) => d.id)).toEqual(second.map((d) => d.id));
  });
});

describe('normalizeSettingsPath', () => {
  it('rewrites every legacy section link the palette shipped', () => {
    expect(normalizeSettingsPath('/settings?section=appearance')).toBe('/settings?tab=appearance');
    expect(normalizeSettingsPath('/settings?section=defaults')).toBe('/settings?tab=general');
    expect(normalizeSettingsPath('/settings?section=icons')).toBe('/settings?tab=appearance');
    expect(normalizeSettingsPath('/settings?section=categories')).toBe('/settings?tab=resources');
    expect(normalizeSettingsPath('/settings?section=environments')).toBe('/settings?tab=resources');
    expect(normalizeSettingsPath('/settings?section=auth')).toBe('/settings?tab=security');
  });

  it('drops a section it cannot map rather than inventing a tab', () => {
    expect(normalizeSettingsPath('/settings?section=experimental')).toBe('/settings');
  });

  it('leaves a correct link and an unrelated path alone', () => {
    expect(normalizeSettingsPath('/settings?tab=system')).toBe('/settings?tab=system');
    expect(normalizeSettingsPath('/hardware')).toBe('/hardware');
  });

  it('maps every legacy key to a tab that actually exists', () => {
    const real = new Set(SETTINGS_TABS.map((t) => t.id));
    for (const tab of Object.values(LEGACY_SECTION_TO_TAB)) {
      expect(real.has(tab)).toBe(true);
    }
  });
});

describe('resolveSettingsTab', () => {
  it('normalizes a direct legacy bookmark for an allowed tab', () => {
    const resolved = resolveSettingsTab(new URLSearchParams('section=timezone'), ADMIN);
    expect(resolved.tabId).toBe('appearance');
    expect(resolved.canonicalParams.toString()).toBe('tab=appearance');
    expect(resolved.shouldReplace).toBe(true);
  });

  it('keeps an explicit canonical tab and unrelated query state', () => {
    const resolved = resolveSettingsTab(new URLSearchParams('tab=system&focus=backup'), ADMIN);
    expect(resolved.tabId).toBe('system');
    expect(resolved.canonicalParams.toString()).toBe('tab=system&focus=backup');
    expect(resolved.shouldReplace).toBe(false);
  });

  it('falls back without rendering an invalid or forbidden tab', () => {
    expect(resolveSettingsTab(new URLSearchParams('tab=experimental'), ADMIN).tabId).toBe(
      'general'
    );
    expect(resolveSettingsTab(new URLSearchParams('tab=security'), EDITOR).tabId).toBe(
      'integrations'
    );
    expect(resolveSettingsTab(new URLSearchParams('tab=general'), VIEWER).tabId).toBeNull();
  });
});

describe('settingsTabMatches', () => {
  const byId = Object.fromEntries(SETTINGS_TABS.map((tab) => [tab.id, tab]));

  it('uses the shared labels, descriptions, and keyword registry', () => {
    expect(settingsTabMatches(byId.appearance, 'timezone')).toBe(true);
    expect(settingsTabMatches(byId['device-roles'], 'topology')).toBe(true);
    expect(settingsTabMatches(byId.security, 'ssl')).toBe(false);
  });
});
