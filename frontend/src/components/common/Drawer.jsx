import React, { useEffect } from 'react';
import { X } from 'lucide-react';

function Drawer({ isOpen, onClose, title, children, width = '500px' }) {
  useEffect(() => {
    const handleEsc = (e) => {
      if (e.key === 'Escape') onClose();
    };
    if (isOpen) window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <>
      <div 
        className="drawer-overlay" 
        onClick={onClose}
        style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0, 0, 0, 0.5)',
          zIndex: 90,
          backdropFilter: 'blur(2px)'
        }}
      />
      <div 
        className="drawer"
        style={{
          position: 'fixed',
          top: 0,
          right: 0,
          bottom: 0,
          width: width,
          maxWidth: '100vw',
          background: 'var(--color-bg)',
          borderLeft: '1px solid var(--color-border)',
          zIndex: 100,
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '-4px 0 24px rgba(0,0,0,0.3)',
          transition: 'transform 0.3s ease-in-out',
          animation: 'slideIn 0.3s ease-out'
        }}
      >
        <div className="drawer-header" style={{
          padding: '16px 20px',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--color-bg-subtle)'
        }}>
          <h3 style={{ margin: 0, fontSize: '1.1rem', fontWeight: 600 }}>{title}</h3>
          <button 
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--color-text-muted)',
              cursor: 'pointer',
              padding: 4
            }}
          >
            <X size={20} />
          </button>
        </div>
        <div className="drawer-content" style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px'
        }}>
          {children}
        </div>
      </div>
      <style>{`
        @keyframes slideIn {
          from { transform: translateX(100%); }
          to { transform: translateX(0); }
        }
      `}</style>
    </>
  );
}

export default Drawer;
