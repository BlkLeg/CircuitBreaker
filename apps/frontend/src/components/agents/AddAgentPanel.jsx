import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { getInstallCommand, mintEnrollmentToken } from '../../api/agents';
import { useSettings } from '../../context/SettingsContext';
import { operatorErrorMessage } from '../../lib/agentErrors';
import { agentDisplayName } from '../../lib/agentLabel';
import { useToast } from '../common/Toast';
import AddAgentInstallStep from './AddAgentInstallStep';
import AddAgentApproveStep from './AddAgentApproveStep';
import AddAgentPairingCode from './AddAgentPairingCode';

// `data-state` on each <li>, which is what styles the step rail. Named rather
// than inlined so the CSS selector list and this file cannot drift apart.
const STEP_DONE = 'done';
const STEP_ACTIVE = 'active';
const STEP_WAITING = 'waiting';

// A step is `done` once its outcome exists, `active` once the step before it
// has produced what this one needs, and `waiting` until then — so the rail
// never invites the operator to act on a step that cannot yet do anything.
function stepState(isDone, isActive) {
  if (isDone) return STEP_DONE;
  return isActive ? STEP_ACTIVE : STEP_WAITING;
}

const GENERIC_INSTALL_ERROR =
  'Could not generate an install command. Check the server’s TLS certificate and try again.';
// GET /agents/install-command is require_role("admin") while this page is
// viewer-visible, so a 403 here is the normal outcome for a non-admin operator,
// not a fault. Saying who can get them one beats echoing "Not enough
// permissions" at someone who cannot act on it.
const INSTALL_ADMIN_ONLY = 'Ask an administrator for the install command';

// Spec §6 item 3. An install that is going to fail fails silently: the agent
// that would report "I cannot reach you" is the one that cannot reach us. After
// this long with no check-in, say which address to go and verify rather than
// spinning "listening…" indefinitely.
const CHECK_IN_OVERDUE_MS = 90_000;

const MODE_ATTENDED = 'attended';
const MODE_UNATTENDED = 'unattended';
// One hour, matching the server default: long enough for a human to paste the
// value into a launch template, short enough that a forgotten token expires.
const TOKEN_TTL_SECONDS = 3600;
const GENERIC_MINT_ERROR = 'Could not create an enrollment token';

// The endpoint whose address matches the one this browser is on is the likeliest
// correct choice for a LAN agent, and picking it reproduces today's behaviour
// for an operator who never opens the picker. Falling back to the first
// declared endpoint beats falling back to none: an empty choice sends the
// browsed host, which is exactly the address the list exists to override.
function defaultEndpointId(endpoints) {
  if (endpoints.length === 0) return '';
  const match = endpoints.find((e) => e.url === globalThis.location.origin);
  return (match ?? endpoints[0]).id ?? '';
}

// AGT-15: the server answers 503 with an operator-fixable reason when it has
// one (an unreadable TLS cert names the path and the chmod that fixes it), and
// preferring it over generic text is what makes the failure actionable. It is
// passed through `operatorErrorMessage`, which redacts secret-shaped material
// on the way — this surface must not depend on every present and future error
// on that route having been written carefully. See lib/agentErrors.js.
function installErrorMessage(err) {
  return operatorErrorMessage(err, {
    fallback: GENERIC_INSTALL_ERROR,
    forbidden: INSTALL_ADMIN_ONLY,
  });
}

/**
 * The guided add-agent flow (design §"Design direction", Cloudflare reference):
 * hand over a command, watch for the machine to appear, then approve — one
 * continuous flow that ends when the agent is approved, rather than a command
 * handed over and an enrollment surfacing somewhere else minutes later.
 *
 * `pendingAgents` is the page's pending rows, so the waiting → checked-in
 * transition is driven by the same data the fleet table is: the live `enrolled`
 * event splices a pending row in immediately, and this panel simply notices.
 */
export default function AddAgentPanel({
  isStandalone,
  pendingAgents = [],
  onApproved,
  onDismiss,
  onReview,
  onPairingResolved,
}) {
  const toast = useToast();
  const { settings } = useSettings();
  // Only the *operator's* toggle lives in state. Whether the panel is open is
  // derived below, because `isStandalone` can turn true after mount — deleting
  // the last agent empties the fleet — and a seeded initial state would leave
  // the page showing nothing but a collapsed "Add agent" button where the panel
  // is supposed to BE the page.
  const [isExpanded, setIsExpanded] = useState(false);
  const [installCommand, setInstallCommand] = useState(null);
  const [installError, setInstallError] = useState(null);
  const [isLoadingCommand, setIsLoadingCommand] = useState(false);
  const isMountedRef = useRef(true);

  const endpoints = useMemo(() => settings?.agent_endpoints ?? [], [settings]);
  // '' is "not chosen yet", which is distinct from "chosen nothing": the
  // settings context loads asynchronously, so an explicit choice has to survive
  // the list arriving, and the derived value below covers the gap before it does.
  const [chosenEndpoint, setChosenEndpoint] = useState('');
  // Slice B. Attended is the default and is what shipped; unattended is opt-in
  // and mints a bearer credential, so nothing here happens without an explicit
  // click. `mintedToken` holds the plaintext for exactly as long as the panel
  // is showing it — it is not recoverable from the server afterwards.
  const [mode, setMode] = useState(MODE_ATTENDED);
  const [mintedToken, setMintedToken] = useState(null);
  const [mintError, setMintError] = useState(null);
  const [isMinting, setIsMinting] = useState(false);
  const selectedEndpoint =
    chosenEndpoint && endpoints.some((e) => e.id === chosenEndpoint)
      ? chosenEndpoint
      : defaultEndpointId(endpoints);
  const selectedEndpointUrl = endpoints.find((e) => e.id === selectedEndpoint)?.url ?? '';

  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);

  const loadInstallCommand = useCallback(async () => {
    setIsLoadingCommand(true);
    setInstallError(null);
    try {
      const { data } = await getInstallCommand(selectedEndpoint, mintedToken?.token ?? null);
      if (isMountedRef.current) setInstallCommand(data);
    } catch (err) {
      if (!isMountedRef.current) return;
      const message = installErrorMessage(err);
      // Inline *and* toast, deliberately (design §4): inline puts the reason
      // where the operator is already looking, and the toast is what reaches
      // them if they have scrolled past the panel by the time it answers.
      setInstallError(message);
      toast.error(message);
    } finally {
      if (isMountedRef.current) setIsLoadingCommand(false);
    }
    // The token is a dependency because the command carries it: minting has to
    // re-issue the command, or the operator copies an attended one.
  }, [selectedEndpoint, mintedToken]); // eslint-disable-line react-hooks/exhaustive-deps

  // A token is scoped to one endpoint, so a change to either the endpoint or
  // the mode drops it. Left in place it would emit a command whose token the
  // server refuses, or — going back to attended — hand the operator a command
  // still carrying a credential they think they abandoned.
  const dropToken = useCallback(() => {
    setMintedToken(null);
    setMintError(null);
  }, []);

  const handleEndpointChange = (id) => {
    dropToken();
    setChosenEndpoint(id);
  };

  const handleModeChange = (next) => {
    dropToken();
    setMode(next);
  };

  const handleMint = async () => {
    setIsMinting(true);
    setMintError(null);
    try {
      const { data } = await mintEnrollmentToken({
        label: `Unattended install — ${selectedEndpointUrl || 'this server'}`,
        endpoint_id: selectedEndpoint,
        ttl_seconds: TOKEN_TTL_SECONDS,
        max_uses: 1,
      });
      if (isMountedRef.current) setMintedToken(data);
    } catch (err) {
      if (!isMountedRef.current) return;
      // Inline and toast, matching how installError is handled above.
      const message = operatorErrorMessage(err, {
        fallback: GENERIC_MINT_ERROR,
        forbidden: INSTALL_ADMIN_ONLY,
      });
      setMintError(message);
      toast.error(message);
    } finally {
      if (isMountedRef.current) setIsMinting(false);
    }
  };

  const isOpen = Boolean(isStandalone) || isExpanded;

  // Standalone means the fleet is empty and this panel *is* the page, so the
  // command is fetched without waiting to be asked. Inline, the fetch is the
  // operator opening the panel — and re-opening after a failure retries it.
  // Keying on the chosen endpoint too is what makes the picker do anything: the
  // command carries the address, so changing the address has to re-issue it.
  useEffect(() => {
    if (isOpen) loadInstallCommand();
  }, [isOpen, loadInstallCommand]);

  const hasCheckedIn = pendingAgents.length > 0;
  const checkedInNames = pendingAgents.map((a) => agentDisplayName(a, a.id)).join(', ');

  // Restarted whenever the command changes, so re-issuing it for a different
  // endpoint gives that address its own fair wait rather than inheriting the
  // previous one's expired clock.
  const [isCheckInOverdue, setIsCheckInOverdue] = useState(false);
  useEffect(() => {
    setIsCheckInOverdue(false);
    if (!installCommand || hasCheckedIn) return undefined;
    const timer = setTimeout(() => setIsCheckInOverdue(true), CHECK_IN_OVERDUE_MS);
    return () => clearTimeout(timer);
  }, [installCommand, hasCheckedIn]);

  if (!isOpen) {
    return (
      <section className="add-agent">
        <button type="button" onClick={() => setIsExpanded(true)}>
          Add agent
        </button>
      </section>
    );
  }

  return (
    <section
      className={isStandalone ? 'add-agent add-agent--standalone' : 'add-agent'}
      aria-label="Add an agent"
    >
      <h2>Add an agent</h2>
      {!isStandalone && (
        <button
          type="button"
          onClick={() => {
            setIsExpanded(false);
            onDismiss?.();
          }}
        >
          Close
        </button>
      )}

      <ol className="add-agent__steps">
        <li className="add-agent__step" data-state={stepState(Boolean(installCommand), true)}>
          <h3>Run this on the new machine</h3>

          {/* The address is part of the command, so it is chosen here rather
              than buried in settings the operator would have to go and read. */}
          {endpoints.length === 0 ? (
            <p className="add-agent__warning">
              No agent endpoints are configured, so this command will use the address you are
              browsing ({globalThis.location.origin}). An agent on another network will not be able
              to reach it. Add an endpoint in Settings → Connectivity.
            </p>
          ) : (
            <label htmlFor="add-agent-endpoint" className="add-agent__endpoint">
              Endpoint
              <select
                id="add-agent-endpoint"
                value={selectedEndpoint}
                onChange={(e) => handleEndpointChange(e.target.value)}
              >
                {endpoints.map((e) => (
                  <option key={e.id} value={e.id}>{`${e.label} — ${e.url}`}</option>
                ))}
              </select>
            </label>
          )}

          {/* Attended is the default and is what shipped. Unattended mints a
              bearer credential, so it is opt-in twice over: choosing it does
              nothing until the operator asks for a token. */}
          <fieldset className="add-agent__mode">
            <legend>Approval</legend>
            <div className="add-agent__mode-options">
              <label htmlFor="add-agent-mode-attended">
                <input
                  id="add-agent-mode-attended"
                  type="radio"
                  name="add-agent-mode"
                  value={MODE_ATTENDED}
                  checked={mode === MODE_ATTENDED}
                  onChange={() => handleModeChange(MODE_ATTENDED)}
                />
                Attended — you approve the machine here
              </label>
              <label htmlFor="add-agent-mode-unattended">
                <input
                  id="add-agent-mode-unattended"
                  type="radio"
                  name="add-agent-mode"
                  value={MODE_UNATTENDED}
                  checked={mode === MODE_UNATTENDED}
                  onChange={() => handleModeChange(MODE_UNATTENDED)}
                />
                Unattended — the machine enrolls itself with a token
              </label>
            </div>
          </fieldset>

          {mode === MODE_UNATTENDED && (
            <div className="add-agent__token">
              {!mintedToken && (
                <>
                  <p>
                    A token lets this machine enrol without waiting for approval. It is a bearer
                    credential: anything presenting it enrols, until it is used or expires.
                  </p>
                  <button type="button" onClick={handleMint} disabled={isMinting}>
                    {isMinting ? 'Generating…' : 'Generate token'}
                  </button>
                </>
              )}
              {mintError && (
                <p className="add-agent__error" role="alert">
                  {mintError}
                </p>
              )}
              {mintedToken && (
                <>
                  <p>This machine will enrol without waiting for approval.</p>
                  <p>
                    One use, expires in an hour. <strong>It will not be shown again</strong> — the
                    server keeps only a hash of it.
                  </p>
                  <code className="add-agent__token-value">{mintedToken.token}</code>
                  <p>
                    It is already in the command below, as an environment variable. Copy the command
                    whole and do not pass the token as an argument: arguments are visible in{' '}
                    <code>ps</code> and land in shell history and cloud-init logs.
                  </p>
                </>
              )}
            </div>
          )}

          <AddAgentInstallStep
            installCommand={installCommand}
            errorMessage={installError}
            isLoading={isLoadingCommand}
          />
        </li>

        <li
          className="add-agent__step"
          data-state={stepState(hasCheckedIn, Boolean(installCommand))}
        >
          {/* The heading an operator is waiting on changes meaning once the
              machine appears: before, the open question is whether it can reach
              the server at all; after, it is whether they trust it. */}
          {hasCheckedIn ? (
            <>
              <h3>Waiting for approval</h3>
              <p>{checkedInNames} checked in.</p>
            </>
          ) : (
            <>
              <h3>Waiting for the machine to check in</h3>
              <span className="add-agent__chip">listening…</span>
              <p>The moment it enrolls it appears here — no need to reload.</p>
              {/* Spec §6 item 3: an agent that cannot reach the server cannot
                  say so, so after long enough this names the address to check
                  rather than leaving "listening…" to imply progress. */}
              {isCheckInOverdue && (
                <p className="add-agent__warning">
                  Nothing has checked in yet. The agent was told to dial{' '}
                  <code>{selectedEndpointUrl || globalThis.location.origin}</code> — confirm that
                  address resolves and is reachable from the machine you installed on.
                </p>
              )}
            </>
          )}
        </li>

        <li className="add-agent__step" data-state={stepState(false, hasCheckedIn)}>
          <h3>Approve it</h3>
          {hasCheckedIn ? (
            <AddAgentApproveStep
              agents={pendingAgents}
              onResolved={onApproved}
              onReview={onReview}
            />
          ) : (
            <p>Compare the fingerprint the agent prints against the one shown here.</p>
          )}
        </li>
      </ol>

      <AddAgentPairingCode onResolved={onPairingResolved} />
    </section>
  );
}

AddAgentPanel.propTypes = {
  isStandalone: PropTypes.bool,
  pendingAgents: PropTypes.arrayOf(PropTypes.object),
  onApproved: PropTypes.func,
  onDismiss: PropTypes.func,
  onReview: PropTypes.func,
  onPairingResolved: PropTypes.func,
};
