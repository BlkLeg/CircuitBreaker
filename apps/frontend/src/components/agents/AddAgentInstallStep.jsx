import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useToast } from '../common/Toast';

// The installer the backend hands out is a Linux shell script — agent_install
// builds it around `useradd` and `sha256sum` — so the other two platforms are
// advertised as not-yet-available instead of being quietly omitted. Offering a
// macOS or Windows tab that produced *something* would mean inventing a package
// nobody builds; showing them disabled answers "is this coming?" honestly.
const PLATFORMS = [
  { value: 'linux', label: 'Linux', isSupported: true },
  { value: 'macos', label: 'macOS', isSupported: false },
  { value: 'windows', label: 'Windows', isSupported: false },
];
const DEFAULT_PLATFORM = 'linux';
const UNSUPPORTED_PLATFORM_TITLE = 'Agent packages are Linux-only today';
// Long enough for the operator to register that the click landed, short enough
// that the button is back to its normal label before they look again.
const COPY_FEEDBACK_MS = 2000;
const PUBLIC_TLS_MODE = 'public';

/**
 * Step 1 of the guided add-agent flow: platform, the command itself, and the
 * two things an operator is supposed to check before running it — which TLS
 * mode the command was built for, and the digest of the script it pipes.
 *
 * Fetching lives in AddAgentPanel, not here: the same failure has to render
 * inline *and* toast, and the panel is what owns whether the flow has started.
 */
export default function AddAgentInstallStep({ installCommand, errorMessage, isLoading }) {
  const toast = useToast();
  const [platform, setPlatform] = useState(DEFAULT_PLATFORM);
  const [isCopied, setIsCopied] = useState(false);
  const copyTimerRef = useRef(null);

  useEffect(() => () => clearTimeout(copyTimerRef.current), []);

  const handleCopy = async () => {
    // navigator.clipboard is absent in jsdom and on any insecure origin — which
    // is how this homelab UI is routinely reached, over plain http on a LAN.
    // Reading `.writeText` off undefined throws synchronously; inside an async
    // function that surfaces as a rejection this try/catch owns, so the button
    // degrades to "select it yourself" instead of blowing up the panel.
    try {
      await navigator.clipboard.writeText(installCommand.command);
      setIsCopied(true);
      copyTimerRef.current = setTimeout(() => setIsCopied(false), COPY_FEEDBACK_MS);
    } catch {
      toast.error('Clipboard unavailable here — select the command and copy it manually');
    }
  };

  const tlsLabel = installCommand?.tls_mode === PUBLIC_TLS_MODE ? 'trusted TLS' : 'self-signed';

  return (
    <>
      <div className="add-agent__platforms" role="group" aria-label="Install platform">
        {PLATFORMS.map(({ value, label, isSupported }) => (
          <button
            key={value}
            type="button"
            disabled={!isSupported}
            title={isSupported ? undefined : UNSUPPORTED_PLATFORM_TITLE}
            aria-pressed={platform === value}
            onClick={() => setPlatform(value)}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading && <p>Generating an install command…</p>}

      {/* Design §4: the reason a 503 (or a 403) came back renders where the
          operator is already looking, not only in a toast that has faded by the
          time they scroll back to the panel. */}
      {errorMessage && (
        <p role="alert" className="add-agent__error">
          {errorMessage}
        </p>
      )}

      {installCommand && (
        <>
          <pre className="add-agent__command">{installCommand.command}</pre>
          <button type="button" className="add-agent__copy" onClick={handleCopy}>
            {isCopied ? 'Copied' : 'Copy'}
          </button>
          <span className="add-agent__chip">{tlsLabel}</span>
          <p className="add-agent__digest">
            <code>sha256:{installCommand.script_sha256}</code> — compare this digest against the
            script before piping it to a shell.
          </p>
        </>
      )}
    </>
  );
}

AddAgentInstallStep.propTypes = {
  installCommand: PropTypes.shape({
    command: PropTypes.string,
    tls_mode: PropTypes.string,
    script_sha256: PropTypes.string,
  }),
  errorMessage: PropTypes.string,
  isLoading: PropTypes.bool,
};
