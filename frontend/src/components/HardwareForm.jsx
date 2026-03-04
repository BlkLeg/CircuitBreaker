import React, { useState } from 'react';
import PropTypes from 'prop-types';

import { hardwareApi } from '../api/client';

const HardwareForm = ({ hardware, onUpdated }) => {
  const [uploading, setUploading] = useState(false);

  const uploadIcon = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch('/api/v1/assets/user-icon', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('Upload failed');
      }

      const { url } = await response.json();
      const updated = await hardwareApi.update(hardware.id, { custom_icon: url });
      onUpdated?.(updated.data);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div>
      <label className="form-label" htmlFor="hardware-custom-icon">Custom Icon</label>
      <input
        id="hardware-custom-icon"
        type="file"
        accept="image/png,image/jpeg,image/svg+xml"
        onChange={(e) => uploadIcon(e.target.files?.[0])}
        disabled={uploading}
      />
      {hardware?.custom_icon && (
        <img src={hardware.custom_icon} alt="Custom" className="w-12 h-12" style={{ marginTop: 8 }} />
      )}
    </div>
  );
};

HardwareForm.propTypes = {
  hardware: PropTypes.shape({
    id: PropTypes.number.isRequired,
    custom_icon: PropTypes.string,
  }).isRequired,
  onUpdated: PropTypes.func,
};

HardwareForm.defaultProps = {
  onUpdated: null,
};

export default HardwareForm;
