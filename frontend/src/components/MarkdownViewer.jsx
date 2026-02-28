import React from 'react';
import ReactMarkdown from 'react-markdown';

function MarkdownViewer({ content, html }) {
  // Prefer pre-rendered HTML when available (faster, server-sanitized)
  if (html) {
    return (
      <div
        className="markdown-viewer"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  // Fallback: render Markdown client-side
  return (
    <div className="markdown-viewer">
      <ReactMarkdown>{content || ''}</ReactMarkdown>
    </div>
  );
}

export default MarkdownViewer;
