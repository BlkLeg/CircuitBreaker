import { useState, useEffect } from 'react';

/**
 * Hook to detect if the current viewport is mobile-sized (< 768px).
 * @returns {boolean} True if mobile, false otherwise.
 */
export function useIsMobile() {
  const [isMobile, setIsMobile] = useState(window.innerWidth < 768);

  useEffect(() => {
    const handleResize = () => {
      setIsMobile(window.innerWidth < 768);
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  return isMobile;
}
