/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState, useEffect, useRef, useCallback } from 'react';
import PropTypes from 'prop-types';
import { catalogApi } from '../api/client';

/**
 * CatalogSearch — typeahead input that queries the vendor device catalog.
 *
 * Props:
 *   value        {string}   current name/query value
 *   onChange     {fn}       called on raw text change: (newValue) => void
 *   onSelect     {fn}       called when user picks a result:
 *                             (result) => void
 *                           result shape:
 *                             { vendor_key, model_key, vendor_label, device_label,
 *                               icon, u_height, role, telemetry_profile, _freeform }
 *   placeholder  {string}
 *   disabled     {bool}
 */
function CatalogSearch({
  value = '',
  onChange,
  onSelect,
  placeholder = 'Search devices or type a name…',
  disabled = false,
}) {
  const [query, setQuery] = useState(value);
  const [results, setResults] = useState([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);
  const debounceRef = useRef(null);
  const containerRef = useRef(null);

  // Sync controlled value
  useEffect(() => {
    setQuery(value);
  }, [value]);

  // Debounced search
  const search = useCallback((q) => {
    if (!q.trim()) {
      setResults([]);
      setOpen(false);
      return;
    }
    setLoading(true);
    catalogApi
      .search(q)
      .then((data) => {
        setResults(data);
        setOpen(true);
        setActiveIdx(-1);
      })
      .catch(() => {
        setResults([]);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleChange = (e) => {
    const val = e.target.value;
    setQuery(val);
    onChange?.(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(val), 280);
  };

  const handleSelect = (result) => {
    if (result._freeform) {
      onChange?.(result.device_label);
      onSelect?.({ ...result, name: result.device_label });
    } else {
      onChange?.(result.device_label);
      onSelect?.(result);
    }
    setQuery(result.device_label);
    setOpen(false);
  };

  const handleKeyDown = (e) => {
    if (!open || !results.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && activeIdx >= 0) {
      e.preventDefault();
      handleSelect(results[activeIdx]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <div ref={containerRef} style={{ position: 'relative' }}>
      <input
        type="text"
        className="input"
        value={query}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        onFocus={() => query.trim() && results.length && setOpen(true)}
        placeholder={placeholder}
        disabled={disabled}
        autoComplete="off"
        style={{ width: '100%' }}
      />
      {loading && (
        <span
          style={{
            position: 'absolute',
            right: 10,
            top: '50%',
            transform: 'translateY(-50%)',
            fontSize: 11,
            color: 'var(--color-text-muted)',
          }}
        >
          …
        </span>
      )}
      {open && results.length > 0 && (
        <div
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            right: 0,
            zIndex: 500,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            marginTop: 4,
            maxHeight: 280,
            overflowY: 'auto',
            boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
          }}
        >
          {results.map((r, idx) => {
            const isFreeform = r._freeform;
            const isActive = idx === activeIdx;
            return (
              <button
                key={isFreeform ? '__freeform' : `${r.vendor_key}::${r.model_key}`}
                onMouseDown={(e) => {
                  e.preventDefault();
                  handleSelect(r);
                }}
                onMouseEnter={() => setActiveIdx(idx)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  width: '100%',
                  padding: '8px 12px',
                  border: 'none',
                  cursor: 'pointer',
                  background: isActive ? 'rgba(0,212,255,0.08)' : 'transparent',
                  color: 'var(--color-text)',
                  textAlign: 'left',
                  fontFamily: 'inherit',
                  fontSize: 13,
                  borderTop: idx > 0 ? '1px solid rgba(255,255,255,0.05)' : 'none',
                }}
              >
                {!isFreeform && r.icon ? (
                  <img
                    src={`/icons/vendors/${r.icon}`}
                    alt=""
                    width={18}
                    height={18}
                    style={{ objectFit: 'contain', flexShrink: 0 }}
                    onError={(e) => {
                      e.target.style.display = 'none';
                    }}
                  />
                ) : (
                  <span style={{ width: 18, flexShrink: 0, textAlign: 'center', fontSize: 14 }}>
                    {isFreeform ? '+' : ''}
                  </span>
                )}
                <span>
                  {isFreeform ? (
                    <span style={{ color: 'var(--color-primary)' }}>
                      Add &ldquo;{r.device_label}&rdquo; as custom device
                    </span>
                  ) : (
                    <>
                      <span style={{ fontWeight: 500 }}>{r.device_label}</span>
                      {r.vendor_label && (
                        <span
                          style={{ color: 'var(--color-text-muted)', marginLeft: 6, fontSize: 11 }}
                        >
                          {r.vendor_label}
                        </span>
                      )}
                      {r.role && (
                        <span
                          style={{
                            color: 'var(--color-text-muted)',
                            marginLeft: 6,
                            fontSize: 10,
                            background: 'rgba(255,255,255,0.06)',
                            borderRadius: 4,
                            padding: '1px 5px',
                          }}
                        >
                          {r.role}
                        </span>
                      )}
                    </>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

CatalogSearch.propTypes = {
  value: PropTypes.string,
  onChange: PropTypes.func,
  onSelect: PropTypes.func,
  placeholder: PropTypes.string,
  disabled: PropTypes.bool,
};

export default CatalogSearch;
