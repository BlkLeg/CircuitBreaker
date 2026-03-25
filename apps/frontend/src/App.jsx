import React, { useState, useEffect, useCallback, useRef } from 'react';
import PropTypes from 'prop-types';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { I18nextProvider } from 'react-i18next';
import i18n from './i18n';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import { TimezoneProvider } from './context/TimezoneContext.jsx';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { TenantProvider } from './context/TenantContext';
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
import { connectSSE, disconnectSSE } from './lib/sseClient.js';
import ConnectionStatus from './components/ConnectionStatus.jsx';
import MasqueradeBanner from './components/MasqueradeBanner.jsx';
import ServerLifecycleBanner from './components/ServerLifecycleBanner.jsx';
import LoadingScreen from './components/common/LoadingScreen.jsx';
import { canEdit, isAdmin } from './utils/rbac';

// Heavy pages lazy-loaded so their chunks are only downloaded when first visited.
const DocsPage = React.lazy(() => import('./pages/DocsPage'));
const SettingsPage = React.lazy(() => import('./pages/SettingsPage'));
const MapPage = React.lazy(() => import('./pages/MapPage'));
const DiscoveryPage = React.lazy(() => import('./pages/DiscoveryPage'));
const HardwarePage = React.lazy(() => import('./pages/HardwarePage'));
const ComputeUnitsPage = React.lazy(() => import('./pages/ComputeUnitsPage'));
const ServicesPage = React.lazy(() => import('./pages/ServicesPage'));
const StoragePage = React.lazy(() => import('./pages/StoragePage'));
const LogsPage = React.lazy(() => import('./pages/LogsPage'));
const ExternalNodesPage = React.lazy(() => import('./pages/ExternalNodesPage'));
const AdminUsersPage = React.lazy(() => import('./pages/AdminUsersPage'));
const UserActionsPage = React.lazy(() => import('./pages/UserActionsPage'));
const InviteAcceptPage = React.lazy(() => import('./pages/InviteAcceptPage'));
const ForceChangePasswordPage = React.lazy(() => import('./pages/ForceChangePasswordPage'));
const ResetPasswordPage = React.lazy(() => import('./pages/ResetPasswordPage'));
const VaultResetPage = React.lazy(() => import('./pages/VaultResetPage.jsx'));
const IPAMPage = React.lazy(() => import('./pages/IPAMPage'));
const StatusPagesPage = React.lazy(() => import('./pages/StatusPagesPage'));
const RackPage = React.lazy(() => import('./pages/RackPage'));
const PublicStatusPage = React.lazy(() => import('./pages/PublicStatusPage'));
const CertificatesPage = React.lazy(() => import('./pages/CertificatesPage'));
const NotificationsPage = React.lazy(() => import('./pages/NotificationsPage'));
const TenantsPage = React.lazy(() => import('./pages/TenantsPage'));

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
        <ErrorBoundary>
          <React.Suspense fallback={<LoadingScreen />}>
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                <Routes location={location}>
                  <Route path="/" element={<Navigate to="/map" replace />} />
                  <Route path="/hardware" element={<HardwarePage />} />
                  <Route path="/compute-units" element={<ComputeUnitsPage />} />
                  <Route path="/services" element={<ServicesPage />} />
                  <Route path="/storage" element={<StoragePage />} />
                  <Route path="/networks" element={<Navigate to="/ipam" replace />} />
                  <Route path="/certificates" element={<CertificatesPage />} />
                  <Route path="/notifications" element={<NotificationsPage />} />
                  <Route path="/tenants" element={<TenantsPage />} />
                  <Route path="/external-nodes" element={<ExternalNodesPage />} />
                  <Route path="/misc" element={<MiscPage />} />
                  <Route path="/docs" element={<DocsPage />} />
                  <Route path="/map" element={<MapPage />} />
                  <Route
                    path="/ipam"
                    element={
                      <RequireEditor>
                        <IPAMPage />
                      </RequireEditor>
                    }
                  />
                  <Route path="/ip-addresses" element={<Navigate to="/ipam" replace />} />
                  <Route
                    path="/status-pages"
                    element={
                      <RequireEditor>
                        <StatusPagesPage />
                      </RequireEditor>
                    }
                  />
                  <Route
                    path="/racks"
                    element={
                      <RequireEditor>
                        <RackPage />
                      </RequireEditor>
                    }
                  />
                  <Route
                    path="/logs"
                    element={
                      <RequireAdmin>
                        <LogsPage />
                      </RequireAdmin>
                    }
                  />
                  <Route
                    path="/settings"
                    element={
                      <RequireEditor>
                        <SettingsPage />
                      </RequireEditor>
                    }
                  />
                  <Route path="/discovery" element={<DiscoveryPage />} />
                  <Route path="/discovery/history" element={<Navigate to="/discovery" replace />} />
                  <Route
                    path="/admin/users"
                    element={
                      <RequireAdmin>
                        <AdminUsersPage />
                      </RequireAdmin>
                    }
                  />
                  <Route
                    path="/admin/users/:id/actions"
                    element={
                      <RequireAdmin>
                        <UserActionsPage />
                      </RequireAdmin>
                    }
                  />
                  <Route path="/invite/accept" element={<InviteAcceptPage />} />
                  <Route path="/auth/change-password" element={<ForceChangePasswordPage />} />
                  <Route path="/reset-password" element={<ResetPasswordPage />} />
                  <Route path="/status/:slug" element={<PublicStatusPage />} />
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

function RequireEditor({ children }) {
  const { user } = useAuth();
  return canEdit(user) ? children : <Navigate to="/map" replace />;
}

function RequireAdmin({ children }) {
  const { user } = useAuth();
  return isAdmin(user) ? children : <Navigate to="/map" replace />;
}

RequireEditor.propTypes = {
  children: PropTypes.node.isRequired,
};

RequireAdmin.propTypes = {
  children: PropTypes.node.isRequired,
};

// Preserves query-string (e.g. ?oauth_token=...) when redirecting to /login
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
            <Route path="/status/:slug" element={<PublicStatusPage />} />
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
      <BrowserRouter>
        <SettingsProvider>
          <TimezoneProvider>
            <AuthProvider>
              <ToastProvider>
                <ServerLifecycleBanner>
                  <TenantProvider>
                    <AppRoutes />
                  </TenantProvider>
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
