import React, { useState, useEffect, useCallback } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { SettingsProvider } from './context/SettingsContext';
import { TimezoneProvider } from './context/TimezoneContext.jsx';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { ToastProvider } from './components/common/Toast';
import { authApi } from './api/auth.js';
import ErrorBoundary from './components/ErrorBoundary';
import Dock from './components/Dock';
import Header from './components/Header';
import CommandPalette from './components/CommandPalette';
import ThemePalette from './components/ThemePalette';
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

// Heavy pages lazy-loaded so their chunks (reactflow/elkjs, md-editor) are only
// downloaded when the user first navigates to those routes.
const DocsPage = React.lazy(() => import('./pages/DocsPage'));
const MapPage = React.lazy(() => import('./pages/MapPage'));

function AppInner() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const { authModalOpen, setAuthModalOpen, profileModalOpen, setProfileModalOpen } = useAuth();

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
      <CommandPalette isOpen={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Header onOpenPalette={() => setPaletteOpen(true)} />
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
          </Routes>
          </React.Suspense>
        </ErrorBoundary>
      </div>
      <Dock />
      <ThemePalette />
      <AuthModal isOpen={authModalOpen} onClose={() => setAuthModalOpen(false)} />
      <ProfileModal isOpen={profileModalOpen} onClose={() => setProfileModalOpen(false)} />
    </div>
  );
}

function AppRoutes() {
  const { isAuthenticated, authEnabled, authReady } = useAuth();
  const [bootstrapLoading, setBootstrapLoading] = useState(true);
  const [needsBootstrap, setNeedsBootstrap] = useState(false);
  const [bootstrapError, setBootstrapError] = useState('');

  const fetchBootstrapStatus = useCallback(() => {
    setBootstrapLoading(true);
    setBootstrapError('');
    authApi.bootstrapStatus()
      .then((res) => {
        setNeedsBootstrap(Boolean(res.data?.needs_bootstrap));
      })
      .catch((err) => {
        const message = err?.message || 'Failed to determine setup state.';
        console.error('Bootstrap status check failed:', message);
        setBootstrapError(message);
      })
      .finally(() => {
        setBootstrapLoading(false);
      });
  }, []);

  useEffect(() => {
    fetchBootstrapStatus();
  }, [fetchBootstrapStatus]);

  if (bootstrapLoading || !authReady) {
    return <div className="login-root" />;
  }

  if (bootstrapError) {
    return (
      <div className="login-root">
        <div className="login-split" style={{ justifyContent: 'center' }}>
          <div className="login-card" role="alert" aria-live="polite">
            <h2 className="login-card-title">Setup check failed</h2>
            <p className="login-card-subtitle">
              Circuit Breaker could not determine whether first-run setup is required.
            </p>
            <div className="login-error-banner" style={{ marginBottom: 16 }}>
              {bootstrapError}
            </div>
            <button type="button" className="btn btn-primary login-btn-submit" onClick={fetchBootstrapStatus}>
              Retry setup check
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
  );
}

export default App;
