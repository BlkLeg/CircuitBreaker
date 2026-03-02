import React from 'react';
import * as Sentry from '@sentry/react';

/**
 * Catches unexpected render-phase errors for the wrapped subtree and shows a
 * friendly fallback instead of a blank screen.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <MyComponent />
 *   </ErrorBoundary>
 */
class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    // Log to the browser console so devs can see the full stack
    console.error('[ErrorBoundary] Uncaught render error:', error, info);
    Sentry.captureException(error, { contexts: { react: { componentStack: info.componentStack } } });
  }

  handleReload = () => {
    // Reset state so the tree can try re-mounting after a fix
    this.setState({ hasError: false, error: null });
    window.location.reload();
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: 16,
          padding: 32,
          textAlign: 'center',
        }}
      >
        <span style={{ fontSize: 48 }}>⚠️</span>
        <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600, color: 'var(--color-text, #e0e0e0)' }}>
          Something went wrong
        </h2>
        <p style={{ margin: 0, color: 'var(--color-text-muted, #888)', maxWidth: 420, fontSize: 14 }}>
          An unexpected error occurred while rendering this page. You can try
          reloading — your data is safe.
        </p>
        {this.state.error && (
          <pre
            style={{
              background: 'var(--color-surface, #1a1a1a)',
              border: '1px solid var(--color-border, #333)',
              borderRadius: 8,
              padding: '12px 16px',
              fontSize: 12,
              color: '#e74c3c',
              maxWidth: 540,
              overflow: 'auto',
              textAlign: 'left',
            }}
          >
            {this.state.error.message}
          </pre>
        )}
        <button
          className="btn btn-primary"
          onClick={this.handleReload}
          style={{ marginTop: 8 }}
        >
          Reload page
        </button>
      </div>
    );
  }
}

export default ErrorBoundary;
