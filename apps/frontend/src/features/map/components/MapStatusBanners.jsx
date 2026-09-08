import PropTypes from 'prop-types';
import { X } from 'lucide-react';

/**
 * Status banners shown above the map canvas.
 *
 * They are exported separately rather than as one component because they
 * render at different points in the page, and collapsing them into a single
 * element would change the DOM order.
 */

/**
 * Prompts the user to review devices found by a discovery scan.
 * Renders nothing when there is no pending scan.
 */
export function ScanImportBanner({ pending, onReview, onDismiss }) {
  if (!pending) return null;

  return (
    <div className="scan-import-banner">
      <span>
        🔍 {pending.newCount} new device{pending.newCount !== 1 ? 's' : ''} discovered
      </span>
      <button className="btn-link" onClick={onReview}>
        Review &amp; Import →
      </button>
      <button className="btn-icon" onClick={onDismiss} aria-label="Dismiss">
        ×
      </button>
    </div>
  );
}

ScanImportBanner.propTypes = {
  pending: PropTypes.shape({
    scanId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
    newCount: PropTypes.number,
    results: PropTypes.array,
  }),
  onReview: PropTypes.func.isRequired,
  onDismiss: PropTypes.func.isRequired,
};

/**
 * Topology load failure. Dismissing it also retries the fetch, which is why
 * the handler is `onRetry` rather than `onDismiss`.
 */
export function MapErrorBanner({ error, onRetry }) {
  if (!error) return null;

  return (
    <div
      style={{
        background: 'rgba(243,139,168,0.15)',
        border: '1px solid #f38ba8',
        color: '#f38ba8',
        padding: '6px 12px',
        fontSize: 12,
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
      }}
    >
      <span>{error}</span>
      <button
        onClick={onRetry}
        aria-label="Dismiss error and retry"
        style={{ background: 'none', border: 'none', color: '#f38ba8', cursor: 'pointer' }}
      >
        <X size={14} />
      </button>
    </div>
  );
}

MapErrorBanner.propTypes = {
  error: PropTypes.string,
  onRetry: PropTypes.func.isRequired,
};
