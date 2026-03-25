import React, { useMemo, useRef, useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { Link, useNavigate } from 'react-router-dom';
import { Search, Moon, Sun, Menu, ChevronDown, LayoutGrid } from 'lucide-react';
import UserAvatar from './auth/UserAvatar.jsx';
import RecentChanges from './common/RecentChanges.jsx';
import ThemePalette from './ThemePalette';
import HeaderWidgets from './HeaderWidgets.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';
import { useTenant } from '../context/TenantContext';
import { settingsApi } from '../api/client';
import { NAV_ITEMS } from '../data/navigation';
import { canEdit, isAdmin } from '../utils/rbac';

function Header({ onOpenPalette }) {
  const navigate = useNavigate();
  const { openAuthModal, openProfileModal, isAuthenticated, user } = useAuth();
  const { settings, reloadSettings } = useSettings();
  const { tenants, activeTenant, switchTenant } = useTenant();
  const branding = settings?.branding;
  const appName = branding?.app_name || 'Circuit Breaker';
  const greetingName = user?.display_name || user?.email?.split('@')[0] || 'there';
  const [themeSaving, setThemeSaving] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [tenantOpen, setTenantOpen] = useState(false);
  const menuRef = useRef(null);
  const tenantRef = useRef(null);
  const isLightTheme = settings?.theme === 'light';

  useEffect(() => {
    const onOutsideClick = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        setMenuOpen(false);
      }
      if (tenantRef.current && !tenantRef.current.contains(event.target)) {
        setTenantOpen(false);
      }
    };
    document.addEventListener('mousedown', onOutsideClick);
    return () => document.removeEventListener('mousedown', onOutsideClick);
  }, []);

  const groupedNavItems = useMemo(
    () =>
      NAV_ITEMS.map((group) => {
        if (group.requireAdmin && !isAdmin(user)) return null;
        const filteredItems = group.items.filter((item) => {
          if (item.requireAdmin && !isAdmin(user)) return false;
          if (item.requireEditor && !canEdit(user)) return false;
          return true;
        });
        if (filteredItems.length === 0) return null;
        return { ...group, items: filteredItems };
      }).filter(Boolean),
    [user]
  );

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
        {isAuthenticated && tenants.length > 1 && (
          <div ref={tenantRef} style={{ position: 'relative' }}>
            <button
              onClick={() => setTenantOpen(!tenantOpen)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                height: 36,
                border: '1px solid var(--color-border)',
                borderRadius: 10,
                background: 'var(--color-bg)',
                color: 'var(--color-text)',
                padding: '0 12px',
                fontSize: 12,
                fontWeight: 600,
                cursor: 'pointer',
              }}
            >
              <LayoutGrid size={14} className="tw-text-cb-primary" />
              <span>{activeTenant?.name || 'Select Tenant'}</span>
              <ChevronDown size={14} style={{ opacity: 0.5 }} />
            </button>

            {tenantOpen && (
              <div
                style={{
                  position: 'absolute',
                  top: 'calc(var(--header-height, 52px) - 6px)',
                  right: 0,
                  width: 220,
                  background: 'color-mix(in srgb, var(--color-surface) 94%, transparent)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 12,
                  boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
                  backdropFilter: 'blur(20px)',
                  padding: '8px',
                  zIndex: 240,
                }}
              >
                <div
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color: 'var(--color-text-muted)',
                    textTransform: 'uppercase',
                    padding: '4px 8px 8px',
                  }}
                >
                  Switch Environment
                </div>
                {tenants.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => {
                      switchTenant(t.id);
                      setTenantOpen(false);
                    }}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      width: '100%',
                      textAlign: 'left',
                      border: '1px solid transparent',
                      borderRadius: 8,
                      background:
                        String(t.id) === String(activeTenant?.id)
                          ? 'var(--color-primary-dim)'
                          : 'transparent',
                      color:
                        String(t.id) === String(activeTenant?.id)
                          ? 'var(--color-primary)'
                          : 'var(--color-text)',
                      padding: '8px 10px',
                      fontSize: 13,
                      cursor: 'pointer',
                    }}
                  >
                    <span style={{ flex: 1 }}>{t.name}</span>
                    {String(t.id) === String(activeTenant?.id) && (
                      <div
                        style={{
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: 'currentColor',
                        }}
                      />
                    )}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
        <div ref={menuRef} style={{ position: 'relative' }}>
          <button
            title="Open route menu"
            aria-label="Open route menu"
            onClick={() => setMenuOpen((open) => !open)}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              height: 36,
              border: '1px solid var(--color-border)',
              borderRadius: 10,
              background: 'var(--color-surface)',
              color: 'var(--color-text-muted)',
              padding: '0 12px',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <Menu size={16} />
            Routes
          </button>

          {menuOpen && (
            <div
              style={{
                position: 'absolute',
                top: 'calc(var(--header-height, 52px) - 6px)',
                right: 0,
                width: 320,
                maxHeight: 'min(72vh, 640px)',
                overflowY: 'auto',
                background: 'color-mix(in srgb, var(--color-surface) 94%, transparent)',
                border: '1px solid var(--color-border)',
                borderRadius: 12,
                boxShadow: '0 16px 40px rgba(0,0,0,0.35)',
                backdropFilter: 'blur(20px)',
                padding: '10px',
                zIndex: 240,
              }}
            >
              {groupedNavItems.map((group) => (
                <div key={group.group} style={{ marginBottom: 10 }}>
                  <div
                    style={{
                      color: 'var(--color-text-muted)',
                      fontSize: 11,
                      fontWeight: 700,
                      textTransform: 'uppercase',
                      letterSpacing: '0.06em',
                      padding: '4px 8px',
                    }}
                  >
                    {group.group}
                  </div>
                  <div style={{ display: 'grid', gap: 4 }}>
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      return (
                        <button
                          key={item.path}
                          onClick={() => {
                            setMenuOpen(false);
                            navigate(item.path);
                          }}
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 10,
                            width: '100%',
                            textAlign: 'left',
                            border: '1px solid transparent',
                            borderRadius: 10,
                            background: 'transparent',
                            color: 'var(--color-text)',
                            padding: '8px 10px',
                            fontSize: 13,
                            cursor: 'pointer',
                          }}
                          onMouseEnter={(e) => {
                            e.currentTarget.style.background = 'var(--color-border)';
                            e.currentTarget.style.borderColor = 'var(--color-border)';
                          }}
                          onMouseLeave={(e) => {
                            e.currentTarget.style.background = 'transparent';
                            e.currentTarget.style.borderColor = 'transparent';
                          }}
                        >
                          <Icon size={16} />
                          {item.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
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
