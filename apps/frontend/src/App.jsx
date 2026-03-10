import React, { useState, useEffect, useCallback, useRef } from 'react';
import PropTypes from 'prop-types';
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom';
import { I18nextProvider } from 'react-i18next';
import i18n from './i18n';
import { SettingsProvider, useSettings } from './context/SettingsContext';
import { TimezoneProvider } from './context/TimezoneContext.jsx';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { ToastProvider } from './components/common/Toast';
import { authApi } from './api/auth.js';
import ErrorBoundary from './components/ErrorBoundary';
import Dock from './components/Dock';
import Header from './components/Header';
import CommandPalette from './components/CommandPalette';
import AuthModal from './components/auth/AuthModal.jsx';
import ProfileModal from './components/auth/ProfileModal.jsx';
import SecurityBanner from './components/common/SecurityBanner.jsx';
import MiscPage from './pages/MiscPage';
import LoginPage from './pages/LoginPage';
import OOBEWizardPage from './pages/OOBEWizardPage';
import { useDiscoveryStream } from './hooks/useDiscoveryStream.js';
import { connectSSE, disconnectSSE } from './lib/sseClient.js';
import ConnectionStatus from './components/ConnectionStatus.jsx';
import { canEdit, isAdmin } from './utils/rbac';

// Heavy pages lazy-loaded so their chunks are only downloaded when first visited.
const DocsPage = React.lazy(() => import('./pages/DocsPage'));
const SettingsPage = React.lazy(() => import('./pages/SettingsPage'));
const MapPage = React.lazy(() => import('./pages/MapPage'));
const DiscoveryPage = React.lazy(() => import('./pages/DiscoveryPage'));
const DiscoveryHistoryPage = React.lazy(() => import('./pages/DiscoveryHistoryPage'));
const HardwarePage = React.lazy(() => import('./pages/HardwarePage'));
const ComputeUnitsPage = React.lazy(() => import('./pages/ComputeUnitsPage'));
const ServicesPage = React.lazy(() => import('./pages/ServicesPage'));
const StoragePage = React.lazy(() => import('./pages/StoragePage'));
const NetworksPage = React.lazy(() => import('./pages/NetworksPage'));
const LogsPage = React.lazy(() => import('./pages/LogsPage'));
const ExternalNodesPage = React.lazy(() => import('./pages/ExternalNodesPage'));
const AdminUsersPage = React.lazy(() => import('./pages/AdminUsersPage'));
const UserActionsPage = React.lazy(() => import('./pages/UserActionsPage'));
const InviteAcceptPage = React.lazy(() => import('./pages/InviteAcceptPage'));
const ForceChangePasswordPage = React.lazy(() => import('./pages/ForceChangePasswordPage'));
const ResetPasswordPage = React.lazy(() => import('./pages/ResetPasswordPage'));
const VaultResetPage = React.lazy(() => import('./pages/VaultResetPage.jsx'));

function AppInner() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { authModalOpen, setAuthModalOpen, profileModalOpen, setProfileModalOpen, authEnabled } =
    useAuth();
  const { pendingCount, connected: discoveryConnected } = useDiscoveryStream({ authEnabled });

  // Start the SSE client once at app root; tear down on unmount
  useEffect(() => {
    connectSSE();
    return () => disconnectSSE();
  }, []);

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
      <SecurityBanner />
      <ConnectionStatus discoveryConnected={discoveryConnected} />
      <div className="page-content">
        <ErrorBoundary>
          <React.Suspense fallback={null}>
            <Routes>
              <Route path="/" element={<Navigate to="/map" replace />} />
              <Route path="/hardware" element={<HardwarePage />} />
              <Route path="/compute-units" element={<ComputeUnitsPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/storage" element={<StoragePage />} />
              <Route path="/networks" element={<NetworksPage />} />
              <Route path="/external-nodes" element={<ExternalNodesPage />} />
              <Route path="/misc" element={<MiscPage />} />
              <Route path="/docs" element={<DocsPage />} />
              <Route path="/map" element={<MapPage />} />
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
              <Route path="/discovery/history" element={<DiscoveryHistoryPage />} />
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
            </Routes>
          </React.Suspense>
        </ErrorBoundary>
      </div>
      <Dock pendingCount={pendingCount} />
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
  const { isAuthenticated, authEnabled, authReady } = useAuth();
  const { settings } = useSettings();
  const branding = settings?.branding;
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const [bootstrapError, setBootstrapError] = useState('');
  const [retryCountdown, setRetryCountdown] = useState(3);
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
        setBootstrapError('');
        setRetryCountdown(3);
      })
      .catch((err) => {
        const message = err?.message || 'Failed to determine setup state.';
        console.error('Bootstrap status check failed:', message);
        setBootstrapError(message);
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
      setRetryCountdown(3);
      return;
    }

    const intervalId = globalThis.setInterval(() => {
      setRetryCountdown((prev) => {
        if (prev <= 1) {
          fetchBootstrapStatus({ background: true });
          return 3;
        }
        return prev - 1;
      });
    }, 1000);

    return () => globalThis.clearInterval(intervalId);
  }, [bootstrapError, fetchBootstrapStatus]);

  if (bootstrapLoading || !authReady) {
    return <div className="login-root" />;
  }

  if (bootstrapError) {
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
              {bootstrapError}
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

  if (authEnabled && !isAuthenticated) {
    return (
      <React.Suspense fallback={<div className="login-root" />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/auth/change-password" element={<ForceChangePasswordPage />} />
          <Route path="/invite/accept" element={<InviteAcceptPage />} />
          <Route path="/reset-password" element={<ResetPasswordPage />} />
          <Route path="/reset-password/vault" element={<VaultResetPage />} />
          <Route path="/auth/change-password" element={<ForceChangePasswordPage />} />
          <Route path="*" element={<NavigateToLogin />} />
        </Routes>
      </React.Suspense>
    );
  }

  return (
    <React.Suspense fallback={<div className="login-root" />}>
      <Routes>
        <Route path="/login" element={<Navigate to="/map" replace />} />
        <Route path="/*" element={<AppInner />} />
      </Routes>
    </React.Suspense>
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
                <AppRoutes />
              </ToastProvider>
            </AuthProvider>
          </TimezoneProvider>
        </SettingsProvider>
      </BrowserRouter>
    </I18nextProvider>
  );
}

export default App;
