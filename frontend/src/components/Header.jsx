import React from 'react';
import { Search } from 'lucide-react';

function Header({ onOpenPalette }) {
  return (
    <header className="global-header" style={{
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      height: '60px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 50,
      pointerEvents: 'none' // Let clicks pass through to underlying elements if not on search
    }}>
      <button 
        className="search-trigger"
        onClick={onOpenPalette}
        style={{
          pointerEvents: 'auto',
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          background: 'rgba(13, 17, 23, 0.6)',
          border: '1px solid rgba(30, 42, 58, 0.6)',
          borderRadius: '8px',
          padding: '8px 16px',
          color: 'var(--color-text-muted)',
          fontSize: '13px',
          cursor: 'pointer',
          backdropFilter: 'blur(8px)',
          transition: 'all 0.2s ease',
          width: '320px',
          maxWidth: '90vw'
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'rgba(13, 17, 23, 0.8)';
          e.currentTarget.style.borderColor = 'var(--color-primary-hover)';
          e.currentTarget.style.color = 'var(--color-text)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'rgba(13, 17, 23, 0.6)';
          e.currentTarget.style.borderColor = 'rgba(30, 42, 58, 0.6)';
          e.currentTarget.style.color = 'var(--color-text-muted)';
        }}
      >
        <Search size={14} />
        <span>Type a command or search...</span>
        <span style={{ 
          marginLeft: 'auto', 
          fontSize: '11px', 
          background: 'rgba(255,255,255,0.05)', 
          padding: '2px 6px', 
          borderRadius: '4px' 
        }}>Ctrl K</span>
      </button>
    </header>
  );
}

export default Header;
