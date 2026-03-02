import React, { useState, useRef, createRef } from 'react';
import PropTypes from 'prop-types';
import { getIconEntry } from './common/IconPickerModal';
import { getOsOption } from '../icons/osOptions';
import { CPU_BRAND_MAP } from '../config/cpuBrands';
import { slugify } from '../utils/slugify';
import CatalogSearch from './CatalogSearch';
import CategoryCombobox from './common/CategoryCombobox';
import EnvironmentCombobox from './common/EnvironmentCombobox';
import IPAddressInput from './IPAddressInput';
import PortsEditor from './PortsEditor';

function EntityForm({ fields, initialValues = {}, onSubmit, onCancel, onDirtyChange, apiErrors = {}, onValidate, entityType, entityId, onOpenEntity }) {
  // Refs for IPAddressInput fields so we can call hasConflicts() on submit
  const ipInputRefsRef = useRef({});

  // eslint-disable-next-line react-naming-convention/use-state -- wrapper needed for dirty tracking
  const [values, setValuesInternal] = useState(() => {
    const init = { ...initialValues };
    fields.forEach((f) => {
      if (f.type === 'tags' && Array.isArray(init[f.name])) {
        init[f.name] = init[f.name].join(', ');
      }
    });
    return init;
  });
  // Track which slug fields have been manually edited (dirty)
  const [slugDirtyFields, setSlugDirtyFields] = useState(() => {
    // When editing an existing record, slug is already set — treat as dirty so it won't auto-reset
    const dirty = {};
    fields.forEach((f) => {
      if (f.type === 'slug' && initialValues[f.name]) dirty[f.name] = true;
    });
    return dirty;
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

  const [clearedApiErrors, setClearedApiErrors] = React.useState({});
  const [validationErrors, setValidationErrors] = React.useState({});

  const setValues = (updater) => {
    setValuesInternal((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater;
      const dirty = JSON.stringify(next) !== initialRef.current;
      onDirtyChange?.(dirty);
      return next;
    });
  };

  const handleIconChange = (fieldName, newSlug) => {
    setValues((prev) => ({ ...prev, [fieldName]: newSlug }));
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
    // Clear any API/Validation error for this field when the user edits it
    setClearedApiErrors((prev) => ({ ...prev, [name]: true }));
    setValidationErrors((prev) => ({ ...prev, [name]: null }));
    
    setValues((prev) => {
      const next = { ...prev, [name]: coerced };
      // Auto-update any un-dirty slug fields that watch this field
      fields.forEach((f) => {
        if (f.type === 'slug' && f.slugSource === name && !slugDirtyFields[f.name]) {
          next[f.name] = slugify(String(coerced ?? ''));
        }
      });
      return next;
    });
  };

  // Slug field own-change: mark it dirty so auto-update stops
  const handleSlugChange = (e) => {
    const { name, value } = e.target;
    setSlugDirtyFields((prev) => ({ ...prev, [name]: true }));
    setValidationErrors((prev) => ({ ...prev, [name]: null }));
    setClearedApiErrors((prev) => ({ ...prev, [name]: true }));
    setValues((prev) => ({ ...prev, [name]: value }));
  };

  const handleResetSlug = (fieldName, sourceFieldName) => {
    setSlugDirtyFields((prev) => ({ ...prev, [fieldName]: false }));
    setValidationErrors((prev) => ({ ...prev, [fieldName]: null }));
    setClearedApiErrors((prev) => ({ ...prev, [fieldName]: true }));
    setValues((prev) => ({ ...prev, [fieldName]: slugify(String(prev[sourceFieldName] ?? '')) }));
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

    if (onValidate) {
      const errors = onValidate(submitted);
      if (errors && Object.keys(errors).length > 0) {
        setValidationErrors(errors);
        return; // Block submission
      }
    }

    // Block submit if any IPAddressInput has active conflicts
    let hasIpConflict = false;
    for (const ref of Object.values(ipInputRefsRef.current)) {
      if (ref?.current?.hasConflicts?.()) {
        ref.current.flashConflicts?.();
        hasIpConflict = true;
      }
    }
    if (hasIpConflict) return;

    onSubmit(submitted);
  };

  const renderField = (field) => {
    // ── IP address input with conflict detection ──────────────────────────────
    if (field.type === 'ip-address-input') {
      if (!ipInputRefsRef.current[field.name]) {
        ipInputRefsRef.current[field.name] = createRef();
      }
      // For services: find the ports field value to pass along
      const portsFieldName = field.portsFieldName || 'ports';
      const portsValue = values[portsFieldName];
      return (
        <IPAddressInput
          ref={ipInputRefsRef.current[field.name]}
          id={field.name}
          name={field.name}
          value={values[field.name] ?? ''}
          onChange={(e) => {
            setClearedApiErrors((prev) => ({ ...prev, [field.name]: true }));
            setValidationErrors((prev) => ({ ...prev, [field.name]: null }));
            setValues((prev) => ({ ...prev, [field.name]: e.target.value }));
          }}
          entityType={field.entityType || entityType}
          entityId={field.entityId !== undefined ? field.entityId : entityId}
          ports={Array.isArray(portsValue) ? portsValue : undefined}
          disabled={field.disabled}
          placeholder={field.placeholder}
          onOpenEntity={onOpenEntity}
        />
      );
    }

    // ── Ports editor (structured port bindings) ───────────────────────────────
    if (field.type === 'ports-editor') {
      const ipFieldName = field.ipFieldName || 'ip_address';
      return (
        <PortsEditor
          value={values[field.name]}
          onChange={(newPorts) => {
            setClearedApiErrors((prev) => ({ ...prev, [field.name]: true }));
            setValidationErrors((prev) => ({ ...prev, [field.name]: null }));
            setValues((prev) => ({ ...prev, [field.name]: newPorts }));
          }}
          entityType={field.entityType || entityType}
          entityId={field.entityId !== undefined ? field.entityId : entityId}
          serviceIp={values[ipFieldName]}
          onOpenEntity={onOpenEntity}
        />
      );
    }

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

    // ── CPU brand select with icon preview ────────────────────────────────────
    if (field.type === 'cpu-select') {
      const brand = CPU_BRAND_MAP[values[field.name]];
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {brand && <img src={brand.icon} alt={brand.label} width={18} height={18} style={{ objectFit: 'contain', flexShrink: 0 }} onError={(e) => { e.target.style.display = 'none'; }} />}
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
            onClick={() => field.onOpenPicker?.(slug, (newSlug) => handleIconChange(field.name, newSlug))}
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

    // ── Category combobox (search/create against /categories) ──────────────
    if (field.type === 'category-combobox') {
      return (
        <CategoryCombobox
          value={values[field.name] ?? null}
          onChange={(id) => {
            setClearedApiErrors((prev) => ({ ...prev, [field.name]: true }));
            setValidationErrors((prev) => ({ ...prev, [field.name]: null }));
            setValues((prev) => ({ ...prev, [field.name]: id }));
          }}
        />
      );
    }

    // ── Environment combobox (search/create against /environments) ───────────
    if (field.type === 'environment-combobox') {
      return (
        <EnvironmentCombobox
          value={values[field.name] ?? null}
          onChange={(id) => {
            setClearedApiErrors((prev) => ({ ...prev, [field.name]: true }));
            setValidationErrors((prev) => ({ ...prev, [field.name]: null }));
            setValues((prev) => ({ ...prev, [field.name]: id }));
          }}
        />
      );
    }

    // ── Catalog typeahead (name + auto-fill vendor/model/u_height/role) ───────
    if (field.type === 'catalog-search') {
      return (
        <CatalogSearch
          value={values[field.name] ?? ''}
          onChange={(val) => {
            setClearedApiErrors((prev) => ({ ...prev, [field.name]: true }));
            setValidationErrors((prev) => ({ ...prev, [field.name]: null }));
            setValues((prev) => ({ ...prev, [field.name]: val }));
          }}
          onSelect={(result) => {
            field.onSelect?.(result, (updates) => {
              setValues((prev) => ({ ...prev, ...updates }));
            });
          }}
          placeholder={field.placeholder}
          disabled={field.disabled}
        />
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

    // ── Slug field with auto-generation ──────────────────────────────────────
    if (field.type === 'slug') {
      const isDirty = !!slugDirtyFields[field.name];
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            id={field.name}
            type="text"
            name={field.name}
            value={values[field.name] ?? ''}
            onChange={handleSlugChange}
            required={field.required}
            style={{ flex: 1, fontFamily: 'monospace', fontSize: 12 }}
          />
          {isDirty && field.slugSource && (
            <button
              type="button"
              className="btn btn-sm"
              title="Re-generate from name"
              onClick={() => handleResetSlug(field.name, field.slugSource)}
              style={{ flexShrink: 0, fontSize: 11 }}
            >
              ↺
            </button>
          )}
        </div>
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
      {fields.map((field) => {
        const apiErr = !clearedApiErrors[field.name] ? apiErrors[field.name] : null;
        const validErr = validationErrors[field.name];
        const errorMsg = validErr || apiErr;
        
        return (
          <div key={field.name} className="form-group">
            <label htmlFor={field.name}>{field.label}</label>
            {renderField(field)}
            {field.hint && <p className="form-hint">{field.hint}</p>}
            {errorMsg && (
              <p style={{ margin: '4px 0 0', fontSize: 12, color: '#e74c3c' }}>{errorMsg}</p>
            )}
          </div>
        );
      })}
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

EntityForm.propTypes = {
  fields: PropTypes.arrayOf(
    PropTypes.shape({
      name: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      type: PropTypes.string,
      options: PropTypes.arrayOf(
        PropTypes.shape({
          value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
          label: PropTypes.string.isRequired,
        })
      ),
      required: PropTypes.bool,
      hint: PropTypes.string,
      onOpenPicker: PropTypes.func,
      // ip-address-input / ports-editor specific
      entityType: PropTypes.string,
      entityId: PropTypes.number,
      portsFieldName: PropTypes.string,
      ipFieldName: PropTypes.string,
    })
  ).isRequired,
  initialValues: PropTypes.object,
  onSubmit: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
  onDirtyChange: PropTypes.func,
  apiErrors: PropTypes.object,
  onValidate: PropTypes.func,
  entityType: PropTypes.string,
  entityId: PropTypes.number,
  onOpenEntity: PropTypes.func,
};

export default EntityForm;
