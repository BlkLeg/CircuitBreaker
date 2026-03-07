import React, { useState, useEffect, useCallback, useRef } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
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
import HardwarePage from './pages/HardwarePage';
import ComputeUnitsPage from './pages/ComputeUnitsPage';
import ServicesPage from './pages/ServicesPage';
import StoragePage from './pages/StoragePage';
import NetworksPage from './pages/NetworksPage';
import MiscPage from './pages/MiscPage';
import LogsPage from './pages/LogsPage';
import SettingsPage from './pages/SettingsPage';
import ExternalNodesPage from './pages/ExternalNodesPage';
import LoginPage from './pages/LoginPage';
import OOBEWizardPage from './pages/OOBEWizardPage';
import { useDiscoveryStream } from './hooks/useDiscoveryStream.js';

// Heavy pages lazy-loaded so their chunks (reactflow/elkjs, md-editor, scan UI)
// are only downloaded when the user first navigates to those routes.
const DocsPage = React.lazy(() => import('./pages/DocsPage'));
const MapPage = React.lazy(() => import('./pages/MapPage'));
const DiscoveryPage = React.lazy(() => import('./pages/DiscoveryPage'));
const DiscoveryHistoryPage = React.lazy(() => import('./pages/DiscoveryHistoryPage'));

function AppInner() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { authModalOpen, setAuthModalOpen, profileModalOpen, setProfileModalOpen } = useAuth();
  const { pendingCount } = useDiscoveryStream();

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
              <Route path="/logs" element={<LogsPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/discovery" element={<DiscoveryPage />} />
              <Route path="/discovery/history" element={<DiscoveryHistoryPage />} />
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
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    );
  }

  return (
    <Routes>
      <Route path="/login" element={<Navigate to="/map" replace />} />
      <Route path="/*" element={<AppInner />} />
    </Routes>
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
