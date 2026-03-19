import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';

const PRESET_COLORS = [
  '#ef4444',
  '#f97316',
  '#eab308',
  '#22c55e',
  '#14b8a6',
  '#3b82f6',
  '#8b5cf6',
  '#ec4899',
  '#6b7280',
  '#1f2937',
];

const chipBase =
  'tw-inline-flex tw-items-center tw-gap-1 tw-rounded tw-px-2 tw-py-0.5 tw-text-xs tw-font-medium tw-border tw-border-cb-border';

/* Match EntityTable editable input for contrast and theme */
const tagInputClass =
  'tw-min-w-[6rem] tw-w-24 tw-bg-cb-bg tw-border tw-border-cb-border tw-text-cb-text tw-rounded tw-px-2 tw-py-1 tw-text-sm focus:tw-outline-none focus:tw-ring-1 focus:tw-ring-cb-primary placeholder:tw-text-cb-text-muted';

function TagsCell({
  tags = [],
  allTags = [],
  onTagsChange,
  onTagColorChange = () => {},
  disabled = false,
}) {
  const [adding, setAdding] = useState(false);
  const [inputValue, setInputValue] = useState('');
  const [colorPickerFor, setColorPickerFor] = useState(null);
  const inputRef = useRef(null);
  const pickerRef = useRef(null);

  const tagMap = React.useMemo(() => {
    const m = new Map();
    (allTags || []).forEach((t) => m.set(t.name, t));
    return m;
  }, [allTags]);

  useEffect(() => {
    if (adding && inputRef.current) inputRef.current.focus();
  }, [adding]);

  useEffect(() => {
    function handleClickOutside(e) {
      if (pickerRef.current && !pickerRef.current.contains(e.target)) {
        setColorPickerFor(null);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleAdd = () => {
    const name = inputValue.trim();
    if (!name) return;
    const next = [...(tags || []), name];
    onTagsChange(next);
    setInputValue('');
    setAdding(false);
  };

  const handleRemove = (name) => {
    onTagsChange((tags || []).filter((t) => t !== name));
  };

  const handleColorSelect = (tagName, color) => {
    const tag = tagMap.get(tagName);
    if (tag?.id) onTagColorChange(tag.id, color);
    setColorPickerFor(null);
  };

  if (disabled) {
    return (
      <span className="tw-text-cb-text-muted tw-text-sm">
        {(tags || []).length ? (tags || []).join(', ') : '—'}
      </span>
    );
  }

  return (
    <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-1.5 tw-min-w-0" data-tags-cell>
      {(tags || []).map((name) => {
        const meta = tagMap.get(name);
        const isDark =
          meta?.color &&
          /^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(meta.color) &&
          (Number.parseInt(meta.color.slice(1), 16) & 0xffffff) < 0x888888;
        let chipColor = 'var(--color-cb-text)';
        if (meta?.color) chipColor = isDark ? '#fff' : '#111';
        return (
          <span
            key={name}
            className={`${chipBase} tw-relative`}
            style={{
              backgroundColor: meta?.color ? `${meta.color}22` : undefined,
              borderColor: meta?.color || 'var(--color-cb-border)',
              color: chipColor,
            }}
          >
            {name}
            <button
              type="button"
              className="tw-ml-1 tw-leading-none tw-p-0.5 tw-rounded tw-border tw-border-transparent tw-bg-transparent hover:tw-bg-cb-border/40 hover:tw-border-cb-border tw-text-current tw-opacity-80 hover:tw-opacity-100 tw-cursor-pointer tw-text-xs"
              onClick={(e) => {
                e.stopPropagation();
                handleRemove(name);
              }}
              aria-label={`Remove ${name}`}
            >
              ×
            </button>
            <button
              type="button"
              className="tw-ml-0.5 tw-p-0.5 tw-rounded tw-border tw-border-cb-border tw-bg-cb-bg/80 hover:tw-bg-cb-border/30 tw-cursor-pointer tw-leading-none"
              onClick={(e) => {
                e.stopPropagation();
                setColorPickerFor((prev) => (prev === name ? null : name));
              }}
              aria-label={`Set color for ${name}`}
              title="Set color"
            >
              <span
                className="tw-inline-block tw-w-2.5 tw-h-2.5 tw-rounded-full tw-border tw-border-cb-border"
                style={{ backgroundColor: meta?.color || 'var(--color-cb-text-muted)' }}
              />
            </button>
            {colorPickerFor === name && (
              <fieldset
                ref={pickerRef}
                className="tw-absolute tw-left-0 tw-top-full tw-mt-1 tw-z-10 tw-p-2 tw-rounded tw-shadow-lg tw-bg-cb-surface tw-border tw-border-cb-border tw-border-solid tw-m-0"
                aria-label="Tag color"
              >
                <div className="tw-grid tw-grid-cols-5 tw-gap-1">
                  {PRESET_COLORS.map((c) => (
                    <button
                      key={c}
                      type="button"
                      className="tw-w-6 tw-h-6 tw-rounded tw-border-2 tw-border-transparent hover:tw-border-cb-primary focus:tw-outline-none focus:tw-ring-1 focus:tw-ring-cb-primary"
                      style={{ backgroundColor: c }}
                      onClick={() => handleColorSelect(name, c)}
                      aria-label={`Color ${c}`}
                    />
                  ))}
                </div>
              </fieldset>
            )}
          </span>
        );
      })}
      {adding ? (
        <input
          ref={inputRef}
          type="text"
          className={tagInputClass}
          placeholder="Tag name"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              handleAdd();
            }
            if (e.key === 'Escape') setAdding(false);
          }}
          onBlur={() => {
            if (inputValue.trim()) handleAdd();
            else setAdding(false);
          }}
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
        />
      ) : (
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={(e) => {
            e.stopPropagation();
            setAdding(true);
          }}
        >
          + Add
        </button>
      )}
    </div>
  );
}

TagsCell.propTypes = {
  tags: PropTypes.arrayOf(PropTypes.string),
  allTags: PropTypes.arrayOf(
    PropTypes.shape({ id: PropTypes.number, name: PropTypes.string, color: PropTypes.string })
  ),
  onTagsChange: PropTypes.func.isRequired,
  onTagColorChange: PropTypes.func,
  disabled: PropTypes.bool,
};

export default TagsCell;
