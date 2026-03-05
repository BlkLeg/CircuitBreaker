import React, { useState } from 'react';
import PropTypes from 'prop-types';

/**
 * ListEditor – manages an ordered list of strings with add/remove.
 * Props:
 *   items      {string[]}          current list
 *   onChange   (string[]) => void  called with new list on any change
 *   placeholder {string}           input placeholder text
 */
function ListEditor({ items = [], onChange, placeholder = 'Add item…' }) {
  const [input, setInput] = useState('');

  const add = () => {
    const v = input.trim();
    if (v && !items.includes(v)) {
      onChange([...items, v]);
      setInput('');
    }
  };

  const remove = (item) => onChange(items.filter((i) => i !== item));

  return (
    <div style={{ marginTop: 8 }}>
      {/* Pill list */}
      {items.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
          {items.map((item) => (
            <span
              key={item}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 4,
                padding: '2px 10px 2px 10px',
                borderRadius: 99,
                fontSize: 12,
                fontWeight: 500,
                background: 'var(--color-glow)',
                border: '1px solid var(--color-primary)',
                color: 'var(--color-primary)',
              }}
            >
              {item}
              <button
                type="button"
                onClick={() => remove(item)}
                style={{
                  marginLeft: 2,
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  fontSize: 14,
                  lineHeight: 1,
                  padding: '0 0 1px 0',
                  display: 'flex',
                  alignItems: 'center',
                }}
                aria-label={`Remove ${item}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Add row */}
      <div style={{ display: 'flex', gap: 8 }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
          style={{
            flex: 1,
            fontSize: 13,
            background: 'var(--color-bg)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
            borderRadius: 4,
            padding: '6px 10px',
          }}
        />
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={add}
          style={{ whiteSpace: 'nowrap' }}
        >
          Add
        </button>
      </div>
    </div>
  );
}

ListEditor.propTypes = {
  items: PropTypes.arrayOf(PropTypes.string),
  onChange: PropTypes.func.isRequired,
  placeholder: PropTypes.string,
};

export default ListEditor;
