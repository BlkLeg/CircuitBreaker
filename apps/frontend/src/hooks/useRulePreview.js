import { useEffect, useRef, useState } from 'react';
import { metricAlertsApi } from '../api/client';
import { validateRule } from '../lib/metricAlerts';

const DEBOUNCE_MS = 600;

/**
 * Preview what a prospective rule would conclude from stored samples.
 *
 * Three guards keep it from lying:
 *   - a request token, so a response for values the operator has since changed
 *     can never render (the same guard VulnerabilityPanel uses);
 *   - no request for a rule that already fails client validation, because the
 *     server would only refuse it — and the previous result is retracted rather
 *     than left standing beside values that no longer produce it;
 *   - no request at all when the viewer cannot preview — /preview is admin-only
 *     and a 403 is not a result worth rendering.
 */
export function useRulePreview(rule, { catalog, canPreview, windowSeconds = 3600 }) {
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState(null);
  const token = useRef(0);
  const serialized = JSON.stringify(rule);

  useEffect(() => {
    // A preview belongs to the values that produced it. When the form stops
    // holding a previewable rule, the result already on screen is retracted and
    // any in-flight response is orphaned by bumping the token — otherwise the
    // panel keeps reporting "Normal" beside a threshold the operator just
    // cleared. The token guards a late answer; this guards the stale one.
    if (!canPreview || Object.keys(validateRule(rule, catalog)).length > 0) {
      token.current += 1;
      setPreview(null);
      setPreviewing(false);
      setPreviewError(null);
      return undefined;
    }

    const current = token.current + 1;
    token.current = current;
    const timer = setTimeout(async () => {
      setPreviewing(true);
      setPreviewError(null);
      try {
        const response = await metricAlertsApi.preview(rule, windowSeconds);
        if (token.current !== current) return;
        setPreview(response.data);
      } catch (err) {
        if (token.current !== current) return;
        setPreviewError(err?.userMessage || 'The preview could not be run.');
      } finally {
        if (token.current === current) setPreviewing(false);
      }
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
    // `serialized` is the dependency that actually changes; `rule` is a new
    // object on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialized, canPreview, windowSeconds, catalog]);

  return { preview, previewing, previewError };
}

export default useRulePreview;
