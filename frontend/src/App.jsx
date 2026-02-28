import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { SettingsProvider } from './context/SettingsContext';
import { AuthProvider, useAuth } from './context/AuthContext.jsx';
import { ToastProvider } from './components/common/Toast';
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
import DocsPage from './pages/DocsPage';
import MapPage from './pages/MapPage';
import LogsPage from './pages/LogsPage';
import SettingsPage from './pages/SettingsPage';
import LoginPage from './pages/LoginPage';

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
          <Routes>
            <Route path="/" element={<Navigate to="/map" replace />} />
            <Route path="/hardware" element={<HardwarePage />} />
            <Route path="/compute-units" element={<ComputeUnitsPage />} />
            <Route path="/services" element={<ServicesPage />} />
            <Route path="/storage" element={<StoragePage />} />
            <Route path="/networks" element={<NetworksPage />} />
            <Route path="/misc" element={<MiscPage />} />
            <Route path="/docs" element={<DocsPage />} />
            <Route path="/map" element={<MapPage />} />
            <Route path="/logs" element={<LogsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </ErrorBoundary>
      </div>
      <Dock />
      <ThemePalette />
      <AuthModal isOpen={authModalOpen} onClose={() => setAuthModalOpen(false)} />
      <ProfileModal isOpen={profileModalOpen} onClose={() => setProfileModalOpen(false)} />
    </div>
  );
}

function App() {
  return (
    <BrowserRouter>
    <SettingsProvider>
    <AuthProvider>
    <ToastProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/*" element={<AppInner />} />
      </Routes>
    </ToastProvider>
    </AuthProvider>
    </SettingsProvider>
    </BrowserRouter>
  );
}

export default App;
