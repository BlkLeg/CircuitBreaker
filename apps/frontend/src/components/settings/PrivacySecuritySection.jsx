import React from 'react';
import PropTypes from 'prop-types';
import SettingField from './SettingField';
import SettingSection from './SettingSection';

function PrivacySecuritySection({ form, set }) {
  return (
    <SettingSection title="Privacy & Threat Intelligence">
      <SettingField
        label="Enable Privacy Scoring"
        hint="Score devices and the network from scan results, run hostile-network checks, and refresh the public threat feed."
      >
        <label className="toggle-switch">
          <span className="sr-only">Enable Privacy Scoring</span>
          <input
            type="checkbox"
            checked={form.windscribe_enabled ?? true}
            onChange={(e) => set('windscribe_enabled', e.target.checked)}
          />
          <span className="toggle-switch-track" />
        </label>
      </SettingField>

      {(form.windscribe_enabled ?? true) && (
        <SettingField
          label="Feed Refresh Interval (hours)"
          hint="How often the threat-intelligence blocklists are refreshed (1-168)."
        >
          <input
            className="form-control"
            type="number"
            min={1}
            max={168}
            value={form.windscribe_feed_refresh_hours ?? 1}
            onChange={(e) =>
              set('windscribe_feed_refresh_hours', Number.parseInt(e.target.value, 10) || 1)
            }
            style={{ width: 100 }}
          />
        </SettingField>
      )}
    </SettingSection>
  );
}

PrivacySecuritySection.propTypes = {
  form: PropTypes.object.isRequired,
  set: PropTypes.func.isRequired,
};

export default PrivacySecuritySection;
