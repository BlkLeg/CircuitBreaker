import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { SETTINGS_TABS } from '../components/settings/SettingsNav.jsx';
import { NAV_MAP } from '../data/navigation';

// Vitest serves modules through Vite, so import.meta.url is not a file: URL and
// new URL(rel, import.meta.url) cannot be handed to readFileSync. process.cwd()
// is the Vitest project root — apps/frontend, where vitest.config.ts lives.
const srcFile = (rel) => resolve(process.cwd(), 'src', rel);

describe('user administration has one address', () => {
  it('is not a settings tab', () => {
    expect(SETTINGS_TABS.map((t) => t.id)).not.toContain('users');
  });

  it('is a Govern nav destination', () => {
    expect(NAV_MAP['/admin/users'].label).toBe('Users');
  });

  it('is not rendered inside SettingsPage', () => {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- reads a source file in this repo
    const src = readFileSync(srcFile('pages/SettingsPage.jsx'), 'utf8');
    expect(src).not.toContain('AdminUsersPage');
  });

  it('leaves the other nine tabs alone', () => {
    expect(SETTINGS_TABS.map((t) => t.id)).toEqual([
      'general',
      'appearance',
      'resources',
      'device-roles',
      'connectivity',
      'integrations',
      'kb',
      'security',
      'system',
    ]);
  });
});
