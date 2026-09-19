import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

/**
 * U4's wiring guarantees, exercised through the real AppInner — the unit that
 * owns navigator state, the Ctrl/Cmd+K listener, activation, and recent
 * recording. Everything above it (bootstrap, auth gating) is deliberately out
 * of scope; everything below it is stubbed only where jsdom cannot honestly
 * run it (page chunks, framer-motion timing, live streams).
 *
 * Where each U4 requirement is held:
 *   - "exactly one Navigate control, no Routes/palette control"  -> here + header-nav-menu
 *   - "header click and Ctrl/Cmd+K open exactly one dialog"      -> here
 *   - "modal handoff order is close then open"                   -> here
 *   - "an unmounted location is not recent"                      -> here (a route whose
 *     element suspends forever keeps the Suspense boundary — and the mount
 *     signal inside it — from committing)
 *   - "dock/navigator/registry parity for all roles"             -> nav-surface-parity
 *   - "unmount clears state without deleting persisted shortcuts"-> here
 *   - "navigation-timing wedge semantics unchanged"              -> here (a never-mounting
 *     route keeps `pending: true` forever) + navigation-timing.test.jsx
 */

const mockAuth = {
  user: { id: 1, email: 'admin@example.test', role: 'admin' },
  isMasquerade: false,
  log: [],
};

vi.mock('framer-motion', () => ({
  // Passthrough, per this suite's established pattern (wifi-overlay.test.jsx):
  // the keyed motion.div remounts synchronously on navigation, so the mount
  // signal's timing is deterministic. The exit-animation semantics that
  // framer-motion adds are guarded by navigation-timing.test.jsx's own harness.
  AnimatePresence: ({ children }) => <>{children}</>,
  motion: {
    div: ({ children, initial, animate, exit, transition, ...props }) => (
      <div {...props}>{children}</div>
    ),
  },
}));

vi.mock('react-i18next', () => ({
  I18nextProvider: ({ children }) => <>{children}</>,
  useTranslation: () => ({ t: (key, opts) => opts?.defaultValue ?? key }),
}));

vi.mock('../i18n', () => ({ default: {} }));

// A real context, not a bare mock: modal open/close must re-render AppInner,
// which reads authModalOpen/profileModalOpen from useAuth every render.
vi.mock('../context/AuthContext.jsx', async () => {
  const ReactModule = await import('react');
  const ctx = ReactModule.createContext(null);
  return {
    AuthProvider: ({ children }) => {
      const [authModalOpen, setAuthModalOpen] = ReactModule.useState(false);
      const [profileModalOpen, setProfileModalOpen] = ReactModule.useState(false);
      const value = {
        authModalOpen,
        profileModalOpen,
        setAuthModalOpen,
        setProfileModalOpen,
        isAuthenticated: true,
        user: mockAuth.user,
        isMasquerade: mockAuth.isMasquerade,
        openAuthModal: () => {
          mockAuth.log.push('auth-open');
          setAuthModalOpen(true);
        },
        openProfileModal: () => {
          mockAuth.log.push('profile-open');
          setProfileModalOpen(true);
        },
      };
      return <ctx.Provider value={value}>{children}</ctx.Provider>;
    },
    useAuth: () => ReactModule.useContext(ctx),
  };
});

vi.mock('../context/SettingsContext', () => ({
  SettingsProvider: ({ children }) => <>{children}</>,
  useSettings: () => ({ settings: { theme: 'dark' }, reloadSettings: vi.fn() }),
}));

vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('../hooks/useDiscoveryStream.js', () => ({
  useDiscoveryStream: () => ({ pendingCount: 0, connected: true, wsStatus: 'connected' }),
  discoveryEmitter: { on: vi.fn(), off: vi.fn() },
}));
vi.mock('../lib/sseClient.js', () => ({
  connectSSE: vi.fn(),
  disconnectSSE: vi.fn(),
  isSSEConnected: () => true,
  sseEmitter: { on: vi.fn(), off: vi.fn() },
}));

vi.mock('../components/ServerLifecycleBanner.jsx', () => ({
  default: ({ children }) => <>{children}</>,
}));
vi.mock('../components/MacOSDOCK.jsx', () => ({ default: () => null }));
vi.mock('../components/UpdateBanner.jsx', () => ({ default: () => null }));
vi.mock('../components/common/RecentChanges.jsx', () => ({ default: () => null }));
vi.mock('../components/ThemePalette', () => ({ default: () => null }));
vi.mock('../components/HeaderWidgets.jsx', () => ({ default: () => null }));
vi.mock('../components/auth/UserAvatar.jsx', () => ({ default: () => null }));

// The auth dialogs are mock components because what is under test is the
// handoff *between* navigator and dialog, not the dialogs themselves. The
// Profile mock records whether the navigator overlay was already gone when
// the dialog mounted — the observable half of "close then open".
vi.mock('../components/auth/AuthModal.jsx', () => ({
  default: ({ isOpen }) =>
    isOpen ? (
      <div role="dialog" aria-label="Sign in">
        Sign-in dialog
      </div>
    ) : null,
}));
vi.mock('../components/auth/ProfileModal.jsx', () => ({
  default: function ProfileModalMock({ isOpen }) {
    React.useEffect(() => {
      if (isOpen) {
        mockAuth.log.push([
          'profile-mounted',
          document.querySelector('.navigator-overlay') === null,
        ]);
      }
    }, [isOpen]);
    return isOpen ? (
      <div role="dialog" aria-label="Profile">
        Profile dialog
      </div>
    ) : null;
  },
}));

// LoadingScreen pulls in lottie-web, which cannot initialise under jsdom's
// canvas stub — same stand-in as discovery-page-fleet.test.jsx, keeping the
// status role the Suspense fallback really exposes.
vi.mock('../components/common/LoadingScreen.jsx', () => ({
  default: () => <div role="status">Loading…</div>,
}));

// Eager page imports App.jsx makes at module scope.
vi.mock('../pages/MiscPage', () => ({ default: () => <div>Misc page</div> }));
vi.mock('../pages/LoginPage', () => ({ default: () => <div>Login page</div> }));
vi.mock('../pages/OOBEWizardPage', () => ({ default: () => <div>OOBE page</div> }));

// The two pages these tests navigate between, as light stubs.
vi.mock('../pages/HardwarePage', () => ({ default: () => <div>Hardware page</div> }));
vi.mock('../pages/ServicesPage', () => ({ default: () => <div>Services page</div> }));

// A page whose element suspends forever: the exact shape of a navigation that
// never mounts. The keyed route div — and the mount signal inside it — never
// commits, so /logs must never become a recent and its nav entry must stay
// pending forever. This is the wedge, on purpose.
vi.mock('../pages/LogsPage', () => ({
  default: function LogsPage() {
    const Never = React.lazy(() => new Promise(() => {}));
    return <Never />;
  },
}));

import { AppInner } from '../App';
import { useNavigationTiming } from '../hooks/useNavigationTiming';
import { getEntries, clearEntries } from '../lib/diagnosticsBuffer';
import { AuthProvider } from '../context/AuthContext.jsx';
import { ToastProvider } from '../components/common/Toast';

function TimingWatcher() {
  useNavigationTiming();
  return null;
}

/**
 * Mirrors App's <BrowserRouter useTransitions={false}>: without that prop
 * navigate() commits inside a startTransition that a jsdom test never flushes,
 * and every navigation in this suite reproduces the sticky-navigation wedge
 * instead of mounting the route. The prop is load bearing in production for
 * the same reason — see App.jsx.
 */
function Harness() {
  return (
    <MemoryRouter initialEntries={['/hardware']} useTransitions={false}>
      <ToastProvider>
        <AuthProvider>
          <TimingWatcher />
          <AppInner />
        </AuthProvider>
      </ToastProvider>
    </MemoryRouter>
  );
}

const RECENTS_KEY = (namespace) => `cb:nav:v1:${namespace}:recents`;
const PINS_KEY = (namespace) => `cb:nav:v1:${namespace}:pins`;

function readStoredList(key) {
  const raw = localStorage.getItem(key);
  if (!raw) return [];
  const parsed = JSON.parse(raw);
  return Array.isArray(parsed?.items) ? parsed.items : [];
}

function navigatorDialogs() {
  return screen.queryAllByRole('dialog', { name: 'Navigate' });
}

async function openViaShortcut() {
  fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
  await screen.findByRole('dialog', { name: 'Navigate' });
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  clearEntries();
  mockAuth.log.length = 0;
  mockAuth.user = { id: 1, email: 'admin@example.test', role: 'admin' };
  mockAuth.isMasquerade = false;
});

describe('navigator wiring in AppInner', () => {
  it('renders one Navigate control and no legacy Routes or palette control', () => {
    render(<Harness />);
    expect(screen.getAllByRole('button', { name: 'Open navigator' })).toHaveLength(1);
    expect(screen.queryByLabelText('Open route menu')).toBeNull();
    expect(screen.queryByLabelText('Open command palette')).toBeNull();
  });

  it('header click and Ctrl/Cmd+K drive exactly one dialog, and a second shortcut closes it', async () => {
    render(<Harness />);

    await screen.findByText('Hardware page');

    // Focus before the click, as a real browser does: the navigator snapshots
    // the opener at open, and jsdom's fireEvent.click never moves focus.
    const trigger = screen.getByRole('button', { name: 'Open navigator' });
    trigger.focus();
    fireEvent.click(trigger);
    await screen.findByRole('dialog', { name: 'Navigate' });
    expect(navigatorDialogs()).toHaveLength(1);
    // Focus lands via requestAnimationFrame on open — wait for it.
    await waitFor(() => expect(screen.getByRole('searchbox')).toHaveFocus());

    // Escape closes through the navigator itself and restores the opener.
    fireEvent.keyDown(navigatorDialogs()[0], { key: 'Escape' });
    await waitFor(() => expect(navigatorDialogs()).toHaveLength(0));
    expect(screen.getByRole('button', { name: 'Open navigator' })).toHaveFocus();

    // The shortcut opens the same single dialog.
    await openViaShortcut();
    expect(navigatorDialogs()).toHaveLength(1);

    // A second shortcut is a toggle, not a second overlay.
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await waitFor(() => expect(navigatorDialogs()).toHaveLength(0));

    // Meta+K is the macOS spelling of the same listener.
    await openViaShortcut();
    fireEvent.keyDown(window, { key: 'k', metaKey: true });
    await waitFor(() => expect(navigatorDialogs()).toHaveLength(0));
  });

  it('hands an action off to a modal only after the navigator has closed', async () => {
    render(<Harness />);
    await screen.findByText('Hardware page');

    await openViaShortcut();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'profile' } });
    // A result row's accessible name is label + description, so match on
    // the label prefix rather than the exact string.
    fireEvent.click(await screen.findByRole('button', { name: /^Profile/ }));
    await screen.findByRole('dialog', { name: 'Profile' });
    expect(navigatorDialogs()).toHaveLength(0);
    expect(mockAuth.log).toContain('profile-open');
    // At dialog mount the overlay was already gone: close happened first.
    expect(mockAuth.log.at(-1)).toEqual(['profile-mounted', true]);

    // The Login action reaches the same handoff.
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true });
    await screen.findByRole('dialog', { name: 'Navigate' });
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'login' } });
    fireEvent.click(await screen.findByRole('button', { name: /^Login/ }));
    await screen.findByRole('dialog', { name: 'Sign in' });
    expect(navigatorDialogs()).toHaveLength(0);
  });

  it('records a recent only after the route mounted, and keeps the wedge signal honest', async () => {
    render(<Harness />);
    await screen.findByText('Hardware page');

    // The initial route mounted, so it is a recent.
    await waitFor(() => expect(readStoredList(RECENTS_KEY('u:1'))).toContain('page:/hardware'));

    // Navigate to a route whose element never resolves: the location moves but
    // the route never mounts, so it must not be recorded — and the navigator
    // must still open, which is the recovery path out of exactly this state.
    await openViaShortcut();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'logs' } });
    fireEvent.click(await screen.findByRole('button', { name: /^Logs/ }));
    await screen.findByRole('status');
    expect(screen.queryByText('Logs page')).toBeNull();
    expect(readStoredList(RECENTS_KEY('u:1'))).not.toContain('page:/logs');

    // Navigate on to a resolvable route through the still-usable navigator.
    await openViaShortcut();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'services' } });
    fireEvent.click(await screen.findByRole('button', { name: /^Services/ }));
    await screen.findByText('Services page');

    const recents = readStoredList(RECENTS_KEY('u:1'));
    expect(recents).toEqual(['page:/services', 'page:/hardware']);
    expect(recents).not.toContain('page:/logs');

    // Wedge semantics unchanged: /logs stays pending forever, /services closed.
    const navEntries = getEntries().filter((entry) => entry.kind === 'nav');
    const byPath = Object.fromEntries(navEntries.map((entry) => [entry.path, entry]));
    expect(byPath['/logs'].pending).toBe(true);
    expect(byPath['/services'].pending).toBe(false);
    expect(byPath['/hardware'].pending).toBe(false);
  });

  it('unmount clears the open navigator without deleting persisted shortcuts, and namespaces stay isolated', async () => {
    localStorage.setItem(PINS_KEY('u:1'), JSON.stringify({ v: 1, items: ['page:/hardware'] }));

    const first = render(<Harness />);
    await screen.findByText('Hardware page');
    fireEvent.click(screen.getByRole('button', { name: 'Open navigator' }));
    await screen.findByRole('dialog', { name: 'Navigate' });
    expect(screen.getByRole('button', { name: 'Hardware', exact: true })).toBeInTheDocument();

    // Unmount (logout does this in the real app): no overlay remains, and the
    // returning user's persisted pin survives in its namespaced key.
    first.unmount();
    expect(document.querySelector('.navigator-overlay')).toBeNull();
    expect(readStoredList(PINS_KEY('u:1'))).toEqual(['page:/hardware']);

    // A different user on the same browser sees none of it.
    mockAuth.user = { id: 2, email: 'other@example.test', role: 'admin' };
    render(<Harness />);
    await screen.findByText('Hardware page');
    fireEvent.click(screen.getByRole('button', { name: 'Open navigator' }));
    await screen.findByRole('dialog', { name: 'Navigate' });
    expect(
      screen.getByText('Use a pin button to keep pages here. Your dock stays unchanged.')
    ).toBeInTheDocument();
    expect(readStoredList(PINS_KEY('u:1'))).toEqual(['page:/hardware']);
    expect(readStoredList(PINS_KEY('u:2'))).toEqual([]);
  });

  it('a masquerade session records recents in its own namespace', async () => {
    mockAuth.isMasquerade = true;
    render(<Harness />);
    await screen.findByText('Hardware page');

    await openViaShortcut();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'services' } });
    fireEvent.click(await screen.findByRole('button', { name: /^Services/ }));
    await screen.findByText('Services page');

    await waitFor(() => expect(readStoredList(RECENTS_KEY('masq:1'))).toContain('page:/services'));
    expect(readStoredList(RECENTS_KEY('u:1'))).toEqual([]);
  });
});
