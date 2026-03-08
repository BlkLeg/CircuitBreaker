import React from 'react';
import { NavLink } from 'react-router-dom';

const NAV_ITEMS = [
  { path: '/hardware', label: 'Hardware' },
  { path: '/compute-units', label: 'Compute Units' },
  { path: '/services', label: 'Services' },
  { path: '/storage', label: 'Storage' },
  { path: '/networks', label: 'Networks' },
  { path: '/misc', label: 'Misc' },
  { path: '/docs', label: 'Docs' },
  { path: '/map', label: 'Map' },
];

function Sidebar() {
  return (
    <nav className="sidebar">
      <div className="sidebar-brand">SLM</div>
      <ul className="sidebar-nav">
        {NAV_ITEMS.map(({ path, label }) => (
          <li key={path}>
            <NavLink
              to={path}
              className={({ isActive }) => (isActive ? 'nav-link active' : 'nav-link')}
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default Sidebar;
