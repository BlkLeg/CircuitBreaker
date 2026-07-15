import React from 'react';
import PropTypes from 'prop-types';
import { DotLottieReact } from '@lottiefiles/dotlottie-react';

const PROGRESS_BAR_ANIMATION_URL = '/Progress%20Bar%20-%20Gradient.lottie';

const ANIMATION_STYLE = {
  width: '100%',
  height: '100%',
};

const CONTAINER_CLASS_NAME = 'scan-progress-animation';

export default function ScanProgressAnimation({ className = '' }) {
  const containerClassName = [CONTAINER_CLASS_NAME, className].filter(Boolean).join(' ');

  return (
    <div className={containerClassName} data-testid="scan-progress-animation" aria-hidden="true">
      <DotLottieReact src={PROGRESS_BAR_ANIMATION_URL} autoplay loop style={ANIMATION_STYLE} />
    </div>
  );
}

ScanProgressAnimation.propTypes = {
  className: PropTypes.string,
};
