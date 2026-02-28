import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { User } from 'lucide-react';
import { useAuth } from '../../context/AuthContext.jsx';

function avatarSrc(user) {
  if (!user) return null;
  if (user.profile_photo_url) return user.profile_photo_url;
  if (user.gravatar_hash) {
    return `https://www.gravatar.com/avatar/${user.gravatar_hash}?s=72&d=mp`;
  }
  return null;
}

function UserAvatar({ onOpenAuth, onOpenProfile }) {
  const { isAuthenticated, user, logout, authEnabled } = useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef(null);
  const navigate = useNavigate();

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    const handler = (e) => {
      if (!dropdownRef.current?.contains(e.target)) setDropdownOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [dropdownOpen]);

  const src = avatarSrc(user);
  const size = 36;

  const handleClick = () => {
    if (isAuthenticated) {
      setDropdownOpen((v) => !v);
    } else {
      onOpenAuth?.();
    }
  };

  return (
    <div ref={dropdownRef} style={{ position: 'relative', pointerEvents: 'auto' }}>
      <button
        onClick={handleClick}
        title={isAuthenticated ? user?.display_name || user?.email : authEnabled ? 'Login' : 'Guest'}
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          border: `1px solid var(--color-border)`,
          background: 'var(--color-surface)',
          padding: 0,
          cursor: 'pointer',
          overflow: 'hidden',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'border-color 0.2s',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.borderColor = 'var(--color-primary)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.borderColor = 'var(--color-border)';
        }}
      >
        {src ? (
          <img src={src} alt="avatar" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
        ) : (
          <User size={18} color="var(--color-text-muted)" />
        )}
      </button>

      {dropdownOpen && isAuthenticated && (
        <div style={{
          position: 'absolute',
          top: size + 8,
          right: 0,
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 8,
          padding: '4px 0',
          minWidth: 160,
          zIndex: 300,
          boxShadow: '0 4px 16px rgba(0,0,0,0.4)',
        }}>
          <div style={{ padding: '8px 14px 6px', borderBottom: '1px solid var(--color-border)', marginBottom: 4 }}>
            <div style={{ fontSize: 13, color: 'var(--color-text)', fontWeight: 500 }}>
              {user?.display_name || user?.email}
            </div>
            {user?.display_name && (
              <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{user.email}</div>
            )}
          </div>
          <DropdownItem label="Profile" onClick={() => { setDropdownOpen(false); onOpenProfile?.(); }} />
          <DropdownItem label="Settings" onClick={() => { setDropdownOpen(false); navigate('/settings?section=auth'); }} />
          <DropdownItem
            label="Logout"
            danger
            onClick={() => { setDropdownOpen(false); logout(); }}
          />
        </div>
      )}
    </div>
  );
}

function DropdownItem({ label, onClick, danger }) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'block',
        width: '100%',
        textAlign: 'left',
        padding: '7px 14px',
        background: 'transparent',
        border: 'none',
        color: danger ? 'var(--color-danger)' : 'var(--color-text)',
        fontSize: 13,
        cursor: 'pointer',
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-border)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
    >
      {label}
    </button>
  );
}

export default UserAvatar;
