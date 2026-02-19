import React from 'react';
import PropTypes from 'prop-types';

const GROUPS = [
  {
    heading: 'General',
    items: [
      {
        key: 'appearance',
        label: 'Appearance',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="8" r="5" />
            <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M3.05 12.95l1.41-1.41M11.54 4.46l1.41-1.41" />
          </svg>
        ),
      },
      {
        key: 'defaults',
        label: 'Defaults',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="3" width="12" height="10" rx="1.5" />
            <path d="M5 7h6M5 10h4" />
          </svg>
        ),
      },
    ],
  },
  {
    heading: 'Customisation',
    items: [
      {
        key: 'lists',
        label: 'Environments & Categories',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 4h10M3 8h7M3 12h5" />
          </svg>
        ),
      },
      {
        key: 'icons',
        label: 'Icons & Vendors',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="2" y="2" width="5" height="5" rx="1" />
            <rect x="9" y="2" width="5" height="5" rx="1" />
            <rect x="2" y="9" width="5" height="5" rx="1" />
            <rect x="9" y="9" width="5" height="5" rx="1" />
          </svg>
        ),
      },
    ],
  },
  {
    heading: 'Advanced',
    items: [
      {
        key: 'experimental',
        label: 'Experimental & Advanced',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M6 2v5L3 13h10L10 7V2" />
            <path d="M6 2h4" />
          </svg>
        ),
      },
    ],
  },
];

function SettingsNav({ activeSection, onNavClick }) {
  return (
    <nav aria-label="Settings navigation">
      <div className="settings-sidebar-header">Settings</div>
      {GROUPS.map((group) => (
        <div key={group.heading} className="settings-nav-group">
          <div className="settings-nav-heading">{group.heading}</div>
          {group.items.map((item) => (
            <button
              key={item.key}
              type="button"
              className={`settings-nav-item${activeSection === item.key ? ' active' : ''}`}
              onClick={() => onNavClick(item.key)}
              aria-current={activeSection === item.key ? 'true' : undefined}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

SettingsNav.propTypes = {
  activeSection: PropTypes.string.isRequired,
  onNavClick: PropTypes.func.isRequired,
};

export default SettingsNav;
