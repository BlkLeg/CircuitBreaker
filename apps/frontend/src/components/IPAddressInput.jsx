import React, { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { CheckCircle, AlertTriangle, Loader } from 'lucide-react';
import { ipCheckApi, servicesApi } from '../api/client';
import IPConflictBanner from './IPConflictBanner';
import IpStatusBadge from './IpStatusBadge';

const DEBOUNCE_MS = 600;

/**
 * Decode "cu_1" → { computeId: 1, hardwareId: null }
 * Decode "hw_2" → { computeId: null, hardwareId: 2 }
 */
function decodeRunsOn(runsOnValue) {
  if (!runsOnValue) return { computeId: null, hardwareId: null };
  if (String(runsOnValue).startsWith('cu_'))
    return { computeId: parseInt(runsOnValue.slice(3), 10), hardwareId: null };
  if (String(runsOnValue).startsWith('hw_'))
    return { computeId: null, hardwareId: parseInt(runsOnValue.slice(3), 10) };
  return { computeId: null, hardwareId: null };
}

/**
 * Controlled IP address input with built-in real-time conflict detection.
 *
 * For services (entityType === 'service'), uses /services/check-ip which is
 * host-chain-aware and distinguishes inherited IPs from real conflicts.
 *
 * Exposes `hasConflicts()` via ref so the parent form can block submission.
 */
const IPAddressInput = forwardRef(function IPAddressInput(
  {
    value,
    onChange,
    entityType,
    entityId,
    ports,
    disabled,
    onOpenEntity,
    name,
    placeholder,
    id,
    runsOnValue,
  },
  ref
) {
  const isServiceCheck = entityType === 'service';

  // State for non-service checks (original)
  const [conflicts, setConflicts] = useState([]);
  // State for service checks (new)
  const [ipMode, setIpMode] = useState('explicit');
  const [conflictWith, setConflictWith] = useState([]);
  const [isConflict, setIsConflict] = useState(false);

  const [checking, setChecking] = useState(false);
  const [checked, setChecked] = useState(false);
  const [flashBanner, setFlashBanner] = useState(false);
  const timerRef = useRef(null);
  const lastCheckedRef = useRef(null);

  useImperativeHandle(ref, () => ({
    hasConflicts: () => (isServiceCheck ? isConflict : conflicts.length > 0),
    flashConflicts: () => {
      const hasAny = isServiceCheck ? isConflict : conflicts.length > 0;
      if (hasAny) {
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
      setIpMode('explicit');
      setConflictWith([]);
      setIsConflict(false);
      setChecked(false);
      setChecking(false);
      return;
    }

    timerRef.current = setTimeout(async () => {
      const cacheKey = `${trimmed}|${JSON.stringify(ports || [])}|${entityType}|${entityId}|${runsOnValue ?? ''}`;
      if (cacheKey === lastCheckedRef.current) return;
      lastCheckedRef.current = cacheKey;

      setChecking(true);
      try {
        if (isServiceCheck) {
          const { computeId, hardwareId } = decodeRunsOn(runsOnValue);
          const res = await servicesApi.checkIp({
            ip_address: trimmed,
            compute_id: computeId,
            hardware_id: hardwareId,
            exclude_service_id: entityId || null,
          });
          setIpMode(res.data.ip_mode || 'explicit');
          setConflictWith(res.data.conflict_with || []);
          setIsConflict(res.data.is_conflict || false);
        } else {
          const res = await ipCheckApi.check({
            ip: trimmed,
            ports: ports || undefined,
            exclude_entity_type: entityType || undefined,
            exclude_entity_id: entityId || undefined,
          });
          setConflicts(res.data.conflicts || []);
        }
        setChecked(true);
      } catch {
        // silently ignore check failures — the API backstop catches real conflicts on submit
        setConflicts([]);
        setIpMode('explicit');
        setConflictWith([]);
        setIsConflict(false);
        setChecked(false);
      } finally {
        setChecking(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timerRef.current);
  }, [value, ports, entityType, entityId, runsOnValue, isServiceCheck]);

  const hasAnyConflict = isServiceCheck ? isConflict : conflicts.length > 0;

  const statusIcon = (() => {
    if (checking)
      return (
        <Loader
          size={14}
          style={{
            color: 'var(--color-text-muted, #9ca3af)',
            animation: 'spin 1s linear infinite',
          }}
        />
      );
    if (!checked || !(value || '').trim()) return null;
    if (hasAnyConflict) return <AlertTriangle size={14} style={{ color: '#f59e0b' }} />;
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
          <span
            style={{
              position: 'absolute',
              right: 9,
              display: 'flex',
              alignItems: 'center',
              pointerEvents: 'none',
            }}
          >
            {statusIcon}
          </span>
        )}
      </div>
      {isServiceCheck ? (
        <IpStatusBadge
          ipMode={ipMode}
          conflictWith={conflictWith}
          flash={flashBanner}
          onOpenEntity={onOpenEntity}
        />
      ) : (
        <IPConflictBanner conflicts={conflicts} onOpenEntity={onOpenEntity} flash={flashBanner} />
      )}
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
  runsOnValue: PropTypes.string,
};

export default IPAddressInput;
