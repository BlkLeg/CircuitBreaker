import React, { useState } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import { cveApi } from '../../api/client';
import { describeIdentityProvenance } from '../../lib/vulnerabilityAssessment';
import '../../styles/intel.css';

/**
 * Correct one entity's assessment identity.
 *
 * The revision the row was read at is sent back, so a correction that races
 * another one is rejected rather than silently overwriting it. A rejection keeps
 * every entered value: retyping what you just typed is not error recovery.
 */
function IdentityCorrectionDrawer({ row, onClose, onSaved }) {
  const identity = row?.identity || null;
  const [form, setForm] = useState({
    vendor: identity?.vendor || '',
    product: identity?.product || '',
    version: identity?.version || '',
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const field = (name) => (event) => setForm((f) => ({ ...f, [name]: event.target.value }));

  const save = async (event) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await cveApi.updateIdentity(row.entity_type, row.entity_id, {
        vendor: form.vendor || null,
        product: form.product || null,
        version: form.version || null,
        // No version_scheme, matching VulnerabilityPanel: the backend infers it
        // from the version just entered. Sending the previous scheme would pin a
        // dotted-numeric comparator to a version that is no longer one.
        revision: identity?.revision ?? 0,
      });
      onSaved(row);
    } catch (err) {
      setError(err?.userMessage || 'The identity could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <Drawer isOpen onClose={onClose} title={`Correct identity — ${row.name}`}>
      <form onSubmit={save}>
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        <p className="tw-text-sm tw-opacity-70">
          {describeIdentityProvenance(identity) ||
            'This entity has no identity yet. What you enter here becomes the operator identity.'}
        </p>
        <label htmlFor="identity-vendor">Vendor</label>
        <input id="identity-vendor" value={form.vendor} onChange={field('vendor')} />
        <label htmlFor="identity-product">Product</label>
        <input id="identity-product" value={form.product} onChange={field('product')} />
        <label htmlFor="identity-version">Version</label>
        <input id="identity-version" value={form.version} onChange={field('version')} />
        <div className="drawer-actions">
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn btn-sm btn-primary" disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </form>
    </Drawer>
  );
}

IdentityCorrectionDrawer.propTypes = {
  row: PropTypes.shape({
    entity_type: PropTypes.string.isRequired,
    entity_id: PropTypes.number.isRequired,
    name: PropTypes.string,
    identity: PropTypes.object,
  }).isRequired,
  onClose: PropTypes.func.isRequired,
  onSaved: PropTypes.func.isRequired,
};

export default IdentityCorrectionDrawer;
