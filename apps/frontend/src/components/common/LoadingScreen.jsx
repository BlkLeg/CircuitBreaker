import React, { useEffect, useState } from 'react';
import Lottie from 'lottie-react';

const LOADING_ANIMATION_PATH = '/loading.json';
const LOADING_ANIMATION_SIZE = 240;
const LOADING_LABEL = 'Loading…';

export default function LoadingScreen() {
  const [animationData, setAnimationData] = useState(null);

  useEffect(() => {
    let isMounted = true;

    fetch(LOADING_ANIMATION_PATH)
      .then((response) => {
        if (!response.ok) {
          throw new Error(`Failed to load animation: ${response.status}`);
        }
        return response.json();
      })
      .then((data) => {
        if (isMounted) {
          setAnimationData(data);
        }
      })
      .catch((error) => {
        console.warn('[LoadingScreen] Unable to load loading animation.', error);
      });

    return () => {
      isMounted = false;
    };
  }, []);

  return (
    <div className="login-root" role="status" aria-live="polite" aria-label={LOADING_LABEL}>
      {animationData ? (
        <Lottie
          animationData={animationData}
          loop
          autoplay
          style={{ width: LOADING_ANIMATION_SIZE, height: LOADING_ANIMATION_SIZE }}
        />
      ) : (
        <div className="login-card" aria-hidden>
          {LOADING_LABEL}
        </div>
      )}
    </div>
  );
}
