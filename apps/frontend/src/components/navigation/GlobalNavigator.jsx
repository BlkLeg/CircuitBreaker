import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { AlertTriangle, Clock3, History, LayoutGrid, Loader2, Pin, Search, X } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import NavigatorResultRow from './NavigatorResultRow.jsx';
import { NAV_GROUPS, canSeeNavItem } from '../../data/navigation';
import { buildLocalIndex } from '../../lib/navigationSearch';
import {
  namespaceFor,
  readPins,
  readRecents,
  togglePin as togglePinStored,
} from '../../lib/navigatorPrefs';
import { useNavigatorSearch } from '../../hooks/useNavigatorSearch';
import { useAuth } from '../../context/AuthContext.jsx';
import { useIsMobile } from '../../hooks/useIsMobile';
import '../../styles/navigator.css';

const IS_MAC = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform ?? '');
const NavigatorResultRowMemo = React.memo(NavigatorResultRow);

function canonicalPath(pathname) {
  if (/^\/agents\/[^/]+/.test(pathname)) return '/agents';
  if (/^\/monitors\/[^/]+/.test(pathname)) return '/monitors';
  return pathname;
}

function isCurrentEntry(entry, location) {
  if (!entry?.path) return false;
  const target = new URL(entry.path, 'https://navigator.local');
  if (canonicalPath(location.pathname) !== target.pathname) return false;
  if (entry.kind !== 'settings') return true;
  return new URLSearchParams(location.search).get('tab') === target.searchParams.get('tab');
}

function focusableElements(panel) {
  if (!panel) return [];
  return [...panel.querySelectorAll('button:not([disabled]), input:not([disabled])')].filter(
    (element) =>
      element.getAttribute('aria-hidden') !== 'true' &&
      !element.hidden &&
      globalThis.getComputedStyle(element).display !== 'none'
  );
}

/** The single browse, search, pin, and recent overlay used by Header and Ctrl/Cmd+K. */
function GlobalNavigator({ isOpen, onClose, onNavigate }) {
  const { user, isMasquerade } = useAuth();
  const location = useLocation();
  const isMobile = useIsMobile();
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('all');
  const [category, setCategory] = useState('all');
  const [activeIndex, setActiveIndex] = useState(0);
  const [pins, setPins] = useState([]);
  const [recents, setRecents] = useState([]);

  const inputRef = useRef(null);
  const panelRef = useRef(null);
  const activeRowRef = useRef(null);
  const openerRef = useRef(null);
  const suppressFocusTrapRef = useRef(false);
  // True when the keyboard moved the selection. A hover must not scroll the
  // list out from under the pointer that caused it.
  const scrollActiveIntoViewRef = useRef(false);
  // The question the current selection was chosen for. While it is unchanged,
  // a list that grows underneath (assets arriving after their debounce) must
  // not move the selection the operator already made.
  const snappedForRef = useRef(null);
  const namespace = useMemo(() => namespaceFor({ user, isMasquerade }), [user, isMasquerade]);

  const { localResults, assetResults, assetsLoading, assetsError, hasMore, retryAssets } =
    useNavigatorSearch({ query, user, enabled: isOpen });
  const index = useMemo(() => buildLocalIndex(user), [user]);
  const byId = useMemo(() => new Map(index.map((entry) => [entry.id, entry])), [index]);
  const searching = query.trim().length > 0;

  useEffect(() => {
    if (!isOpen) return undefined;
    openerRef.current = document.activeElement;
    suppressFocusTrapRef.current = false;
    setQuery('');
    setMode('all');
    setCategory('all');
    setActiveIndex(0);
    snappedForRef.current = null;
    setPins(readPins(namespace).filter((id) => byId.has(id)));
    setRecents(readRecents(namespace).filter((id) => byId.has(id)));
    const frame = requestAnimationFrame(() => inputRef.current?.focus());
    return () => cancelAnimationFrame(frame);
  }, [isOpen, namespace, byId]);

  useEffect(() => {
    if (!scrollActiveIntoViewRef.current) return;
    scrollActiveIntoViewRef.current = false;
    activeRowRef.current?.scrollIntoView?.({ block: 'nearest' });
  }, [activeIndex]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const onFocusIn = (event) => {
      if (suppressFocusTrapRef.current) return;
      if (panelRef.current && !panelRef.current.contains(event.target)) inputRef.current?.focus();
    };
    document.addEventListener('focusin', onFocusIn);
    return () => document.removeEventListener('focusin', onFocusIn);
  }, [isOpen]);

  const close = useCallback(() => {
    suppressFocusTrapRef.current = true;
    onClose();
    const opener = openerRef.current;
    if (opener && typeof opener.focus === 'function' && document.contains(opener)) opener.focus();
  }, [onClose]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const onPointerDown = (event) => {
      if (panelRef.current && !panelRef.current.contains(event.target)) close();
    };
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => document.removeEventListener('pointerdown', onPointerDown, true);
  }, [isOpen, close]);

  const visibleGroups = useMemo(
    () =>
      NAV_GROUPS.map((group) => ({
        id: group.id,
        label: group.label,
        entries: group.items
          .filter((item) => canSeeNavItem(item, group, user))
          .map((item) => byId.get(`page:${item.path}`))
          .filter(Boolean),
      })).filter((group) => group.entries.length > 0),
    [user, byId]
  );

  const pinnedEntries = useMemo(() => pins.map((id) => byId.get(id)).filter(Boolean), [pins, byId]);
  const recentEntries = useMemo(
    () => recents.map((id) => byId.get(id)).filter(Boolean),
    [recents, byId]
  );

  const groups = useMemo(() => {
    if (searching) {
      const pagesAndSettings = localResults.filter((entry) => entry.kind !== 'action');
      const actions = localResults.filter((entry) => entry.kind === 'action');
      return [
        ...(pagesAndSettings.length
          ? [{ id: 'local', label: 'Pages & Settings', entries: pagesAndSettings }]
          : []),
        ...(assetResults.length ? [{ id: 'assets', label: 'Assets', entries: assetResults }] : []),
        ...(actions.length ? [{ id: 'actions', label: 'Actions', entries: actions }] : []),
      ];
    }
    if (mode === 'recent') {
      return recentEntries.length
        ? [{ id: 'recent', label: 'Recently visited', entries: recentEntries }]
        : [];
    }
    return category === 'all'
      ? visibleGroups
      : visibleGroups.filter((group) => group.id === category);
  }, [searching, localResults, assetResults, mode, recentEntries, category, visibleGroups]);

  const flat = useMemo(() => groups.flatMap((group) => group.entries), [groups]);

  // What the operator is currently asking for. A new question earns a fresh
  // selection; the same question re-rendered with more results does not.
  const question = searching ? `search:${query.trim()}` : `browse:${mode}:${category}`;

  useEffect(() => {
    if (snappedForRef.current !== question) {
      snappedForRef.current = question;
      // Actions sort after assets, so the best local match is not always
      // flat[0] — find it rather than assuming the top of the list.
      const bestLocalIndex =
        searching && localResults.length
          ? flat.findIndex((entry) => entry.id === localResults[0].id)
          : -1;
      if (bestLocalIndex > 0) scrollActiveIntoViewRef.current = true;
      setActiveIndex(bestLocalIndex >= 0 ? bestLocalIndex : 0);
      return;
    }
    // Same question, longer list: keep the selection, only pull it back into
    // range if the list shrank beneath it.
    setActiveIndex((indexValue) => (indexValue < flat.length ? indexValue : 0));
  }, [flat, searching, localResults, question]);

  const handleActivate = useCallback(
    (entry) => {
      if (!entry) return;
      suppressFocusTrapRef.current = true;
      onClose();
      onNavigate(entry);
    },
    [onClose, onNavigate]
  );

  // Stable, and takes the index rather than closing over it, so the memoized
  // rows are not invalidated on every render.
  const handleHover = useCallback((rowIndex) => setActiveIndex(rowIndex), []);

  const handleTogglePin = useCallback(
    (entry) => {
      if (!['page', 'settings'].includes(entry.kind)) return;
      setPins(togglePinStored(namespace, entry.id).filter((id) => byId.has(id)));
    },
    [namespace, byId]
  );

  const handleKeyDown = (event) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
      return;
    }
    if (event.key === 'Tab') {
      const focusable = focusableElements(panelRef.current);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
      return;
    }
    if (event.nativeEvent?.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      scrollActiveIntoViewRef.current = true;
      // Arrowing is list navigation, and Enter opens the *selected* row only
      // while the search field holds focus. Returning focus here keeps one
      // notion of "selected": a row that was tabbed to would otherwise be
      // opened by Enter while the highlight sat somewhere else entirely.
      inputRef.current?.focus();
      if (event.key === 'ArrowDown') {
        setActiveIndex((indexValue) =>
          flat.length ? Math.min(indexValue + 1, flat.length - 1) : 0
        );
      } else {
        setActiveIndex((indexValue) => Math.max(indexValue - 1, 0));
      }
    } else if (event.key === 'Enter' && event.target === inputRef.current) {
      event.preventDefault();
      handleActivate(flat.at(activeIndex));
    }
  };

  if (!isOpen) return null;

  const pinSet = new Set(pins);
  const activeOptionId =
    activeIndex >= 0 && activeIndex < flat.length ? `navigator-option-${activeIndex}` : undefined;
  let cursor = -1;
  const totalVisiblePages = visibleGroups.reduce((total, group) => total + group.entries.length, 0);

  return (
    <div className="navigator-overlay">
      <section
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="navigator-title"
        className={`navigator-panel${isMobile ? ' navigator-panel--mobile' : ''}`}
        onKeyDown={handleKeyDown}
      >
        <header className="navigator-titlebar">
          <div>
            <h2 id="navigator-title">Navigate</h2>
            <p>Search, pin, and jump anywhere in Circuit Breaker.</p>
          </div>
          <button
            type="button"
            className="navigator-close"
            onClick={close}
            aria-label="Close navigator"
          >
            <X size={18} aria-hidden="true" />
          </button>
        </header>

        <div className="navigator-search-row">
          <Search size={17} aria-hidden="true" />
          <input
            ref={inputRef}
            type="search"
            role="searchbox"
            // Which row is highlighted, for anyone who cannot see it. The row
            // ids existed for this from the start and nothing pointed at them.
            //
            // Not `role="combobox"`: that promises a listbox popup, and a
            // listbox may not contain the per-row pin buttons — axe reports
            // `aria-required-children` (critical) for every row. A searchbox
            // supports aria-activedescendant on its own, which is the part
            // that was actually missing.
            aria-activedescendant={activeOptionId}
            className="navigator-input"
            placeholder="Search pages, settings, and assets…"
            aria-label="Search pages, settings, and assets"
            aria-controls="navigator-results"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value);
              setActiveIndex(0);
            }}
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="navigator-hint">{IS_MAC ? '⌘K' : 'Ctrl K'}</kbd>
        </div>

        {!searching ? (
          <div className="navigator-controls">
            <div className="navigator-modes" aria-label="Navigator view">
              <button
                type="button"
                className={mode === 'all' ? 'is-active' : ''}
                aria-pressed={mode === 'all'}
                onClick={() => setMode('all')}
              >
                <LayoutGrid size={14} aria-hidden="true" /> All pages
              </button>
              <button
                type="button"
                className={mode === 'recent' ? 'is-active' : ''}
                aria-pressed={mode === 'recent'}
                onClick={() => setMode('recent')}
              >
                <History size={14} aria-hidden="true" /> Recent
              </button>
            </div>

            {mode === 'all' ? (
              <div className="navigator-pinned" aria-label="Pinned pages">
                <span>
                  <Pin size={12} aria-hidden="true" /> Pinned
                </span>
                <div>
                  {pinnedEntries.length ? (
                    pinnedEntries.map((entry) => (
                      <button key={entry.id} type="button" onClick={() => handleActivate(entry)}>
                        {entry.label.replace(/^Settings: /, '')}
                      </button>
                    ))
                  ) : (
                    <em>Use a pin button to keep pages here. Your dock stays unchanged.</em>
                  )}
                </div>
              </div>
            ) : null}

            {mode === 'all' ? (
              <div className="navigator-categories" aria-label="Page categories">
                {[{ id: 'all', label: 'Everything' }, ...visibleGroups].map((group) => (
                  <button
                    key={group.id}
                    type="button"
                    className={category === group.id ? 'is-active' : ''}
                    aria-pressed={category === group.id}
                    onClick={() => {
                      setCategory(group.id);
                      setActiveIndex(0);
                    }}
                  >
                    {group.label}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ) : null}

        {assetsError ? (
          <div className="navigator-banner navigator-banner--error">
            <AlertTriangle size={14} aria-hidden="true" />
            <span>Assets could not be searched. Page results are still available.</span>
            <button type="button" className="navigator-retry" onClick={retryAssets}>
              Retry
            </button>
          </div>
        ) : null}

        <div id="navigator-results" aria-label="Results" className="navigator-results">
          <div
            className={`navigator-groups${
              !searching && mode === 'all' && category === 'all' ? ' navigator-groups--columns' : ''
            }`}
          >
            {groups.map((group) => (
              <section
                key={group.id}
                role="group"
                aria-labelledby={`navigator-group-label-${group.id}`}
                className="navigator-group"
              >
                <div id={`navigator-group-label-${group.id}`} className="navigator-group-label">
                  {group.id === 'recent' ? <Clock3 size={12} aria-hidden="true" /> : null}
                  <span>{group.label}</span>
                  <span
                    className="navigator-group-count"
                    data-testid={`navigator-group-count-${group.id}`}
                  >
                    {group.entries.length}
                  </span>
                </div>
                {group.entries.map((entry) => {
                  cursor += 1;
                  const active = cursor === activeIndex;
                  return (
                    <div key={entry.id} ref={active ? activeRowRef : null}>
                      <NavigatorResultRowMemo
                        entry={entry}
                        active={active}
                        current={isCurrentEntry(entry, location)}
                        index={cursor}
                        onActivate={handleActivate}
                        onHover={handleHover}
                        onTogglePin={
                          ['page', 'settings'].includes(entry.kind) && namespace
                            ? handleTogglePin
                            : null
                        }
                        pinned={pinSet.has(entry.id)}
                      />
                    </div>
                  );
                })}
              </section>
            ))}
          </div>

          {assetsLoading && !flat.length ? (
            <div className="navigator-empty">
              <Loader2 size={14} className="navigator-spin" aria-hidden="true" /> Searching…
            </div>
          ) : null}
          {!assetsLoading && searching && !flat.length && !assetsError ? (
            <div className="navigator-empty">No results for “{query.trim()}”</div>
          ) : null}
          {!searching && mode === 'recent' && !recentEntries.length ? (
            <div className="navigator-empty">Pages you successfully visit will appear here.</div>
          ) : null}
          {hasMore ? (
            <div className="navigator-footnote">
              More assets match than are shown. Refine your search to narrow it.
            </div>
          ) : null}
        </div>

        <footer className="navigator-footer">
          <span role="status" aria-live="polite">
            {assetsLoading
              ? 'Searching assets…'
              : searching
                ? `${flat.length} results`
                : `${totalVisiblePages} pages available`}
          </span>
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> select <kbd>Enter</kbd> open <kbd>Esc</kbd> close
          </span>
        </footer>
      </section>
    </div>
  );
}

GlobalNavigator.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onNavigate: PropTypes.func.isRequired,
};

export default GlobalNavigator;
