import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import { certificatesApi } from '../../api/client';
import { Shield, Clock, RefreshCw, FileText, Copy, Check } from 'lucide-react';
import { useToast } from '../common/Toast';

function CertificateDetail({ certificate, isOpen, onClose, onUpdate }) {
  const toast = useToast();
  const [fullCert, setFullCert] = useState(null);
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);

  const fetchDetail = useCallback(async () => {
    if (!certificate) return;
    setLoading(true);
    try {
      const res = await certificatesApi.get(certificate.id);
      setFullCert(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [certificate, toast]);

  useEffect(() => {
    if (isOpen) {
      fetchDetail();
      setCopied(false);
    }
  }, [isOpen, fetchDetail]);

  const handleRenew = async () => {
    try {
      await certificatesApi.renew(certificate.id);
      toast.success('Renewal triggered successfully.');
      onUpdate?.();
      fetchDetail();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    toast.success('Copied to clipboard.');
  };

  if (!certificate) return null;

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Certificate: ${certificate.domain}`}>
      <div className="tw-space-y-6">
        {/* Overview Section */}
        <div className="tw-bg-cb-secondary/30 tw-p-4 tw-rounded-lg tw-border tw-border-cb-border">
          <div className="tw-grid tw-grid-cols-2 tw-gap-4">
            <div>
              <label className="tw-text-xs tw-text-cb-text-muted tw-uppercase tw-font-bold">
                Domain
              </label>
              <div className="tw-flex tw-items-center tw-gap-2">
                <Shield size={14} className="tw-text-cb-primary" />
                <span className="tw-font-medium">{certificate.domain}</span>
              </div>
            </div>
            <div>
              <label className="tw-text-xs tw-text-cb-text-muted tw-uppercase tw-font-bold">
                Type
              </label>
              <div>{certificate.type === 'letsencrypt' ? "Let's Encrypt" : 'Self-Signed'}</div>
            </div>
            <div>
              <label className="tw-text-xs tw-text-cb-text-muted tw-uppercase tw-font-bold">
                Expires
              </label>
              <div className="tw-flex tw-items-center tw-gap-2">
                <Clock size={14} className="tw-text-cb-text-muted" />
                <span>{new Date(certificate.expires_at).toLocaleString()}</span>
              </div>
            </div>
            <div>
              <label className="tw-text-xs tw-text-cb-text-muted tw-uppercase tw-font-bold">
                Auto Renew
              </label>
              <div>{certificate.auto_renew ? 'Enabled' : 'Disabled'}</div>
            </div>
          </div>

          <div className="tw-mt-4 tw-pt-4 tw-border-t tw-border-cb-border/50">
            <button
              className="btn btn-sm tw-flex tw-items-center tw-gap-2"
              onClick={handleRenew}
              disabled={loading}
            >
              <RefreshCw size={14} className={loading ? 'tw-animate-spin' : ''} />
              Renew Now
            </button>
          </div>
        </div>

        {/* Certificate PEM Section */}
        <div>
          <div className="tw-flex tw-items-center tw-justify-between tw-mb-2">
            <h4 className="tw-text-sm tw-font-bold tw-flex tw-items-center tw-gap-2">
              <FileText size={16} /> Certificate (PEM)
            </h4>
            {fullCert?.cert_pem && (
              <button
                className="tw-text-cb-text-muted hover:tw-text-cb-primary tw-transition-colors"
                onClick={() => copyToClipboard(fullCert.cert_pem)}
                title="Copy PEM"
              >
                {copied ? <Check size={16} /> : <Copy size={16} />}
              </button>
            )}
          </div>
          <div className="tw-relative">
            <pre className="tw-bg-black/20 tw-p-3 tw-rounded tw-text-[11px] tw-font-mono tw-overflow-x-auto tw-max-h-60 tw-border tw-border-cb-border">
              {loading
                ? 'Loading PEM content...'
                : fullCert?.cert_pem || 'No PEM content available.'}
            </pre>
          </div>
        </div>

        {/* Info Box */}
        <div className="tw-p-3 tw-rounded tw-bg-cb-primary/10 tw-border tw-border-cb-primary/20 tw-text-sm">
          <p className="tw-m-0 tw-text-cb-text-muted">
            <strong>Note:</strong> Private keys are stored securely in the vault and are never
            displayed in the UI for security reasons.
          </p>
        </div>
      </div>
    </Drawer>
  );
}

CertificateDetail.propTypes = {
  certificate: PropTypes.object,
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onUpdate: PropTypes.func,
};

export default CertificateDetail;
