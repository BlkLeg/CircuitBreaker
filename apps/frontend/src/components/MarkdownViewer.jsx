import React from 'react';
import ReactMarkdown from 'react-markdown';
import DOMPurify from 'dompurify';

function MarkdownViewer({ content, html }) {
  // Prefer pre-rendered HTML when available (faster, client-sanitized with DOMPurify)
  if (html) {
    return (
      <div
        className="markdown-viewer"
        dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(html) }}
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
