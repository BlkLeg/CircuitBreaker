import React, { createContext, useContext, useMemo } from 'react';
import PropTypes from 'prop-types';
import { useConnectionState } from '../hooks/useConnectionState';

const DEFAULT_VALUE = {
  isConnecting: false,
  onConnectStart: () => {},
  onConnectEnd: () => {},
};

const ConnectionStateContext = createContext(DEFAULT_VALUE);

export function ConnectionStateProvider({ children }) {
  const { isConnecting, onConnectStart, onConnectEnd } = useConnectionState();
  const value = useMemo(
    () => ({ isConnecting, onConnectStart, onConnectEnd }),
    [isConnecting, onConnectStart, onConnectEnd]
  );
  return (
    <ConnectionStateContext.Provider value={value}>{children}</ConnectionStateContext.Provider>
  );
}

ConnectionStateProvider.propTypes = {
  children: PropTypes.node.isRequired,
};

export function useConnectionStateContext() {
  return useContext(ConnectionStateContext);
}
