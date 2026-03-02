import React, { useEffect, useRef, useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import { searchApi } from '../api/client';
import { useAuth } from '../context/AuthContext.jsx';

// Navigation items — only honest entries that navigate directly to what they say.
// Ghost commands (actions that just navigate to a route without applying a filter/action)
// and the append-only audit-log "clear" command have been removed.
const DEFAULT_ITEMS = [
  // ── Navigation ──────────────────────────────────────────────────────────────
  { id: 'nav-hardware',     icon: '🖥️', title: 'Go to: Hardware',              action_url: '/hardware'       },
  { id: 'nav-compute',      icon: '💻', title: 'Go to: Compute',               action_url: '/compute-units'  },
  { id: 'nav-services',     icon: '🛠️', title: 'Go to: Services',              action_url: '/services'       },
  { id: 'nav-networks',     icon: '🔗', title: 'Go to: Networks',              action_url: '/networks'       },
  { id: 'nav-storage',      icon: '💾', title: 'Go to: Storage',               action_url: '/storage'        },
  { id: 'nav-map',          icon: '🗺️', title: 'Go to: Topology Map',          action_url: '/map'            },
  { id: 'nav-logs',         icon: '📋', title: 'Go to: Logs',                  action_url: '/logs'           },
  { id: 'nav-ext',          icon: '☁️', title: 'Go to: External / Cloud Nodes',action_url: '/external-nodes' },
  { id: 'nav-docs',         icon: '📄', title: 'Go to: Documentation',         action_url: '/docs'           },
  // ── Settings ─────────────────────────────────────────────────────────────────
  { id: 'settings-open',         icon: '⚙️', title: 'Go to: Settings',                   action_url: '/settings'                     },
  { id: 'settings-appearance',   icon: '🎨', title: 'Settings: Appearance',              action_url: '/settings?section=appearance'  },
  { id: 'settings-defaults',     icon: '🔧', title: 'Settings: Defaults',                action_url: '/settings?section=defaults'    },
  { id: 'settings-icons',        icon: '🖼️', title: 'Settings: Icons & Vendors',        action_url: '/settings?section=icons'       },
  { id: 'settings-categories',   icon: '🏷️', title: 'Settings: Manage Categories',      action_url: '/settings?section=categories'  },
  { id: 'settings-environments', icon: '🌐', title: 'Settings: Manage Environments',    action_url: '/settings?section=environments'},
  { id: 'settings-timezone',     icon: '🕐', title: 'Settings: Change Timezone',        action_url: '/settings?section=appearance'  },
  { id: 'settings-auth',         icon: '🔒', title: 'Settings: Authentication',         action_url: '/settings?section=auth'        },
  { id: 'settings-experimental', icon: '🧪', title: 'Settings: Experimental',           action_url: '/settings?section=experimental'},
  // ── Actions (open modals / overlays) ─────────────────────────────────────────
  { id: 'auth-login',   icon: '👤', title: 'Open: Login',   action_fn: 'openAuthModal'    },
  { id: 'auth-profile', icon: '🪪', title: 'Open: Profile', action_fn: 'openProfileModal' },
];

const TYPE_LABELS = {
  hardware: 'HW',
  compute:  'VM',
  service:  'SVC',
  storage:  'STR',
  network:  'NET',
  misc:     'MISC',
  external: 'EXT',
};

function CommandPalette({ isOpen, onClose }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef(null);
  const debounceRef = useRef(null);
  const panelRef = useRef(null);
  const activeItemRef = useRef(null);
  const navigate = useNavigate();
  const { openAuthModal, openProfileModal } = useAuth();

  // Stable ref-backed action map — avoids stale closures without recreating handleSelect
  const authFnsRef = useRef({});
  authFnsRef.current = { openAuthModal, openProfileModal };

  // Auto-focus and reset state when palette opens
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setResults([]);
      setSelectedIndex(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  // Scroll active item into view whenever selectedIndex changes
  useEffect(() => {
    activeItemRef.current?.scrollIntoView({ block: 'nearest' });
  }, [selectedIndex]);

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

  // Clean up any pending debounce on unmount
  useEffect(() => {
    return () => clearTimeout(debounceRef.current);
  }, []);

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
    setSelectedIndex(0);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => doSearch(val), 200);
  };

  const handleSelect = useCallback((item) => {
    if (item.action_fn && authFnsRef.current[item.action_fn]) {
      authFnsRef.current[item.action_fn]();
    } else if (item.action_url) {
      navigate(item.action_url);
    }
    onClose();
  }, [navigate, onClose]);

  const handleKeyDown = (e) => {
    if (!items.length) return;
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIndex((i) => Math.min(i + 1, items.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      handleSelect(items[selectedIndex]);
    }
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
            aria-label="Search commands"
            value={query}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
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

          {!loading && items.map((item, idx) => {
            const isActive = idx === selectedIndex;
            return (
              <button
                key={item.id}
                ref={isActive ? activeItemRef : null}
                className={`palette-result-item${isActive ? ' palette-result-item--active' : ''}`}
                onClick={() => handleSelect(item)}
                onMouseEnter={() => setSelectedIndex(idx)}
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
            );
          })}
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
