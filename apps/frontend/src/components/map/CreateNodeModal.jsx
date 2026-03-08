import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import {
  X,
  Server,
  Router,
  Network,
  Shield,
  Wifi,
  HardDrive,
  Zap,
  Plug,
  Laptop,
  Monitor,
  Box,
  Package,
  Cloud,
} from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import IconPickerModal, { IconImg } from '../common/IconPickerModal';

const roles = [
  { id: 'server', label: 'Server', icon: Server, type: 'Compute' },
  { id: 'router', label: 'Router', icon: Router, type: 'Network' },
  { id: 'switch', label: 'Switch', icon: Network, type: 'Network' },
  { id: 'firewall', label: 'Firewall', icon: Shield, type: 'Security' },
  { id: 'access_point', label: 'Access Point', icon: Wifi, type: 'Network' },
  { id: 'nas', label: 'NAS', icon: HardDrive, type: 'Storage' },
  { id: 'ups', label: 'UPS', icon: Zap, type: 'Power' },
  { id: 'pdu', label: 'PDU', icon: Plug, type: 'Power' },
  { id: 'laptop', label: 'Laptop', icon: Laptop, type: 'Compute' },
  { id: 'desktop', label: 'Desktop', icon: Monitor, type: 'Compute' },
  { id: 'vm', label: 'VM', icon: Box, type: 'Compute' },
  { id: 'container', label: 'Container', icon: Package, type: 'Compute' },
  { id: 'cloud', label: 'Cloud', icon: Cloud, type: 'Network' },
];

export default function CreateNodeModal({ isOpen, onClose, onConfirm, position }) {
  const [label, setLabel] = useState('');
  const [subLabel, setSubLabel] = useState('');
  const [selectedRole, setSelectedRole] = useState(roles[0]);
  const [selectedIconSlug, setSelectedIconSlug] = useState(null);
  const [showIconPicker, setShowIconPicker] = useState(false);

  useEffect(() => {
    if (!isOpen) {
      setShowIconPicker(false);
    }
  }, [isOpen]);

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!label) return;

    onConfirm({
      label,
      subLabel,
      type: selectedRole.type,
      iconType: selectedRole.id, // we map this to _hwRole / role dynamically
      icon_slug: selectedIconSlug,
      position,
    });

    // Reset form
    setLabel('');
    setSubLabel('');
    setSelectedRole(roles[0]);
    setSelectedIconSlug(null);
  };

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="tw-fixed tw-inset-0 tw-bg-black/70 tw-backdrop-blur-sm tw-z-50 tw-flex tw-items-center tw-justify-center"
          >
            {/* Modal */}
            <motion.div
              initial={{ scale: 0.95, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.95, opacity: 0, y: 20 }}
              onClick={(e) => e.stopPropagation()}
              role="dialog"
              aria-modal="true"
              aria-labelledby="create-node-modal-title"
              className="tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-xl tw-shadow-2xl tw-w-full tw-max-w-2xl tw-overflow-hidden tw-flex tw-flex-col tw-max-h-[90vh]"
            >
              <div className="tw-flex tw-items-center tw-justify-between tw-px-6 tw-py-4 tw-border-b tw-border-cb-border tw-bg-cb-secondary">
                <h3
                  id="create-node-modal-title"
                  className="tw-text-cb-text tw-font-bold tw-text-lg tw-font-mono"
                >
                  Create New Node
                </h3>
                <button
                  type="button"
                  onClick={onClose}
                  aria-label="Close create node dialog"
                  className="tw-w-7 tw-h-7 tw-rounded-full tw-border tw-border-cb-border tw-text-cb-text-muted tw-hover:tw-text-cb-text tw-hover:tw-bg-cb-bg tw-transition-colors tw-inline-flex tw-items-center tw-justify-center"
                >
                  <X className="tw-w-4 tw-h-4" />
                </button>
              </div>

              <div className="tw-flex tw-flex-1 tw-overflow-hidden">
                {/* Left: Form */}
                <div className="tw-w-1/2 tw-p-6 tw-border-r tw-border-cb-border tw-overflow-y-auto">
                  <form id="create-node-form" onSubmit={handleSubmit} className="tw-space-y-6">
                    <div>
                      <label
                        htmlFor="create-node-name"
                        className="tw-block tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider tw-mb-2"
                      >
                        Name / Device Lookup
                      </label>
                      <input
                        id="create-node-name"
                        type="text"
                        value={label}
                        onChange={(e) => setLabel(e.target.value)}
                        placeholder="e.g. OptiPlex 7080 SFF"
                        className="tw-w-full tw-bg-cb-bg tw-border tw-border-cb-border tw-rounded-lg tw-px-4 tw-py-2.5 tw-text-cb-text tw-placeholder:text-cb-muted tw-focus:outline-none tw-focus:border-blue-500/50 tw-transition-colors tw-font-mono tw-text-sm"
                        autoFocus
                      />
                    </div>

                    <div>
                      <label
                        htmlFor="create-node-ip"
                        className="tw-block tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider tw-mb-2"
                      >
                        IP Address
                      </label>
                      <input
                        id="create-node-ip"
                        type="text"
                        value={subLabel}
                        onChange={(e) => setSubLabel(e.target.value)}
                        placeholder="e.g. 10.10.10.4"
                        className="tw-w-full tw-bg-cb-bg tw-border tw-border-cb-border tw-rounded-lg tw-px-4 tw-py-2.5 tw-text-cb-text tw-placeholder:text-cb-muted tw-focus:outline-none tw-focus:border-blue-500/50 tw-transition-colors tw-font-mono tw-text-sm"
                      />
                    </div>

                    <div>
                      <div className="tw-block tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider tw-mb-2">
                        Selected Role
                      </div>
                      <div className="tw-flex tw-items-center tw-gap-3 tw-p-3 tw-rounded-lg tw-bg-cb-secondary tw-border tw-border-cb-border">
                        <div className="tw-w-10 tw-h-10 tw-rounded-full tw-bg-blue-500/20 tw-flex tw-items-center tw-justify-center tw-text-cb-primary">
                          <selectedRole.icon className="tw-w-5 tw-h-5" />
                        </div>
                        <div>
                          <div className="tw-text-cb-text tw-font-medium tw-text-sm">
                            {selectedRole.label}
                          </div>
                          <div className="tw-text-cb-muted tw-text-xs">{selectedRole.type}</div>
                        </div>
                      </div>
                    </div>

                    <div>
                      <div className="tw-block tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider tw-mb-2">
                        Icon
                      </div>
                      <div className="tw-flex tw-items-center tw-justify-between tw-gap-3 tw-p-3 tw-rounded-lg tw-bg-cb-secondary tw-border tw-border-cb-border">
                        <div className="tw-flex tw-items-center tw-gap-3">
                          {selectedIconSlug ? (
                            <IconImg slug={selectedIconSlug} size={22} />
                          ) : (
                            <div className="tw-w-[22px] tw-h-[22px] tw-rounded tw-bg-cb-bg tw-border tw-border-cb-border" />
                          )}
                          <div className="tw-text-xs tw-text-cb-muted">
                            {selectedIconSlug || 'No custom icon selected'}
                          </div>
                        </div>
                        <button
                          type="button"
                          className="btn"
                          onClick={() => setShowIconPicker(true)}
                        >
                          Pick Icon
                        </button>
                      </div>
                    </div>

                    <div className="tw-pt-4">
                      <button
                        type="submit"
                        disabled={!label}
                        className="tw-w-full tw-bg-cb-primary tw-hover:bg-cb-primary-h tw-disabled:opacity-50 tw-disabled:cursor-not-allowed tw-text-cb-text tw-font-medium tw-py-2.5 tw-rounded-lg tw-transition-colors tw-shadow-lg tw-shadow-[var(--color-primary-hover)]/20"
                      >
                        Create Node
                      </button>
                    </div>
                  </form>
                </div>

                {/* Right: Role Selection */}
                <div className="tw-w-1/2 tw-bg-cb-bg tw-flex tw-flex-col">
                  <div className="tw-px-4 tw-py-3 tw-border-b tw-border-cb-border tw-bg-cb-secondary">
                    <span className="tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider">
                      Select Role
                    </span>
                  </div>
                  <div className="tw-flex-1 tw-overflow-y-auto tw-p-2">
                    <div className="tw-grid tw-grid-cols-1 tw-gap-1">
                      {roles.map((role) => (
                        <button
                          key={role.id}
                          type="button"
                          onClick={() => setSelectedRole(role)}
                          aria-pressed={selectedRole.id === role.id}
                          className={`tw-flex tw-items-center tw-gap-3 tw-px-4 tw-py-3 tw-rounded-lg tw-text-left tw-transition-all ${
                            selectedRole.id === role.id
                              ? 'tw-bg-cb-secondary tw-border tw-border-cb-primary tw-text-cb-text tw-shadow-sm'
                              : 'tw-bg-cb-surface tw-border tw-border-cb-border tw-text-cb-text tw-hover:tw-bg-cb-secondary tw-hover:tw-border-cb-primary/60 tw-hover:tw-shadow-sm'
                          }`}
                        >
                          <role.icon
                            className={`tw-w-4 tw-h-4 ${selectedRole.id === role.id ? 'tw-text-cb-primary' : 'tw-text-cb-text-muted'}`}
                          />
                          <span className="tw-text-sm tw-font-medium">{role.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>

          {showIconPicker && (
            <IconPickerModal
              currentSlug={selectedIconSlug}
              onSelect={(slug) => setSelectedIconSlug(slug || null)}
              onClose={() => setShowIconPicker(false)}
            />
          )}
        </>
      )}
    </AnimatePresence>
  );
}

CreateNodeModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
  position: PropTypes.shape({
    x: PropTypes.number,
    y: PropTypes.number,
  }),
};
