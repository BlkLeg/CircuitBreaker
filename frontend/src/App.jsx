import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { SettingsProvider } from './context/SettingsContext';
import { ToastProvider } from './components/common/Toast';
import ErrorBoundary from './components/ErrorBoundary';
import Dock from './components/Dock';
import Header from './components/Header';
import CommandPalette from './components/CommandPalette';
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

function App() {
  const [paletteOpen, setPaletteOpen] = useState(false);

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
    <SettingsProvider>
    <ToastProvider>
    <BrowserRouter>
      <div className="app-shell">
        <CommandPalette isOpen={paletteOpen} onClose={() => setPaletteOpen(false)} />
        <Header onOpenPalette={() => setPaletteOpen(true)} />
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
      </div>
    </BrowserRouter>
    </ToastProvider>
    </SettingsProvider>
  );
}

export default App;

