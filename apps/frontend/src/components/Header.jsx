import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { Search, Moon, Sun } from 'lucide-react';
import UserAvatar from './auth/UserAvatar.jsx';
import RecentChanges from './common/RecentChanges.jsx';
import ThemePalette from './ThemePalette';
import HeaderWidgets from './HeaderWidgets.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';
import { settingsApi } from '../api/client';

function Header({ onOpenPalette }) {
  const { openAuthModal, openProfileModal, isAuthenticated, user } = useAuth();
  const { settings, reloadSettings } = useSettings();
  const branding = settings?.branding;
  const appName = branding?.app_name || 'Circuit Breaker';
  const greetingName = user?.display_name || user?.email?.split('@')[0] || 'there';
  const [themeSaving, setThemeSaving] = useState(false);
  const isLightTheme = settings?.theme === 'light';

  const handleToggleTheme = async () => {
    if (themeSaving) return;
    const nextTheme = isLightTheme ? 'dark' : 'light';
    setThemeSaving(true);
    try {
      await settingsApi.update({ theme: nextTheme });
      await reloadSettings();
    } finally {
      setThemeSaving(false);
    }
  };

  return (
    <header
      className="global-header"
      role="banner"
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 200,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '8px 16px',
        background: 'var(--color-surface)',
        borderBottom: '1px solid var(--color-border)',
        height: 'var(--header-height)',
      }}
    >
      <Link to="/map" title="Home" aria-label={`${appName} — Home`} className="header-brand-link">
        <img
          src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
          alt={appName}
          className="header-logo"
          style={{ height: 40, width: 'auto', maxWidth: 120 }}
        />
        <div className="header-brand-text">
          <span className="header-brand-name">{appName}</span>
          {isAuthenticated && user && (
            <span className="header-greeting">Welcome, {greetingName}</span>
          )}
        </div>
      </Link>
      <div
        style={{
          position: 'absolute',
          left: '50%',
          transform: 'translate(-50%, -50%)',
          top: '50%',
          marginTop: '-1px',
          pointerEvents: 'auto',
          zIndex: 1,
        }}
      >
        <HeaderWidgets settings={settings} />
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, pointerEvents: 'auto' }}>
        <RecentChanges />
        <ThemePalette placement="header" />
        <button
          title={isLightTheme ? 'Switch to dark mode' : 'Switch to light mode'}
          aria-label={isLightTheme ? 'Switch to dark mode' : 'Switch to light mode'}
          onClick={handleToggleTheme}
          disabled={themeSaving}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 36,
            height: 36,
            background: 'transparent',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            cursor: themeSaving ? 'not-allowed' : 'pointer',
            color: 'var(--color-text-muted)',
            transition: 'all 0.15s',
            flexShrink: 0,
            opacity: themeSaving ? 0.6 : 1,
          }}
          onMouseEnter={(e) => {
            if (!themeSaving) e.currentTarget.style.borderColor = 'var(--color-primary)';
          }}
          onMouseLeave={(e) => {
            if (!themeSaving) e.currentTarget.style.borderColor = 'var(--color-border)';
          }}
        >
          {isLightTheme ? <Moon size={16} /> : <Sun size={16} />}
        </button>
        <UserAvatar onOpenAuth={openAuthModal} onOpenProfile={openProfileModal} />
        <button
          className="search-trigger"
          onClick={onOpenPalette}
          aria-label="Open command palette"
          aria-keyshortcuts="Control+K"
          style={{
            pointerEvents: 'auto',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: '8px',
            padding: '7px 14px',
            color: 'var(--color-text-muted)',
            fontSize: '13px',
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            width: '260px',
            maxWidth: 'calc(100vw - 32px)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'var(--color-surface)';
            e.currentTarget.style.borderColor = 'var(--color-primary)';
            e.currentTarget.style.color = 'var(--color-text)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'var(--color-surface)';
            e.currentTarget.style.borderColor = 'var(--color-border)';
            e.currentTarget.style.color = 'var(--color-text-muted)';
          }}
        >
          <Search size={14} />
          <span>Type a command or search...</span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: '11px',
              background: 'var(--color-border)',
              padding: '2px 6px',
              borderRadius: '4px',
            }}
          >
            Ctrl K
          </span>
        </button>
      </div>
    </header>
  );
}

Header.propTypes = {
  onOpenPalette: PropTypes.func.isRequired,
};

export default Header;
