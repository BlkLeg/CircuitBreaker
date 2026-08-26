import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { lookupPairingCode } from '../../api/agents';
import { PAIRING_LOOKUP_FAILED } from '../../lib/agentErrors';
import { useToast } from '../common/Toast';

/**
 * The alternate enrollment path, kept rather than dropped by the redesign: an
 * agent that printed a pairing code can be pulled up by it directly, without
 * waiting for it to surface as a pending row.
 *
 * Its own component because it owns its own input state and its own request —
 * folding that back into AddAgentPanel would put a third unrelated async
 * failure mode inside the panel that already owns the install command's.
 *
 * The label text and the input id are load-bearing: an existing test drives
 * this by `getByLabelText('Or paste a pairing code:')`.
 */
export default function AddAgentPairingCode({ onResolved }) {
  const toast = useToast();
  const [code, setCode] = useState('');

  const handleSubmit = async () => {
    try {
      const { data } = await lookupPairingCode(code.trim());
      onResolved?.(data.agent_id);
      setCode('');
    } catch {
      // AGT-15: one message for every cause, and the code the operator typed is
      // never echoed back. The endpoint is reachable by any authenticated user
      // and takes a short, guessable code, so distinguishing "no such code"
      // from "expired" from "already approved" would make this form an oracle
      // for enumerating pending enrollments. See lib/agentErrors.js.
      toast.error(PAIRING_LOOKUP_FAILED);
    }
  };

  return (
    <div className="add-agent__pairing">
      <label htmlFor="pairing-code-input">Or paste a pairing code:</label>
      <input
        id="pairing-code-input"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="XXXX-XXXX-XXXX"
      />
      <button type="button" onClick={handleSubmit}>
        Look up
      </button>
    </div>
  );
}

AddAgentPairingCode.propTypes = {
  onResolved: PropTypes.func,
};
