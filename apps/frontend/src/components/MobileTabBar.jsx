import React, { useState } from 'react';
import { NavLink } from 'react-router-dom';
import { Map, Server, Network, ScrollText, MoreHorizontal } from 'lucide-react';
import MobileOverflowSheet from './MobileOverflowSheet';

const MobileTabBar = ({ overflowItems, pendingCount }) => {
  const [isSheetOpen, setIsSheetOpen] = useState(false);

  const primaryTabs = [
    { icon: Map, path: '/map', label: 'Map' },
    { icon: Server, path: '/hardware', label: 'Hardware' },
    { icon: ScrollText, path: '/services', label: 'Services' },
    { icon: Network, path: '/networks', label: 'Network' },
  ];

  return (
    <>
      <nav className="mobile-tab-bar">
        {primaryTabs.map((tab) => (
          <NavLink
            key={tab.path}
            to={tab.path}
            className={({ isActive }) => `mobile-tab-item ${isActive ? 'active' : ''}`}
          >
            <tab.icon size={22} strokeWidth={1.5} />
            <span className="mobile-tab-label">{tab.label}</span>
          </NavLink>
        ))}
        <button
          className={`mobile-tab-item ${isSheetOpen ? 'active' : ''}`}
          onClick={() => setIsSheetOpen(true)}
        >
          <div className="mobile-tab-icon-wrapper">
            <MoreHorizontal size={22} strokeWidth={1.5} />
            {pendingCount > 0 && <span className="mobile-tab-badge" />}
          </div>
          <span className="mobile-tab-label">More</span>
        </button>
      </nav>
      <MobileOverflowSheet
        isOpen={isSheetOpen}
        onClose={() => setIsSheetOpen(false)}
        navItems={overflowItems}
        pendingCount={pendingCount}
      />
    </>
  );
};

export default MobileTabBar;
