import { useCallback, useState } from 'react';

export function useConnectionState() {
  const [isConnecting, setIsConnecting] = useState(false);

  const onConnectStart = useCallback(() => {
    setIsConnecting(true);
  }, []);

  const onConnectEnd = useCallback(() => {
    setIsConnecting(false);
  }, []);

  return { isConnecting, onConnectStart, onConnectEnd };
}
