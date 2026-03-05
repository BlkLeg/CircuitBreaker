import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext.jsx';

function getInitials(user) {
  if (!user) return '?';
  const name = user.display_name || user.email?.split('@')[0] || '';
  const parts = name.trim().split(/[\s._-]+/).filter(Boolean);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  if (parts[0]) return parts[0].slice(0, 2).toUpperCase();
  return '?';
}

function UserAvatar({ onOpenAuth, onOpenProfile }) {
  const { isAuthenticated, user, logout, authEnabled } = useAuth();
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [photoBroken, setPhotoBroken] = useState(false);
  const [gravatarBroken, setGravatarBroken] = useState(false);
  const dropdownRef = useRef(null);
  const navigate = useNavigate();

  // Reset broken-image flags when user's photo or gravatar changes
  useEffect(() => { setPhotoBroken(false); }, [user?.profile_photo_url]);
  useEffect(() => { setGravatarBroken(false); }, [user?.gravatar_hash]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!dropdownOpen) return;
    const handler = (e) => {
      if (!dropdownRef.current?.contains(e.target)) setDropdownOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [dropdownOpen]);

  const size = 36;

  // Priority: uploaded photo → gravatar → initials
  const showPhoto = !photoBroken && !!user?.profile_photo_url;
  const showGravatar = !showPhoto && !gravatarBroken && !!user?.gravatar_hash;

  let src = null;
  if (showPhoto) src = user.profile_photo_url;
  else if (showGravatar) src = `https://www.gravatar.com/avatar/${user.gravatar_hash}?s=72&d=404`;

  const handleClick = () => {
    if (isAuthenticated) {
      setDropdownOpen((v) => !v);
    } else {
      onOpenAuth?.();
    }
  };

  const defaultButtonTitle = authEnabled ? 'Login' : 'Guest';
  const buttonTitle = isAuthenticated 
    ? user?.display_name || user?.email 
    : defaultButtonTitle;

  const renderAvatar = () => {
    if (src) {
      return (
        <img
          src={src}
          alt="avatar"
          style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          onError={() => {
            if (showPhoto) setPhotoBroken(true);
            else if (showGravatar) setGravatarBroken(true);
          }}
        />
      );
    }
    if (isAuthenticated && user) {
      return (
        <span style={{
          fontSize: 13,
          fontWeight: 600,
          color: 'var(--color-primary)',
          userSelect: 'none',
          letterSpacing: '0.02em',
        }}>
          {getInitials(user)}
        </span>
      );
    }
    return (
      <span style={{ fontSize: 13, color: 'var(--color-text-muted)', userSelect: 'none' }}>
        ?
      </span>
    );
  };

  return (
    <div ref={dropdownRef} style={{ position: 'relative', pointerEvents: 'auto' }}>
      <button
        onClick={handleClick}
        title={buttonTitle}
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
        {renderAvatar()}
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

DropdownItem.propTypes = {
  label: PropTypes.string.isRequired,
  onClick: PropTypes.func.isRequired,
  danger: PropTypes.bool,
};

UserAvatar.propTypes = {
  onOpenAuth: PropTypes.func,
  onOpenProfile: PropTypes.func,
};

export default UserAvatar;
