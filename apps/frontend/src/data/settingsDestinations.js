import {
  BookOpen,
  Database,
  Globe,
  Layers,
  Palette,
  Plug,
  Server,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { canEdit, isAdmin } from '../utils/rbac';

export const SETTINGS_TABS = [
  {
    id: 'general',
    label: 'General',
    icon: Settings,
    description: 'Basic app configuration and defaults.',
  },
  {
    id: 'appearance',
    label: 'Appearance',
    icon: Palette,
    description: 'Themes, branding, and visual preferences.',
  },
  {
    id: 'resources',
    label: 'Resources',
    icon: Layers,
    description: 'Manage environments, categories, and locations.',
  },
  {
    id: 'device-roles',
    label: 'Device Roles',
    icon: Server,
    description: 'Hardware classification and topology ranking.',
  },
  {
    id: 'connectivity',
    label: 'Connectivity',
    icon: Globe,
    description: 'Auto-discovery and API settings.',
  },
  {
    id: 'integrations',
    label: 'Integrations',
    icon: Plug,
    description: 'NATS, Docker, and external service controls.',
  },
  {
    id: 'kb',
    label: 'Knowledge Base',
    icon: BookOpen,
    description: 'Vendor and hostname hints that discovery uses for naming.',
    adminOnly: true,
  },
  {
    id: 'security',
    label: 'Security',
    icon: ShieldCheck,
    description: 'Authentication and session management.',
  },
  {
    id: 'system',
    label: 'System',
    icon: Database,
    description: 'Backups, maintenance, and advanced tools.',
  },
];

/**
 * The settings half of the navigation registry.
 *
 * The non-admin policy must live here, not privately in SettingsPage with the
 * palette guessing at it through a canEdit check and its own hardcoded
 * `?section=` list. Two copies disagree: the palette offers an editor eight
 * settings deep-links, seven of which the page refuses to render. One exported
 * policy, two consumers.
 *
 * SettingsNav reads this file. Data never imports a rendered component.
 */

/**
 * Search keywords per tab, so "timezone" finds Appearance.
 *
 * Each entry was checked against its real owner rather than copied from the
 * palette's labels: `icons` and `timezone` live in AppearanceSection, not in a
 * tab of their own, and `defaults` is General.
 */
export const SETTINGS_TAB_KEYWORDS = {
  general: ['defaults', 'default environment', 'hints', 'api', 'external'],
  appearance: [
    'theme',
    'timezone',
    'icons',
    'vendors',
    'branding',
    'logo',
    'fonts',
    'widgets',
    'dock',
  ],
  resources: ['categories', 'environments', 'locations'],
  'device-roles': ['roles', 'device', 'hardware', 'classification', 'topology', 'rank'],
  connectivity: ['discovery', 'listener', 'mdns', 'ssdp', 'arp', 'nmap', 'snmp', 'map'],
  integrations: [
    'docker',
    'container',
    'nats',
    'opnsense',
    'proxmox',
    'smtp',
    'cve',
    'vulnerability',
    'realtime',
    'hypervisor',
    'vm',
  ],
  kb: ['knowledge base', 'hints', 'hostname', 'vendor'],
  security: [
    'authentication',
    'auth',
    'login',
    'sessions',
    'registration',
    'rate limit',
    'password',
    'audit',
  ],
  system: [
    'backup',
    'restore',
    'import',
    'export',
    'transfer',
    'maintenance',
    'updates',
    'reset',
    'clear',
  ],
};

export function settingsTabMatches(tab, query) {
  const needle = String(query ?? '')
    .trim()
    .toLowerCase();
  if (!needle) return true;
  if (tab.label.toLowerCase().includes(needle)) return true;
  if (tab.description.toLowerCase().includes(needle)) return true;
  return (SETTINGS_TAB_KEYWORDS[tab.id] ?? []).some((keyword) => keyword.includes(needle));
}

/**
 * The single settings-tab visibility policy.
 *
 * Two gates, in order: /settings itself is editor-guarded (routeGuards.js), and
 * within it only an admin sees more than Integrations (SettingsPage.jsx:54).
 * A viewer therefore gets an empty list, not "everything the route allows".
 */
export function allowedSettingsTabs(user) {
  if (!canEdit(user)) return [];
  if (isAdmin(user)) return SETTINGS_TABS.slice();
  return SETTINGS_TABS.filter((tab) => tab.id === 'integrations');
}

/** The allowed tabs as navigator destinations. `id` is stable enough to pin. */
export function settingsDestinations(user) {
  return allowedSettingsTabs(user).map((tab) => ({
    id: `settings:${tab.id}`,
    label: tab.label,
    description: tab.description,
    path: `/settings?tab=${tab.id}`,
    icon: tab.icon,

    keywords: SETTINGS_TAB_KEYWORDS[tab.id] ?? [],
  }));
}

/**
 * Historical `?section=` values → real tab ids.
 *
 * Only links that were genuinely reachable at some point are listed. The
 * palette's `experimental` is absent on purpose: SETTINGS_TABS has never had
 * such a tab, so there is no valid historical link to preserve, and inventing
 * one would be the "Experimental section from a stale command label" plan 01
 * explicitly forbids.
 */
export const LEGACY_SECTION_TO_TAB = {
  appearance: 'appearance',
  defaults: 'general',
  general: 'general',
  icons: 'appearance',
  timezone: 'appearance',
  categories: 'resources',
  environments: 'resources',
  locations: 'resources',
  auth: 'security',
  security: 'security',
  system: 'system',
  integrations: 'integrations',
};

/** Resolve the rendered tab and its canonical, permission-safe query string. */
export function resolveSettingsTab(searchParams, user) {
  const params = new URLSearchParams(searchParams);
  const allowed = allowedSettingsTabs(user);
  const fallback = allowed[0]?.id ?? null;
  const requested = params.get('tab');
  const section = params.get('section');
  const legacy =
    section && Object.hasOwn(LEGACY_SECTION_TO_TAB, section)
      ? // eslint-disable-next-line security/detect-object-injection -- own-property checked above
        LEGACY_SECTION_TO_TAB[section]
      : null;
  const candidate = requested || legacy;
  const tabId = allowed.some((tab) => tab.id === candidate) ? candidate : fallback;

  const canonicalParams = new URLSearchParams(params);
  canonicalParams.delete('section');
  if (tabId) canonicalParams.set('tab', tabId);
  else canonicalParams.delete('tab');

  return {
    tabId,
    canonicalParams,
    shouldReplace: canonicalParams.toString() !== params.toString(),
  };
}

/**
 * Rewrite a legacy settings link. Bookmarks that predate the `?tab=` rename
 * keep working; an unmappable section lands on Settings rather than on a tab
 * that does not exist.
 */
export function normalizeSettingsPath(path) {
  if (typeof path !== 'string' || !path.startsWith('/settings')) return path;
  const queryStart = path.indexOf('?');
  if (queryStart === -1) return path;
  const params = new URLSearchParams(path.slice(queryStart + 1));
  const section = params.get('section');
  if (!section) return path;
  const tab = Object.hasOwn(LEGACY_SECTION_TO_TAB, section)
    ? // eslint-disable-next-line security/detect-object-injection -- own-property checked above
      LEGACY_SECTION_TO_TAB[section]
    : null;
  return tab ? `/settings?tab=${tab}` : '/settings';
}
