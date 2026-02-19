import React, { useState, useEffect, useRef } from 'react';
import { getIconEntry } from './common/IconPickerModal';
import { getOsOption } from '../icons/osOptions';

function EntityForm({ fields, initialValues = {}, onSubmit, onCancel, onDirtyChange }) {
  const [values, _setValues] = useState(() => {
    const init = { ...initialValues };
    fields.forEach((f) => {
      if (f.type === 'tags' && Array.isArray(init[f.name])) {
        init[f.name] = init[f.name].join(', ');
      }
    });
    return init;
  });
  const initialRef = useRef(null);
  // Capture a comparable snapshot of initial values once
  if (initialRef.current === null) {
    const snap = { ...initialValues };
    fields.forEach((f) => {
      if (f.type === 'tags' && Array.isArray(snap[f.name])) snap[f.name] = snap[f.name].join(', ');
    });
    initialRef.current = JSON.stringify(snap);
  }

  const setValues = (updater) => {
    _setValues((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      const dirty = JSON.stringify(next) !== initialRef.current;
      onDirtyChange?.(dirty);
      return next;
    });
  };

  const handleChange = (e) => {
    const { name, value, type } = e.target;
    let coerced;
    if (type === 'number') {
      coerced = value === '' ? null : Number(value);
    } else if (type === 'select-one') {
      coerced = value === '' ? null : value;
    } else {
      coerced = value;
    }
    setValues((prev) => ({ ...prev, [name]: coerced }));
  };


  const handleSubmit = (e) => {
    e.preventDefault();
    const submitted = { ...values };
    fields.forEach((f) => {
      if (f.type === 'tags') {
        submitted[f.name] = submitted[f.name]
          ? submitted[f.name].split(',').map((t) => t.trim()).filter(Boolean)
          : [];
      }
    });
    onSubmit(submitted);
  };

  const renderField = (field) => {
    // ── OS select with icon preview ───────────────────────────────────────────
    if (field.type === 'os-select') {
      const opt = getOsOption(values[field.name]);
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {opt && <img src={opt.icon} alt={opt.label} width={18} height={18} style={{ objectFit: 'contain', flexShrink: 0 }} onError={(e) => { e.target.style.display = 'none'; }} />}
          <select id={field.name} name={field.name} value={values[field.name] ?? ''} onChange={handleChange} style={{ flex: 1 }}>
            <option value="">-- select --</option>
            {field.options.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
        </div>
      );
    }

    // ── Icon picker chip ──────────────────────────────────────────────────────
    if (field.type === 'icon-picker') {
      const slug = values[field.name];
      const entry = getIconEntry(slug);
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {slug ? (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'var(--color-bg)', border: '1px solid var(--color-border)',
              borderRadius: 6, padding: '5px 10px',
            }}>
              <img
                src={entry?.path ?? '/icons/vendors/generic.svg'}
                alt={entry?.label ?? slug}
                width={22} height={22} style={{ objectFit: 'contain' }}
                onError={(e) => { e.target.src = '/icons/vendors/generic.svg'; }}
              />
              <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{entry?.label ?? slug}</span>
            </div>
          ) : (
            <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>No icon selected</span>
          )}
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => field.onOpenPicker?.(slug, (newSlug) => setValues((prev) => ({ ...prev, [field.name]: newSlug })))}
          >
            {slug ? 'Change icon' : 'Choose icon'}
          </button>
          {slug && (
            <button type="button" className="btn btn-sm btn-danger" onClick={() => setValues((prev) => ({ ...prev, [field.name]: null }))}>
              ✕
            </button>
          )}
        </div>
      );
    }

    // ── standard select ───────────────────────────────────────────────────────
    if (field.type === 'select') {
      return (
        <select id={field.name} name={field.name} value={values[field.name] ?? ''} onChange={handleChange}>
          <option value="">-- select --</option>
          {field.options.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      );
    }

    if (field.type === 'textarea') {
      return (
        <textarea id={field.name} name={field.name} value={values[field.name] ?? ''} onChange={handleChange} rows={4} />
      );
    }

    return (
      <input
        id={field.name}
        type={field.type === 'tags' ? 'text' : (field.type || 'text')}
        name={field.name}
        value={values[field.name] ?? ''}
        onChange={handleChange}
        required={field.required}
        placeholder={field.type === 'tags' ? 'e.g. prod, storage' : undefined}
      />
    );
  };

  return (
    <form className="entity-form" onSubmit={handleSubmit}>
      {fields.map((field) => (
        <div key={field.name} className="form-group">
          <label htmlFor={field.name}>{field.label}</label>
          {renderField(field)}
          {field.hint && <p className="form-hint">{field.hint}</p>}
        </div>
      ))}
      <div className="form-actions">
        <button type="submit" className="btn btn-primary">
          {initialValues.id ? 'Update' : 'Create'}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}

export default EntityForm;
