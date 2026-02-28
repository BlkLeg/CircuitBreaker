import React from 'react';
import { Link } from 'react-router-dom';
import { Search } from 'lucide-react';
import UserAvatar from './auth/UserAvatar.jsx';
import RecentChanges from './common/RecentChanges.jsx';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';

function Header({ onOpenPalette }) {
  const { openAuthModal, openProfileModal } = useAuth();
  const { settings } = useSettings();
  const branding = settings?.branding;

  return (
    <>
      <header className="global-header" style={{
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
      }}>
      <Link
        to="/map"
        title="Home"
        style={{
          pointerEvents: 'auto',
          opacity: 1,
          transition: 'opacity 0.2s ease',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          flexShrink: 0,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.opacity = '0.75'; }}
        onMouseLeave={(e) => { e.currentTarget.style.opacity = '1'; }}
      >
        <img
          src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
          alt={branding?.app_name ?? 'Circuit Breaker'}
          style={{ width: 80, height: 'auto' }}
        />
      </Link>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, pointerEvents: 'auto' }}>
      <RecentChanges />
      <UserAvatar onOpenAuth={openAuthModal} onOpenProfile={openProfileModal} />
      <button
        className="search-trigger"
        onClick={onOpenPalette}
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
        <span style={{
          marginLeft: 'auto',
          fontSize: '11px',
          background: 'var(--color-border)',
          padding: '2px 6px',
          borderRadius: '4px'
        }}>Ctrl K</span>
      </button>
      </div>
      </header>
    </>
  );
}

export default Header;
