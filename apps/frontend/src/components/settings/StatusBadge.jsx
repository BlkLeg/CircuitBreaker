import React from 'react';
import PropTypes from 'prop-types';

function StatusBadge({ ok, labelOk = 'Connected', labelNo = 'Unavailable' }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontSize: 11,
        fontWeight: 600,
        padding: '2px 8px',
        borderRadius: 20,
        background: ok ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.1)',
        color: ok ? '#22c55e' : '#ef4444',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: ok ? '#22c55e' : '#ef4444',
          flexShrink: 0,
        }}
      />
      {ok ? labelOk : labelNo}
    </span>
  );
}

StatusBadge.propTypes = {
  ok: PropTypes.bool.isRequired,
  labelOk: PropTypes.string,
  labelNo: PropTypes.string,
};

export default StatusBadge;
