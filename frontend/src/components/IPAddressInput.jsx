import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { CheckCircle, AlertTriangle, Loader } from 'lucide-react';
import { ipCheckApi } from '../api/client';
import IPConflictBanner from './IPConflictBanner';

const DEBOUNCE_MS = 600;

/**
 * Controlled IP address input with built-in real-time conflict detection.
 *
 * Exposes `hasConflicts()` via ref so the parent form can block submission.
 */
const IPAddressInput = forwardRef(function IPAddressInput(
  { value, onChange, entityType, entityId, ports, disabled, onOpenEntity, name, placeholder, id },
  ref
) {
  const [conflicts, setConflicts] = useState([]);
  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);
  const [flashBanner, setFlashBanner] = useState(false);
  const timerRef = useRef(null);
  const lastCheckedRef = useRef(null);

  useImperativeHandle(ref, () => ({
    hasConflicts: () => conflicts.length > 0,
    flashConflicts: () => {
      if (conflicts.length > 0) {
        setFlashBanner(true);
        setTimeout(() => setFlashBanner(false), 900);
      }
    },
  }));

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);

    const trimmed = (value || '').trim();
    if (!trimmed) {
      setConflicts([]);
      setChecked(false);
      setChecking(false);
      return;
    }

    timerRef.current = setTimeout(async () => {
      const cacheKey = `${trimmed}|${JSON.stringify(ports || [])}|${entityType}|${entityId}`;
      if (cacheKey === lastCheckedRef.current) return;
      lastCheckedRef.current = cacheKey;

      setChecking(true);
      try {
        const res = await ipCheckApi.check({
          ip: trimmed,
          ports: ports || undefined,
          exclude_entity_type: entityType || undefined,
          exclude_entity_id: entityId || undefined,
        });
        setConflicts(res.data.conflicts || []);
        setChecked(true);
      } catch {
        // silently ignore check failures — the API backstop will catch real conflicts on submit
        setConflicts([]);
        setChecked(false);
      } finally {
        setChecking(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timerRef.current);
  }, [value, ports, entityType, entityId]);

  const statusIcon = (() => {
    if (checking) return <Loader size={14} style={{ color: 'var(--color-text-muted, #9ca3af)', animation: 'spin 1s linear infinite' }} />;
    if (!checked || !(value || '').trim()) return null;
    if (conflicts.length > 0) return <AlertTriangle size={14} style={{ color: '#f59e0b' }} />;
    return <CheckCircle size={14} style={{ color: '#22c55e' }} />;
  })();

  return (
    <div>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'center' }}>
        <input
          id={id}
          type="text"
          name={name}
          value={value ?? ''}
          onChange={onChange}
          disabled={disabled}
          placeholder={placeholder}
          style={{ paddingRight: statusIcon ? 30 : undefined, width: '100%' }}
        />
        {statusIcon && (
          <span style={{
            position: 'absolute',
            right: 9,
            display: 'flex',
            alignItems: 'center',
            pointerEvents: 'none',
          }}>
            {statusIcon}
          </span>
        )}
      </div>
      <IPConflictBanner
        conflicts={conflicts}
        onOpenEntity={onOpenEntity}
        flash={flashBanner}
      />
    </div>
  );
});

IPAddressInput.propTypes = {
  value: PropTypes.string,
  onChange: PropTypes.func.isRequired,
  entityType: PropTypes.string,
  entityId: PropTypes.number,
  ports: PropTypes.array,
  disabled: PropTypes.bool,
  onOpenEntity: PropTypes.func,
  name: PropTypes.string,
  placeholder: PropTypes.string,
  id: PropTypes.string,
};

export default IPAddressInput;
