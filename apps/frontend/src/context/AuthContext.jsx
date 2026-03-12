import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';

export const AuthContext = createContext({
  isAuthenticated: false,
  authReady: false,
  user: null,
  token: null,
  login: () => {},
  logout: () => {},
  openAuthModal: () => {},
  openProfileModal: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(null);
  const [user, setUser] = useState(null);
  const [meReady, setMeReady] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const pendingActionRef = useRef(null);
  const loginJustSucceededAtRef = useRef(0);
  const navigate = useNavigate();

  // Validate session on mount via cookie (httpOnly); sets meReady when done
  useEffect(() => {
    let cancelled = false;
    fetch('/api/v1/auth/me', { credentials: 'include' })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((u) => {
        if (cancelled) return;
        setUser(u);
        setToken('cookie');
      })
      .catch(() => {
        if (cancelled) return;
        setUser(null);
        setToken(null);
      })
      .finally(() => {
        if (!cancelled) setMeReady(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Handle session expiry signalled by the axios interceptor (401 on any request)
  useEffect(() => {
    const handler = () => {
      setToken(null);
      setUser(null);
      setAuthModalOpen(true);
    };
    window.addEventListener('cb:session-expired', handler);
    return () => window.removeEventListener('cb:session-expired', handler);
  }, []);

  const login = useCallback((newToken, newUser) => {
    if (!newUser) return;
    loginJustSucceededAtRef.current = Date.now();
    setToken(newToken ?? 'cookie');
    setUser(newUser);
    setAuthModalOpen(false);
    if (pendingActionRef.current) {
      pendingActionRef.current();
      pendingActionRef.current = null;
    }
  }, []);

  const logout = useCallback(() => {
    fetch('/api/v1/auth/logout', { method: 'POST', credentials: 'include' }).catch((err) => {
      console.warn('Server-side logout failed (session will expire):', err);
    });
    setToken(null);
    setUser(null);
    setProfileModalOpen(false);
    navigate('/login');
  }, [navigate]);

  const openAuthModal = useCallback((pendingAction) => {
    if (pendingAction) pendingActionRef.current = pendingAction;
    setAuthModalOpen(true);
  }, []);

  const openProfileModal = useCallback(() => {
    setProfileModalOpen(true);
  }, []);

  const value = {
    isAuthenticated: !!user,
    authReady: meReady,
    user,
    token,
    login,
    logout,
    openAuthModal,
    openProfileModal,
    authModalOpen,
    setAuthModalOpen,
    profileModalOpen,
    setProfileModalOpen,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

AuthProvider.propTypes = {
  children: PropTypes.node.isRequired,
};
