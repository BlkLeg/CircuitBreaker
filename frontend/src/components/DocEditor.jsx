import React, { useState, useEffect, useRef, useCallback } from 'react';
import MDEditor, { commands } from '@uiw/react-md-editor';
import '@uiw/react-md-editor/markdown-editor.css';
import data from '@emoji-mart/data';
import Picker from '@emoji-mart/react';
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
export default function DocEditor({ docId, value, onChange, onSave, updatedAt }) {
  const [saveStatus, setSaveStatus] = useState('saved'); // saved | saving | unsaved | error
  const [showEmoji, setShowEmoji] = useState(false);
  const [draftBanner, setDraftBanner] = useState(null); // { draftBody }
  const [imageError, setImageError] = useState(null);
  const dirtyRef = useRef(false);
  const backendTimerRef = useRef(null);
  const editorRef = useRef(null);

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

  // ── Custom toolbar commands ─────────────────────────────────

  // Emoji picker command
  const emojiCommand = {
    name: 'emoji',
    keyCommand: 'emoji',
    buttonProps: { 'aria-label': 'Insert emoji', title: 'Emoji' },
    icon: <span style={{ fontSize: 16 }}>😀</span>,
    execute: () => setShowEmoji(prev => !prev),
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
    commands.bold, commands.italic, commands.strikethrough,
    commands.divider,
    commands.title1, commands.title2, commands.title3,
    commands.divider,
    commands.quote, commands.code, commands.codeBlock,
    commands.divider,
    commands.link, commands.image, imageUploadCommand,
    commands.divider,
    commands.unorderedListCommand, commands.orderedListCommand, commands.checkedListCommand,
    commands.divider,
    commands.table,
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
    saved: 'Saved',
    saving: 'Saving…',
    unsaved: 'Unsaved changes',
    error: 'Save failed — will retry',
  };

  return (
    <div className="doc-editor-wrapper" data-color-mode="dark">
      {/* Draft recovery banner */}
      {draftBanner && (
        <div className="doc-editor-draft-banner">
          <span>📝 A local draft was found that's newer than the last save.</span>
          <button className="restore" onClick={restoreDraft}>Restore draft</button>
          <button onClick={discardDraft}>Discard</button>
        </div>
      )}

      {/* Save status */}
      <div className="doc-editor-status">
        <span className={`status-dot ${saveStatus}`} />
        <span>{statusLabels[saveStatus]}</span>
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
          extraCommands={[commands.codeEdit, commands.codeLive, commands.codePreview]}
          preview="live"
          height="100%"
          visibleDragbar
          textareaProps={{
            placeholder: 'Write Markdown here…',
          }}
        />

        {/* Emoji picker popover */}
        {showEmoji && (
          <>
            <div className="emoji-picker-backdrop" onClick={() => setShowEmoji(false)} />
            <div className="emoji-picker-popover">
              <Picker
                data={data}
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
