import React from 'react';
import { Search } from 'lucide-react';

function Header({ onOpenPalette }) {
  return (
    <header className="global-header" style={{
      position: 'fixed',
      top: 8,
      right: 16,
      zIndex: 200,
      pointerEvents: 'none',
    }}>
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
    </header>
  );
}

export default Header;
