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
        label: 'Environments & Locations',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M3 4h10M3 8h7M3 12h5" />
          </svg>
        ),
      },
      {
        key: 'categories',
        label: 'Categories',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="4" cy="5" r="1.5" />
            <path d="M8 5h5M8 11h5" />
            <circle cx="4" cy="11" r="1.5" />
          </svg>
        ),
      },
      {
        key: 'environments',
        label: 'Environments',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <ellipse cx="8" cy="5" rx="6" ry="2.5" />
            <path d="M2 5v6c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5" />
            <path d="M2 8c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5" />
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
      {
        key: 'themes',
        label: 'Themes',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="4" cy="4" r="2" />
            <circle cx="12" cy="4" r="2" />
            <circle cx="4" cy="12" r="2" />
            <circle cx="12" cy="12" r="2" />
            <path d="M6 4h4M4 6v4M12 6v4M6 12h4" />
          </svg>
        ),
      },
      {
        key: 'dock',
        label: 'Dock',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="1" y="10" width="14" height="4" rx="1.5" />
            <rect x="2" y="11" width="2.5" height="2" rx="0.5" />
            <rect x="6" y="11" width="2.5" height="2" rx="0.5" />
            <rect x="10.5" y="11" width="2.5" height="2" rx="0.5" />
          </svg>
        ),
      },
      {
        key: 'branding',
        label: 'Branding',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <circle cx="8" cy="8" r="3" />
            <path d="M8 1v2M8 13v2M1 8h2M13 8h2" />
            <path d="M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4" />
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
      {
        key: 'auth',
        label: 'Authentication',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <rect x="3" y="7" width="10" height="7" rx="1.5" />
            <path d="M5 7V5a3 3 0 0 1 6 0v2" />
          </svg>
        ),
      },
      {
        key: 'admin',
        label: 'Admin & Backup',
        icon: (
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M8 1.5L2 4.5v4c0 3.3 2.5 6.4 6 7 3.5-.6 6-3.7 6-7v-4L8 1.5z" />
            <path d="M5.5 8l1.5 1.5L10.5 6" />
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
