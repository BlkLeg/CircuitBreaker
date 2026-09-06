import React, { useCallback, useState } from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const COPIED_MS = 1200;

/**
 * A monospace value with a copy button.
 *
 * Truncation shows head AND tail. These values — agent fingerprints, scope
 * versions — exist to be compared character by character against something
 * printed elsewhere, and truncating only the tail hides half of what is being
 * checked. The full value is always what gets copied and always what `title`
 * carries, so nothing is lost to the abbreviation.
 */
export default function CopyField({ value, label, head = null, tail = 4 }) {
  const [copied, setCopied] = useState(false);

  const display =
    head === null || value.length <= head + tail
      ? value
      : `${value.slice(0, head)}…${value.slice(-tail)}`;

  const onCopy = useCallback(() => {
    // Clipboard access is denied outright in some embedded browsers. The copy
    // is a convenience over a value that is already on screen and selectable,
    // so a failure is silent rather than a toast the operator cannot act on.
    Promise.resolve(navigator.clipboard?.writeText(value))
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), COPIED_MS);
      })
      .catch(() => {});
  }, [value]);

  return (
    <span className="cb-copy">
      <code title={value}>{display}</code>
      <button type="button" className="cb-copy__btn" onClick={onCopy} aria-label={`Copy ${label}`}>
        {copied ? '✓' : '⧉'}
      </button>
    </span>
  );
}

CopyField.propTypes = {
  value: PropTypes.string.isRequired,
  label: PropTypes.string.isRequired,
  head: PropTypes.number,
  tail: PropTypes.number,
};
