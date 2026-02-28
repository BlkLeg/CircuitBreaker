import React, { createContext, useContext, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';

// ── Context ───────────────────────────────────────────────────────────────────

const ToastContext = createContext(null);

let _nextId = 0;

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef({});

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
    if (timers.current[id]) {
      clearTimeout(timers.current[id]);
      delete timers.current[id];
    }
  }, []);

  const addToast = useCallback((message, variant = 'info') => {
    const id = ++_nextId;
    const duration = variant === 'error' ? 8000 : 5000;
    setToasts((prev) => [...prev, { id, message, variant }]);
    timers.current[id] = setTimeout(() => dismiss(id), duration);
    return id;
  }, [dismiss]);

  const toast = {
    success: (msg) => addToast(msg, 'success'),
    error:   (msg) => addToast(msg, 'error'),
    warn:    (msg) => addToast(msg, 'warn'),
    info:    (msg) => addToast(msg, 'info'),
  };

  return (
    <ToastContext.Provider value={toast}>
      {children}
      {createPortal(
        <ToastStack toasts={toasts} onDismiss={dismiss} />,
        document.body,
      )}
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used inside <ToastProvider>');
  return ctx;
}

// ── Toast Stack UI ────────────────────────────────────────────────────────────

const VARIANT_STYLES = {
  success: { bg: 'var(--color-surface)', border: '#2ecc71', icon: '\u2713', color: '#2ecc71' },
  error:   { bg: 'var(--color-surface)', border: '#e74c3c', icon: '\u2715', color: '#e74c3c' },
  warn:    { bg: 'var(--color-surface)', border: '#f39c12', icon: '\u26a0', color: '#f39c12' },
  info:    { bg: 'var(--color-surface)', border: '#3498db', icon: '\u2139', color: '#3498db' },
};

function ToastStack({ toasts, onDismiss }) {
  return (
    <div
      style={{
        position: 'fixed',
        top: 16,
        right: 16,
        zIndex: 9999,
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        maxWidth: 380,
        pointerEvents: 'none',
      }}
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastItem({ toast, onDismiss }) {
  const s = VARIANT_STYLES[toast.variant] || VARIANT_STYLES.info;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: 10,
        background: s.bg,
        border: `1px solid ${s.border}`,
        borderLeft: `4px solid ${s.border}`,
        borderRadius: 8,
        padding: '10px 12px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.5)',
        pointerEvents: 'all',
        animation: 'toast-in 0.2s ease',
      }}
    >
      <span style={{ color: s.color, fontWeight: 700, fontSize: 14, lineHeight: '20px', flexShrink: 0 }}>
        {s.icon}
      </span>
      <span style={{ flex: 1, fontSize: 13, lineHeight: '20px', color: 'var(--color-text, #e0e0e0)', wordBreak: 'break-word' }}>
        {toast.message}
      </span>
      <button
        onClick={() => onDismiss(toast.id)}
        style={{
          background: 'none',
          border: 'none',
          color: 'var(--color-text-muted, #888)',
          cursor: 'pointer',
          fontSize: 16,
          lineHeight: 1,
          padding: '0 2px',
          flexShrink: 0,
        }}
        aria-label="Dismiss notification"
      >
        ×
      </button>
    </div>
  );
}

export default ToastProvider;
