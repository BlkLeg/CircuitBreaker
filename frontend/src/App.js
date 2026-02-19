import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from './components/Layout/Sidebar';
import Topbar from './components/Layout/Topbar';
import HardwarePage from './pages/HardwarePage';
import ComputeUnitsPage from './pages/ComputeUnitsPage';
import ServicesPage from './pages/ServicesPage';
import StoragePage from './pages/StoragePage';
import NetworksPage from './pages/NetworksPage';
import MiscPage from './pages/MiscPage';
import DocsPage from './pages/DocsPage';
import MapPage from './pages/MapPage';

function App() {
  return (
    <BrowserRouter>
      <div className="app-shell">
        <Sidebar />
        <div className="main-area">
          <Topbar />
          <div className="page-content">
            <Routes>
              <Route path="/" element={<Navigate to="/hardware" replace />} />
              <Route path="/hardware" element={<HardwarePage />} />
              <Route path="/compute-units" element={<ComputeUnitsPage />} />
              <Route path="/services" element={<ServicesPage />} />
              <Route path="/storage" element={<StoragePage />} />
              <Route path="/networks" element={<NetworksPage />} />
              <Route path="/misc" element={<MiscPage />} />
              <Route path="/docs" element={<DocsPage />} />
              <Route path="/map" element={<MapPage />} />
            </Routes>
          </div>
        </div>
      </div>
    </BrowserRouter>
  );
}

export default App;
