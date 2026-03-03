import React, { useState, useEffect, useRef, useCallback } from 'react';
import PropTypes from 'prop-types';
import MDEditor, { commands } from '@uiw/react-md-editor';
import '@uiw/react-md-editor/markdown-editor.css';
import { Undo2, Redo2 } from 'lucide-react';

// Emoji picker loaded on-demand (~680 kB) — only when user clicks the emoji button
let _emojiModules = null;
const loadEmojiPicker = async () => {
  if (!_emojiModules) {
    const [dataModule, pickerModule] = await Promise.all([
      import('@emoji-mart/data'),
      import('@emoji-mart/react'),
    ]);
    _emojiModules = { data: dataModule.default, Picker: pickerModule.default };
  }
  return _emojiModules;
};

/* ── Custom undo/redo commands (removed in @uiw/react-md-editor v4) ──── */
const undoCommand = {
  name: 'undo',
  keyCommand: 'undo',
  icon: React.createElement(Undo2, { size: 14 }),
  execute: () => { document.execCommand('undo'); },
};
const redoCommand = {
  name: 'redo',
  keyCommand: 'redo',
  icon: React.createElement(Redo2, { size: 14 }),
  execute: () => { document.execCommand('redo'); },
};
import { docsApi } from '../api/client';
import logger from '../utils/logger';
import './DocEditor.css';

const DRAFT_PREFIX = 'cb-doc-';
const AUTOSAVE_INTERVAL = 30000; // 30 seconds
const BACKEND_DEBOUNCE = 15000; // 15 seconds

/**
 * DocEditor — production-grade Markdown editor with toolbar, emoji, image
 * upload, auto-save, and draft recovery.
 *
 * Props:
 *   docId       — numeric doc ID (null for unsaved new docs)
 *   value       — current Markdown string
 *   onChange     — called with new Markdown on every keystroke
 *   onSave      — async function to persist to backend
 *   updatedAt   — ISO timestamp of last backend save
 */
function DocEditor({ docId, value, onChange, onSave, updatedAt }) {
  const [saveStatus, setSaveStatus] = useState('saved'); // saved | saving | unsaved | error
  const [showEmoji, setShowEmoji] = useState(false);
  const [emojiReady, setEmojiReady] = useState(false);
  const emojiRef = useRef(null); // { data, Picker }
  const [draftBanner, setDraftBanner] = useState(null); // { draftBody }
  const [imageError, setImageError] = useState(null);
  const dirtyRef = useRef(false);
  const backendTimerRef = useRef(null);
  const editorRef = useRef(null);
  const headingLevelRef = useRef(null);

  // ── Draft recovery on mount ──────────────────────────────────
  useEffect(() => {
    if (!docId) return;
    const key = `${DRAFT_PREFIX}${docId}`;
    const raw = localStorage.getItem(key);
    if (!raw) return;
    try {
      const draft = JSON.parse(raw);
      if (updatedAt && draft.savedAt) {
        const draftTime = new Date(draft.savedAt).getTime();
        const backendTime = new Date(updatedAt).getTime();
        if (draftTime > backendTime && draft.body !== value) {
          setDraftBanner({ draftBody: draft.body });
        }
      }
    } catch {
      localStorage.removeItem(key);
    }
    // Only run on mount / docId change
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [docId]);

  const restoreDraft = useCallback(() => {
    if (draftBanner) {
      onChange(draftBanner.draftBody);
      setDraftBanner(null);
      setSaveStatus('unsaved');
    }
  }, [draftBanner, onChange]);

  const discardDraft = useCallback(() => {
    if (docId) localStorage.removeItem(`${DRAFT_PREFIX}${docId}`);
    setDraftBanner(null);
  }, [docId]);

  // ── Auto-save to localStorage every 30s ─────────────────────
  useEffect(() => {
    const interval = setInterval(() => {
      if (!dirtyRef.current || !docId) return;
      const key = `${DRAFT_PREFIX}${docId}`;
      localStorage.setItem(key, JSON.stringify({ body: value, savedAt: new Date().toISOString() }));
    }, AUTOSAVE_INTERVAL);
    return () => clearInterval(interval);
  }, [docId, value]);

  // ── Debounced backend save ──────────────────────────────────
  useEffect(() => {
    if (!dirtyRef.current || !docId) return;
    clearTimeout(backendTimerRef.current);
    backendTimerRef.current = setTimeout(async () => {
      if (!dirtyRef.current) return;
      setSaveStatus('saving');
      try {
        await onSave(value);
        dirtyRef.current = false;
        setSaveStatus('saved');
        // Clear draft on successful save
        localStorage.removeItem(`${DRAFT_PREFIX}${docId}`);
      } catch (err) {
        logger.error('Auto-save failed:', err);
        setSaveStatus('error');
      }
    }, BACKEND_DEBOUNCE);
    return () => clearTimeout(backendTimerRef.current);
  }, [value, docId, onSave]);

  // ── Handle change ───────────────────────────────────────────
  const handleChange = useCallback((val) => {
    onChange(val || '');
    dirtyRef.current = true;
    setSaveStatus('unsaved');
    setImageError(null);
  }, [onChange]);

  // ── Image upload (drag & drop or toolbar) ───────────────────
  const handleImageUpload = useCallback(async (file) => {
    if (!docId) {
      setImageError('Save the document first to upload images');
      return null;
    }
    if (!file.type.startsWith('image/')) {
      setImageError('File must be an image');
      return null;
    }
    if (file.size > 5 * 1024 * 1024) {
      setImageError('Image must be ≤ 5 MB');
      return null;
    }
    try {
      const res = await docsApi.uploadImage(docId, file);
      setImageError(null);
      return res.data.url;
    } catch (err) {
      logger.error('Image upload failed:', err);
      setImageError(err.message || 'Upload failed');
      return null;
    }
  }, [docId]);

  // ── Drop handler ────────────────────────────────────────────
  const handleDrop = useCallback(async (e) => {
    e.preventDefault();
    const files = Array.from(e.dataTransfer?.files || []);
    const imageFile = files.find(f => f.type.startsWith('image/'));
    if (!imageFile) return;
    const url = await handleImageUpload(imageFile);
    if (url) {
      onChange((value || '') + `\n![image](${url})\n`);
      dirtyRef.current = true;
      setSaveStatus('unsaved');
    }
  }, [handleImageUpload, onChange, value]);

  const handleDragOver = useCallback((e) => {
    e.preventDefault();
  }, []);

  // ── ⌘S / Ctrl+S keyboard shortcut ─────────────────────────
  useEffect(() => {
    const handleKeyDown = async (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 's') {
        e.preventDefault();
        if (!dirtyRef.current) return;
        clearTimeout(backendTimerRef.current);
        setSaveStatus('saving');
        try {
          await onSave(value);
          dirtyRef.current = false;
          setSaveStatus('saved');
          if (docId) localStorage.removeItem(`${DRAFT_PREFIX}${docId}`);
        } catch (err) {
          logger.error('⌘S save failed:', err);
          setSaveStatus('error');
        }
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [value, docId, onSave]);

  // ── Custom toolbar commands ─────────────────────────────────

  // Emoji picker command
  const emojiCommand = {
    name: 'emoji',
    keyCommand: 'emoji',
    buttonProps: { 'aria-label': 'Insert emoji', title: 'Emoji' },
    icon: <span style={{ fontSize: 16 }}>😀</span>,
    execute: () => {
      if (!emojiReady) {
        loadEmojiPicker().then((mods) => {
          emojiRef.current = mods;
          setEmojiReady(true);
          setShowEmoji(true);
        });
      } else {
        setShowEmoji(prev => !prev);
      }
    },
  };

  // Heading dropdown command (replaces separate h1/h2/h3 buttons)
  const headingCommand = {
    name: 'heading',
    keyCommand: 'heading',
    buttonProps: { 'aria-label': 'Heading level', title: 'Heading level' },
    icon: (
      <select
        style={{ background: 'transparent', border: 'none', color: 'var(--color-text-muted)', fontSize: 12, cursor: 'pointer', outline: 'none', padding: '0 2px' }}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => { headingLevelRef.current = e.target.value; e.target.value = ''; }}
        defaultValue=""
      >
        <option value="" disabled>¶ H▾</option>
        <option value="p">Paragraph</option>
        <option value="1">Heading 1</option>
        <option value="2">Heading 2</option>
        <option value="3">Heading 3</option>
      </select>
    ),
    execute: (state, api) => {
      const level = headingLevelRef.current;
      if (!level || level === 'p') { api.replaceSelection(state.selectedText.replace(/^#{1,6} /, '')); return; }
      const prefix = '#'.repeat(Number(level)) + ' ';
      const stripped = state.selectedText.replace(/^#{1,6} /, '');
      api.replaceSelection(prefix + (stripped || 'heading'));
    },
  };

  // Image upload command
  const imageUploadCommand = {
    name: 'image-upload',
    keyCommand: 'image-upload',
    buttonProps: { 'aria-label': 'Upload image', title: 'Upload Image' },
    icon: (
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
        <circle cx="8.5" cy="8.5" r="1.5"/>
        <polyline points="21 15 16 10 5 21"/>
      </svg>
    ),
    execute: () => {
      const input = document.createElement('input');
      input.type = 'file';
      input.accept = 'image/*';
      input.onchange = async (e) => {
        const file = e.target.files?.[0];
        if (!file) return;
        const url = await handleImageUpload(file);
        if (url) {
          onChange((value || '') + `\n![image](${url})\n`);
          dirtyRef.current = true;
          setSaveStatus('unsaved');
        }
      };
      input.click();
    },
  };

  // ── Toolbar config ──────────────────────────────────────────
  const toolbarCommands = [
    // Undo / redo
    undoCommand, redoCommand,
    commands.divider,
    // Inline formatting
    commands.bold, commands.italic, commands.strikethrough,
    commands.divider,
    // Heading dropdown (replaces h1/h2/h3 separate buttons)
    headingCommand,
    commands.divider,
    // Block elements
    commands.quote, commands.code, commands.codeBlock,
    commands.divider,
    // Links & images
    commands.link, commands.image, imageUploadCommand,
    commands.divider,
    // Lists
    commands.unorderedListCommand, commands.orderedListCommand, commands.checkedListCommand,
    commands.divider,
    // Table
    commands.table,
    commands.divider,
    // Emoji — at end, separated by divider
    emojiCommand,
  ];

  // ── Emoji select handler ────────────────────────────────────
  const handleEmojiSelect = useCallback((emoji) => {
    onChange((value || '') + emoji.native);
    dirtyRef.current = true;
    setSaveStatus('unsaved');
    setShowEmoji(false);
  }, [onChange, value]);

  // ── Render ──────────────────────────────────────────────────
  const statusLabels = {
    saved: 'Saved  (⌘S)',
    saving: 'Saving…',
    unsaved: 'Unsaved — ⌘S to save',
    error: 'Save failed — will retry',
  };

  const wordCount = (value || '').trim().split(/\s+/).filter(Boolean).length;
  const readingMins = Math.ceil(wordCount / 200);

  return (
    <div className="doc-editor-wrapper" data-color-mode="dark">
      {/* Draft recovery banner */}
      {draftBanner && (
        <div className="doc-editor-draft-banner">
          <span>📝 A local draft was found that&apos;s newer than the last save.</span>
          <button className="restore" onClick={restoreDraft}>Restore draft</button>
          <button onClick={discardDraft}>Discard</button>
        </div>
      )}

      {/* Save status + word count + reading time */}
      <div className="doc-editor-status">
        <span className={`status-dot ${saveStatus}`} />
        <span>{statusLabels[saveStatus]}</span>
        <span className="doc-editor-wordcount">
          {wordCount > 0 && `${wordCount.toLocaleString()} word${wordCount === 1 ? '' : 's'} · ~${readingMins} min read`}
        </span>
        {imageError && <span style={{ color: '#f44336', marginLeft: 'auto' }}>⚠ {imageError}</span>}
      </div>

        {/* Editor */}
        <div
          ref={editorRef}
          style={{ flex: 1, minHeight: 0, position: 'relative' }}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
        >
          <MDEditor
            value={value}
            onChange={handleChange}
            commands={toolbarCommands}
            extraCommands={[commands.divider, commands.codeEdit, commands.codeLive, commands.codePreview]}
            preview="live"
            height="100%"
            visibleDragbar
            textareaProps={{
              placeholder: 'Start writing…',
            }}
          />
  
          {/* Emoji picker popover */}
          {showEmoji && emojiRef.current && (
            <>
              <div className="emoji-picker-backdrop" onClick={() => setShowEmoji(false)} />
              <div className="emoji-picker-popover">
                <emojiRef.current.Picker
                  data={emojiRef.current.data}
                  onEmojiSelect={handleEmojiSelect}
                  theme="dark"
                  previewPosition="none"
                  skinTonePosition="none"
                  maxFrequentRows={2}
                />
              </div>
            </>
          )}
        </div>
    </div>
  );
}

DocEditor.propTypes = {
  docId: PropTypes.number,
  value: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  onSave: PropTypes.func.isRequired,
  updatedAt: PropTypes.string,
};

export default DocEditor;
