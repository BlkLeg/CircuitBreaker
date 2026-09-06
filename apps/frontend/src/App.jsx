import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { I18nextProvider } from 'react-i18next';
import i18n from './i18n';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import { TimezoneProvider } from './context/TimezoneContext.jsx';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { ToastProvider, useToast } from './components/common/Toast';
import { authApi } from './api/auth.js';
import ErrorBoundary from './components/ErrorBoundary';
import MacOSDOCK from './components/MacOSDOCK';
import Header from './components/Header';
import CommandPalette from './components/CommandPalette';
import AuthModal from './components/auth/AuthModal.jsx';
import ProfileModal from './components/auth/ProfileModal.jsx';
import MiscPage from './pages/MiscPage';
import LoginPage from './pages/LoginPage';
import OOBEWizardPage from './pages/OOBEWizardPage';
import { useDiscoveryStream, discoveryEmitter } from './hooks/useDiscoveryStream.js';
import { useNavigationTiming, useNavigationMountSignal } from './hooks/useNavigationTiming.js';
import { lazyRoute } from './lib/lazyRoute.js';
import { connectSSE, disconnectSSE } from './lib/sseClient.js';
import ConnectionStatus from './components/ConnectionStatus.jsx';
import MasqueradeBanner from './components/MasqueradeBanner.jsx';
import UpdateBanner from './components/UpdateBanner.jsx';
import ServerLifecycleBanner from './components/ServerLifecycleBanner.jsx';
import LoadingScreen from './components/common/LoadingScreen.jsx';
import Guarded from './components/common/Guarded';

/**
 * `/discovery/history` folded into `/discovery` — carrying the query string.
 *
 * A bare `<Navigate to="/discovery" />` drops it, and the search is load
 * bearing: `DiscoveryScopeSection` deep-links an agent's job history as
 * `?agent=<id>`, which `DiscoveryPage` reads to filter the history. Losing it
 * here would land the operator on the unfiltered list with no sign anything
 * had been asked for.
 */
export function DiscoveryHistoryRedirect() {
  const { search } = useLocation();
  return <Navigate to={{ pathname: '/discovery', search }} replace />;
}

// Heavy pages lazy-loaded so their chunks are only downloaded when first
// visited. `lazyRoute` is `React.lazy` plus the per-chunk fetch record route
// §4.2 asks for and a single retry on a failed import — see lib/lazyRoute.js
// for why both live in one wrapper. Do not reintroduce a bare `React.lazy`
// here: a route without a chunk record is a hole in §4.4's decision tree, and
// tests/build has a check that fails the build for one.
const DocsPage = lazyRoute('DocsPage', () => import('./pages/DocsPage'));
const SettingsPage = lazyRoute('SettingsPage', () => import('./pages/SettingsPage'));
const MapPage = lazyRoute('MapPage', () => import('./pages/MapPage'));
const DiscoveryPage = lazyRoute('DiscoveryPage', () => import('./pages/DiscoveryPage'));
const HardwarePage = lazyRoute('HardwarePage', () => import('./pages/HardwarePage'));
const ComputeUnitsPage = lazyRoute('ComputeUnitsPage', () => import('./pages/ComputeUnitsPage'));
const ServicesPage = lazyRoute('ServicesPage', () => import('./pages/ServicesPage'));
const StoragePage = lazyRoute('StoragePage', () => import('./pages/StoragePage'));
const LogsPage = lazyRoute('LogsPage', () => import('./pages/LogsPage'));
const ExternalNodesPage = lazyRoute('ExternalNodesPage', () => import('./pages/ExternalNodesPage'));
const AdminUsersPage = lazyRoute('AdminUsersPage', () => import('./pages/AdminUsersPage'));
const AccessTokensPage = lazyRoute('AccessTokensPage', () => import('./pages/AccessTokensPage'));
const UserActionsPage = lazyRoute('UserActionsPage', () => import('./pages/UserActionsPage'));
const InviteAcceptPage = lazyRoute('InviteAcceptPage', () => import('./pages/InviteAcceptPage'));
const ForceChangePasswordPage = lazyRoute(
  'ForceChangePasswordPage',
  () => import('./pages/ForceChangePasswordPage')
);
const ResetPasswordPage = lazyRoute('ResetPasswordPage', () => import('./pages/ResetPasswordPage'));
const VaultResetPage = lazyRoute('VaultResetPage', () => import('./pages/VaultResetPage.jsx'));
const IPAMPage = lazyRoute('IPAMPage', () => import('./pages/IPAMPage'));

const CertificatesPage = lazyRoute('CertificatesPage', () => import('./pages/CertificatesPage'));
const MonitorsPage = lazyRoute('MonitorsPage', () => import('./pages/MonitorsPage'));
const MonitorDetailPage = lazyRoute('MonitorDetailPage', () => import('./pages/MonitorDetailPage'));
const AgentsPage = lazyRoute('AgentsPage', () => import('./pages/AgentsPage'));
const AgentDetailPage = lazyRoute('AgentDetailPage', () => import('./pages/AgentDetailPage'));
const PrivacyPage = lazyRoute('PrivacyPage', () => import('./pages/PrivacyPage'));
const NotificationsPage = lazyRoute('NotificationsPage', () => import('./pages/NotificationsPage'));
const IntelPage = lazyRoute('IntelPage', () => import('./pages/IntelPage'));

function AppInner() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { authModalOpen, setAuthModalOpen, profileModalOpen, setProfileModalOpen, isMasquerade } =
    useAuth();
  const toast = useToast();
  const location = useLocation();
  const pathnameRef = useRef(location.pathname);
  pathnameRef.current = location.pathname;

  const { pendingCount, connected: discoveryConnected, wsStatus } = useDiscoveryStream();

  // Start the SSE client once at app root; tear down on unmount
  useEffect(() => {
    connectSSE();
    return () => disconnectSSE();
  }, []);

  useEffect(() => {
    const onJobUpdate = (job) => {
      if (!job?.status) return;
      if (pathnameRef.current.startsWith('/discovery')) return;

      const name = job.label || job.target_cidr || 'Scan';
      if (job.status === 'completed') {
        const hosts = job.hosts_found ?? 0;
        toast.success(`${name} completed \u2014 ${hosts} host${hosts !== 1 ? 's' : ''} found`);
      } else if (job.status === 'failed') {
        toast.error(`${name} failed${job.error_text ? `: ${job.error_text}` : ''}`);
      }
    };

    discoveryEmitter.on('job:update', onJobUpdate);
    return () => discoveryEmitter.off('job:update', onJobUpdate);
  }, [toast]);

  const handleClosePalette = useCallback(() => setPaletteOpen(false), []);
  const handleOpenPalette = useCallback(() => setPaletteOpen(true), []);

  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen((v) => !v);
      }
    };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="app-shell">
      <CommandPalette isOpen={paletteOpen} onClose={handleClosePalette} />
      <Header onOpenPalette={handleOpenPalette} />
      <MasqueradeBanner />
      <ConnectionStatus discoveryConnected={discoveryConnected} />
      <div
        className="page-content"
        style={
          isMasquerade
            ? { paddingTop: 'calc(var(--header-height, 60px) + 36px + 16px)' }
            : undefined
        }
      >
        <UpdateBanner />
        <ErrorBoundary>
          <React.Suspense fallback={<LoadingScreen />}>
            {/*
              This wrapper is a page transition and nothing more. It was added
              by 8bb0ee25 as the fix for the sticky-navigation wedge
              (known_bugs item 1) and was never actually load bearing for it:
              removing `AnimatePresence` outright leaves the wedge rate
              unchanged at 16/40, and `mode="sync"` gives 15/40 against 16/40
              for `"wait"`. The wedge lives in the router — see the comment on
              `<BrowserRouter>` at the bottom of this file.

              So `mode` is a look, not a fix, and it is safe to change on
              visual grounds. What is *not* safe is reaching for this block the
              next time navigation misbehaves; that mistake cost this bug eight
              months of investigation.
            */}
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                data-route-path={location.pathname}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                {/*
                  Mounted fresh every navigation (this element's ancestor is
                  keyed by location.pathname, so it fully remounts rather than
                  updating) and gated by the same Suspense boundary as
                  <Routes> below, so its mount effect fires exactly when the
                  incoming route has actually rendered — see
                  hooks/useNavigationTiming.js.
                */}
                <NavigationMountSignal />
                <Routes location={location}>
                  <Route path="/" element={<Navigate to="/map" replace />} />
                  <Route path="/hardware" element={<HardwarePage />} />
                  <Route path="/compute-units" element={<ComputeUnitsPage />} />
                  <Route path="/services" element={<ServicesPage />} />
                  <Route path="/storage" element={<StoragePage />} />
                  <Route path="/networks" element={<Navigate to="/ipam" replace />} />
                  <Route
                    path="/certificates"
                    element={
                      <Guarded path="/certificates">
                        <CertificatesPage />
                      </Guarded>
                    }
                  />
                  <Route path="/monitors" element={<MonitorsPage />} />
                  <Route path="/monitors/:id" element={<MonitorDetailPage />} />
                  <Route path="/privacy" element={<PrivacyPage />} />
                  <Route
                    path="/notifications"
                    element={
                      <Guarded path="/notifications">
                        <NotificationsPage />
                      </Guarded>
                    }
                  />
                  <Route path="/tenants" element={<Navigate to="/map" replace />} />
                  <Route path="/external-nodes" element={<ExternalNodesPage />} />
                  <Route path="/misc" element={<MiscPage />} />
                  <Route path="/docs" element={<DocsPage />} />
                  <Route path="/map" element={<MapPage />} />
                  <Route
                    path="/ipam"
                    element={
                      <Guarded path="/ipam">
                        <IPAMPage />
                      </Guarded>
                    }
                  />
                  <Route path="/ip-addresses" element={<Navigate to="/ipam" replace />} />
                  <Route path="/intel" element={<IntelPage />} />
                  <Route
                    path="/logs"
                    element={
                      <Guarded path="/logs">
                        <LogsPage />
                      </Guarded>
                    }
                  />
                  <Route
                    path="/logs/audit"
                    element={
                      <Guarded path="/logs/audit">
                        <LogsPage auditMode />
                      </Guarded>
                    }
                  />
                  <Route
                    path="/settings"
                    element={
                      <Guarded path="/settings">
                        <SettingsPage />
                      </Guarded>
                    }
                  />
                  <Route path="/discovery" element={<DiscoveryPage />} />
                  <Route path="/discovery/history" element={<DiscoveryHistoryRedirect />} />
                  <Route path="/agents" element={<AgentsPage />} />
                  <Route path="/agents/enroll" element={<AgentsPage />} />
                  <Route path="/agents/:id" element={<AgentDetailPage />} />
                  <Route
                    path="/admin/users"
                    element={
                      <Guarded path="/admin/users">
                        <AdminUsersPage />
                      </Guarded>
                    }
                  />
                  <Route
                    path="/admin/users/:id/actions"
                    element={
                      <Guarded path="/admin/users/:id/actions">
                        <UserActionsPage />
                      </Guarded>
                    }
                  />
                  <Route
                    path="/admin/tokens"
                    element={
                      <Guarded path="/admin/tokens">
                        <AccessTokensPage />
                      </Guarded>
                    }
                  />
                  <Route path="/invite/accept" element={<InviteAcceptPage />} />
                  <Route path="/auth/change-password" element={<ForceChangePasswordPage />} />
                  <Route path="/reset-password" element={<ResetPasswordPage />} />
                </Routes>
              </motion.div>
            </AnimatePresence>
          </React.Suspense>
        </ErrorBoundary>
      </div>
      <MacOSDOCK pendingCount={pendingCount} wsStatus={wsStatus} />
      <AuthModal isOpen={authModalOpen} onClose={() => setAuthModalOpen(false)} />
      <ProfileModal isOpen={profileModalOpen} onClose={() => setProfileModalOpen(false)} />
    </div>
  );
}

// Mounted once, inside the router context but above the route tree, so
// hooks/useNavigationTiming.js observes every navigation regardless of which
// page is showing — deliberately not folded into AppInner alongside
// useDiscoveryStream(), which route §4 H3 already suspects of a re-render
// storm; this renders nothing, so it adds no re-render surface there.
function NavigationTimingWatcher() {
  useNavigationTiming();
  return null;
}

// Mounted once, as a sibling of <Routes> inside the Suspense boundary that
// wraps it (see AppInner below) — the other half of useNavigationTiming.js.
// Renders nothing; its only job is the mount effect useNavigationMountSignal
// runs, which closes out whatever nav useNavigationTiming() opened.
function NavigationMountSignal() {
  useNavigationMountSignal();
  return null;
}

// Preserves query-string (e.g. ?cb_auth_code= for OAuth exchange) when redirecting to /login
function NavigateToLogin() {
  const location = useLocation();
  return <Navigate to={`/login${location.search}`} replace />;
}

function AppRoutes() {
  const BOOTSTRAP_RETRY_SECONDS = 10;
  const { isAuthenticated, authReady } = useAuth();
  const { settings } = useSettings();
  const branding = settings?.branding;
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const [bootstrapError, setBootstrapError] = useState(null);
  const [retryCountdown, setRetryCountdown] = useState(BOOTSTRAP_RETRY_SECONDS);
  const [isRetrying, setIsRetrying] = useState(false);
  const checkInFlightRef = useRef(false);

  const fetchBootstrapStatus = useCallback((options = {}) => {
    const { background = false } = options;
    if (checkInFlightRef.current) return;

    checkInFlightRef.current = true;
    if (!background) setBootstrapLoading(true);
    if (background) setIsRetrying(true);

    authApi
      .bootstrapStatus()
      .then((res) => {
        setNeedsBootstrap(Boolean(res.data?.needs_bootstrap));
        setBootstrapError(null);
        setRetryCountdown(BOOTSTRAP_RETRY_SECONDS);
      })
      .catch((err) => {
        const message = err?.message || 'Failed to determine setup state.';
        const status = err?.response?.status;
        const isStartup =
          status === 502 ||
          status === 503 ||
          status === 504 ||
          message.toLowerCase().includes('network error');
        console.error('Bootstrap status check failed:', message);
        setBootstrapError({ message, isStartup });
      })
      .finally(() => {
        checkInFlightRef.current = false;
        if (!background) setBootstrapLoading(false);
        if (background) setIsRetrying(false);
      });
  }, []);

  useEffect(() => {
    fetchBootstrapStatus();
  }, [fetchBootstrapStatus]);

  // ADR-0003 removed multi-tenancy. This clears the key left in browsers that used it;
  // it replaces a whole context provider that wrapped the app to do only this.
  useEffect(() => {
    try {
      window.localStorage.removeItem('cb_active_tenant_id');
    } catch {
      // Private mode and blocked site data both throw on access; nothing to clean up then.
    }
  }, []);

  useEffect(() => {
    if (!bootstrapError) {
      setRetryCountdown(BOOTSTRAP_RETRY_SECONDS);
      return;
    }

    const intervalId = globalThis.setInterval(() => {
      setRetryCountdown((prev) => {
        if (prev <= 1) {
          fetchBootstrapStatus({ background: true });
          return BOOTSTRAP_RETRY_SECONDS;
        }
        return prev - 1;
      });
    }, 1000);

    return () => globalThis.clearInterval(intervalId);
  }, [bootstrapError, fetchBootstrapStatus]);

  if (bootstrapLoading || !authReady) {
    return <LoadingScreen />;
  }

  // Server startup errors are now handled by ServerLifecycleBanner higher up the tree.
  // Only surface non-startup (configuration/setup) errors here.
  if (bootstrapError && !bootstrapError.isStartup) {
    return (
      <div className="login-root">
        <div className="setup-check-shell" role="alert" aria-live="polite">
          <img
            src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
            alt={branding?.app_name ?? 'Circuit Breaker'}
            className="setup-check-logo"
          />
          <div className="login-card setup-check-card">
            <h2 className="login-card-title">Setup check failed</h2>
            <p className="login-card-subtitle">
              Circuit Breaker could not determine whether first-run setup is required.
            </p>
            <div className="login-error-banner" style={{ marginBottom: 16 }}>
              {bootstrapError.message}
            </div>
            {(isRetrying || retryCountdown < 3) && (
              <p className="login-card-subtitle" style={{ marginBottom: 8, fontSize: '0.9rem' }}>
                The server may still be starting. Retrying…
              </p>
            )}
            <div className="setup-check-status" aria-live="polite">
              {isRetrying ? 'Retrying setup check…' : `Auto-retry in ${retryCountdown}s`}
            </div>
            <button
              type="button"
              className="btn btn-primary login-btn-submit"
              onClick={() => fetchBootstrapStatus()}
              disabled={isRetrying}
            >
              {isRetrying ? 'Retrying…' : 'Retry setup check now'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (needsBootstrap) {
    return (
      <Routes>
        <Route path="*" element={<OOBEWizardPage onCompleted={() => setNeedsBootstrap(false)} />} />
      </Routes>
    );
  }

  if (!isAuthenticated) {
    return (
      <ErrorBoundary>
        <React.Suspense fallback={<LoadingScreen />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/auth/change-password" element={<ForceChangePasswordPage />} />
            <Route path="/invite/accept" element={<InviteAcceptPage />} />
            <Route path="/reset-password" element={<ResetPasswordPage />} />
            <Route path="/reset-password/vault" element={<VaultResetPage />} />

            <Route path="*" element={<NavigateToLogin />} />
          </Routes>
        </React.Suspense>
      </ErrorBoundary>
    );
  }

  return (
    <ErrorBoundary>
      <React.Suspense fallback={<LoadingScreen />}>
        <Routes>
          <Route path="/login" element={<Navigate to="/map" replace />} />
          <Route path="/*" element={<AppInner />} />
        </Routes>
      </React.Suspense>
    </ErrorBoundary>
  );
}

function App() {
  return (
    <I18nextProvider i18n={i18n}>
      {/*
        `useTransitions={false}` is the fix for known_bugs item 1, the sticky
        navigation wedge: the URL advances and the page does not, permanently,
        until a manual reload.

        react-router v7 wraps every location update in `React.startTransition`,
        while `history.pushState` has already changed the URL synchronously.
        A transition is interruptible and non-urgent, so React is free to
        render it late, discard the render, or never commit it at all — and
        when the outgoing route is an expensive tree (MapPage's topology
        canvas), that is exactly what happens. The URL and the rendered route
        then disagree with nothing on screen to say so: no fallback, no error
        boundary, no console error. A reload is the only recovery because it
        re-seeds both from the address bar.

        Measured on this app, dock-click navigations, Chromium under 6x CPU
        throttle:

        | variant                            | wedges |
        |------------------------------------|--------|
        | as shipped                         | 16/40  |
        | `AnimatePresence mode="sync"`      | 15/40  |
        | no `AnimatePresence` at all        | 16/40  |
        | journey routes imported eagerly    | 16/40  |
        | `useTransitions={false}`           |  0/80  |

        and against a real backend, 15/40 -> 0/40. Every wedge in every run was
        a navigation *away from* `/map`.

        Read the middle rows before changing anything here. The animation
        wrapper in `AppInner` and the `React.lazy` route chunks were the two
        standing hypotheses for eight months, and both are innocent: removing
        either one entirely leaves the wedge rate untouched. Only this prop does.

        The cost is the intended one. Without transitions the location commits
        immediately, so a route whose chunk is still loading shows the
        `LoadingScreen` fallback instead of silently holding the previous page.
        A visible loading state is the behaviour this app wants; a stale page
        that lies about where you are is not.

        tests/build/test_router_transitions_contract.py fails the build if this
        prop is dropped, and e2e/navigation.spec.ts reproduces the wedge under
        throttle.
      */}
      <BrowserRouter useTransitions={false}>
        <NavigationTimingWatcher />
        <SettingsProvider>
          <TimezoneProvider>
            <AuthProvider>
              <ToastProvider>
                <ServerLifecycleBanner>
                  <AppRoutes />
                </ServerLifecycleBanner>
              </ToastProvider>
            </AuthProvider>
          </TimezoneProvider>
        </SettingsProvider>
      </BrowserRouter>
    </I18nextProvider>
  );
}

export default App;
