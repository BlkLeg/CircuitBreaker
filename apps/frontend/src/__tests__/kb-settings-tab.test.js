import { describe, expect, it } from 'vitest';
import { SETTINGS_TABS } from '../components/settings/SettingsNav.jsx';

describe('Knowledge Base settings tab', () => {
  it('is registered', () => {
    expect(SETTINGS_TABS.map((t) => t.id)).toContain('kb');
  });

  it('is admin-only, matching require_role("admin") on every /kb route', () => {
    const tab = SETTINGS_TABS.find((t) => t.id === 'kb');
    expect(tab.adminOnly).toBe(true);
  });

  it('sits next to the other discovery-adjacent configuration', () => {
    const ids = SETTINGS_TABS.map((t) => t.id);
    expect(ids.indexOf('kb')).toBeGreaterThan(ids.indexOf('connectivity'));
  });

  it('has a label and description', () => {
    const tab = SETTINGS_TABS.find((t) => t.id === 'kb');
    expect(tab.label).toBe('Knowledge Base');
    expect(typeof tab.description).toBe('string');
    expect(tab.description.length).toBeGreaterThan(0);
  });
});
