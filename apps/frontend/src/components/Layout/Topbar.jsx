/* eslint-disable security/detect-object-injection -- internal key lookups */
import React from 'react';
import { useLocation } from 'react-router-dom';

const TITLE_MAP = {
  '/hardware': 'Hardware',
  '/compute-units': 'Compute Units',
  '/services': 'Services',
  '/storage': 'Storage',
  '/networks': 'Networks',
  '/misc': 'Misc Items',
  '/docs': 'Documentation',
  '/map': 'Topology Map',
};

function Topbar() {
  const { pathname } = useLocation();
  const title = TITLE_MAP[pathname] || 'Service Layout Mapper';
  return (
    <header className="topbar">
      <h1 className="topbar-title">{title}</h1>
    </header>
  );
}

export default Topbar;
