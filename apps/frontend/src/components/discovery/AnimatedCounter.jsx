import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { SCAN_COUNTER_ANIMATION_DURATION_MS } from '../../lib/constants.js';

export default function AnimatedCounter({
  value,
  duration = SCAN_COUNTER_ANIMATION_DURATION_MS,
  className = 'tabular-nums',
}) {
  const [displayed, setDisplayed] = useState(value);
  const frameRef = useRef(null);
  const startRef = useRef(null);
  const fromRef = useRef(value);
  const displayedRef = useRef(value);

  useEffect(() => {
    displayedRef.current = displayed;
  }, [displayed]);

  useEffect(() => {
    if (value === fromRef.current && value === displayedRef.current) {
      return undefined;
    }

    const from = displayedRef.current;
    const delta = value - from;

    const animate = (timestamp) => {
      if (startRef.current == null) startRef.current = timestamp;
      const elapsed = timestamp - startRef.current;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      const nextValue = Math.round(from + delta * eased);
      displayedRef.current = nextValue;
      setDisplayed(nextValue);

      if (progress < 1) {
        frameRef.current = requestAnimationFrame(animate);
      } else {
        fromRef.current = value;
        displayedRef.current = value;
        startRef.current = null;
      }
    };

    if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
    frameRef.current = requestAnimationFrame(animate);

    return () => {
      if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
      frameRef.current = null;
      startRef.current = null;
    };
  }, [value, duration]);

  return <span className={className}>{displayed > 0 ? displayed : '\u2014'}</span>;
}

AnimatedCounter.propTypes = {
  value: PropTypes.number.isRequired,
  duration: PropTypes.number,
  className: PropTypes.string,
};
