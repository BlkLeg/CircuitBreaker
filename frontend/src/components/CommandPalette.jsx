import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { searchApi } from '../api/client';

const DEFAULT_ITEMS = [
  { id: 'default-1', icon: '🖥️', title: 'Go to: Hardware',              action_url: '/hardware'       },
  { id: 'default-2', icon: '➕', title: 'Go to: Services',               action_url: '/services'       },
  { id: 'default-3', icon: '🔗', title: 'Go to: Networks',               action_url: '/networks'       },
  { id: 'default-4', icon: '💾', title: 'Go to: Storage',                action_url: '/storage'        },
  { id: 'default-5', icon: '🗺️', title: 'Go to: Topology Map',           action_url: '/map'            },
  { id: 'default-6', icon: '📄', title: 'Go to: Documentation',          action_url: '/docs'           },
];

const TYPE_LABELS = {
  hardware: 'HW',
  compute:  'VM',
  service:  'SVC',
  storage:  'STR',
  network:  'NET',
  misc:     'MISC',
};

function CommandPalette({ isOpen, onClose }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const debounceRef = useRef(null);
  const navigate = useNavigate();

  // Auto-focus when palette opens
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setResults([]);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Close on Escape
  useEffect(() => {
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const doSearch = useCallback(async (q) => {
    if (!q.trim()) { setResults([]); setLoading(false); return; }
    setLoading(true);
    try {
      const res = await searchApi.search(q);
      setResults(res.data);
    } catch {
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const handleInput = (e) => {
    const val = e.target.value;
    setQuery(val);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 200);
  };

  const handleSelect = (url) => {
    navigate(url);
    onClose();
  };

  if (!isOpen) return null;

  const showDefaults = !query.trim();
  const items = showDefaults ? DEFAULT_ITEMS : results;

  return (
    <div className="palette-overlay" onClick={onClose}>
      <div className="command-palette" onClick={(e) => e.stopPropagation()}>
        <div className="palette-search-row">
          <input
            ref={inputRef}
            className="palette-input"
            type="text"
            placeholder="Type a command or search..."
            value={query}
            onChange={handleInput}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="palette-hint">Ctrl K</kbd>
        </div>

        <div className="palette-results">
          {loading && <div className="palette-empty">Searching…</div>}

          {!loading && items.length === 0 && query.trim() && (
            <div className="palette-empty">No results for "{query}"</div>
          )}

          {!loading && items.map((item) => (
            <button
              key={item.id}
              className="palette-result-item"
              onClick={() => handleSelect(item.action_url)}
            >
              {showDefaults ? (
                <span className="palette-default-icon">{item.icon}</span>
              ) : (
                <span className={`palette-type-badge palette-type-${item.type}`}>
                  {TYPE_LABELS[item.type] ?? item.type}
                </span>
              )}
              <span className="palette-item-title">{item.title}</span>
              {item.description && (
                <span className="palette-item-desc">{item.description}</span>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default CommandPalette;
