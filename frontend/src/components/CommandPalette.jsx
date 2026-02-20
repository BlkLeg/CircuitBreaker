import React, { useEffect, useRef, useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import { searchApi } from '../api/client';

const DEFAULT_ITEMS = [
  { id: 'default-1', icon: '🖥️', title: 'Go to: Hardware',              action_url: '/hardware'       },
  { id: 'default-2', icon: '➕', title: 'Go to: Services',               action_url: '/services'       },
  { id: 'nav-net',   icon: '🔗', title: 'Open: Networks',                action_url: '/networks'       },
  { id: 'default-4', icon: '💾', title: 'Go to: Storage',                action_url: '/storage'        },
  { id: 'nav-map',        icon: '🗺️', title: 'Open: Topology Map',            action_url: '/map'            },
  { id: 'nav-cb-map',    icon: '⚡', title: 'Open: Circuit Breaker Map',     action_url: '/map'            },
  { id: 'map-filter-env',icon: '🌍', title: 'Map: Filter by environment',    action_url: '/map'            },
  { id: 'map-filter-tag',icon: '🏷️', title: 'Map: Filter by tag',            action_url: '/map'            },
  { id: 'nav-docs',  icon: '📄', title: 'Open: Documentation',           action_url: '/docs'           },
  { id: 'settings-open',        icon: '⚙️', title: 'Open: Settings',                      action_url: '/settings'                          },
  { id: 'settings-appearance',  icon: '🎨', title: 'Settings: Appearance',                action_url: '/settings?section=appearance'        },
  { id: 'settings-defaults',    icon: '🏷️', title: 'Settings: Defaults',                  action_url: '/settings?section=defaults'          },
  { id: 'settings-icons',       icon: '🖼️', title: 'Settings: Icons & Vendors',           action_url: '/settings?section=icons'             },
  { id: 'settings-experimental',icon: '🧪', title: 'Settings: Experimental',              action_url: '/settings?section=experimental'      },
  { id: 'nav-logs',          icon: '🕐', title: 'Open: Logs',              action_url: '/logs' },
  { id: 'logs-filter-crud',  icon: '📋', title: 'Logs: Filter by CRUD',    action_url: '/logs' },
  { id: 'logs-filter-svc',   icon: '🔧', title: 'Logs: Filter by service', action_url: '/logs' },
  { id: 'logs-export',       icon: '⬇️', title: 'Logs: Export logs',       action_url: '/logs' },
  { id: 'logs-clear',        icon: '🗑️', title: 'Logs: Clear logs',        action_url: '/logs' },
  { id: 'map-link-node',     icon: '🔗', title: 'Map: Link selected node',              action_url: '/map'      },
  { id: 'map-storage',       icon: '💾', title: 'Map: Show storage details',            action_url: '/map'      },
  { id: 'hw-filter-storage', icon: '🗄️', title: 'Hardware: Filter by storage capacity', action_url: '/hardware' },
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
  const panelRef = useRef(null);
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
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [onClose]);

  // Close on click outside the panel
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (panelRef.current && !panelRef.current.contains(e.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [isOpen, onClose]);

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
  const defaultMatches = query.trim()
    ? DEFAULT_ITEMS.filter(item =>
        item.title.toLowerCase().includes(query.trim().toLowerCase()))
    : [];
  const items = showDefaults ? DEFAULT_ITEMS : [...defaultMatches, ...results];

  return (
    <div className="palette-overlay">
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        className="command-palette"
        aria-label="Command palette"
      >
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

CommandPalette.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};
