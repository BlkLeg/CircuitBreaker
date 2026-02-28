import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';

const TOKEN_KEY = import.meta.env.VITE_TOKEN_STORAGE_KEY;

export const AuthContext = createContext({
  isAuthenticated: false,
  user: null,
  token: null,
  authEnabled: false,
  login: () => {},
  logout: () => {},
  setAuthEnabled: () => {},
  openAuthModal: () => {},
  openProfileModal: () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY));
  const [user, setUser] = useState(null);
  const [authEnabled, setAuthEnabled] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const pendingActionRef = useRef(null);
  const navigate = useNavigate();

  // F3-4: Sync authEnabled from backend on mount (before SettingsPage loads)
  useEffect(() => {
    fetch('/api/v1/settings')
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((s) => setAuthEnabled(s.auth_enabled ?? false))
      .catch(() => {});
  }, []);

  // Validate token on mount and whenever it changes
  useEffect(() => {
    if (!token) return;
    fetch('/api/v1/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((u) => setUser(u))
      .catch(() => {
        localStorage.removeItem(TOKEN_KEY);
        setToken(null);
        setUser(null);
      });
  }, [token]);

  const login = useCallback((newToken, newUser) => {
    localStorage.setItem(TOKEN_KEY, newToken);
    setToken(newToken);
    setUser(newUser);
    setAuthModalOpen(false);
    // Retry any pending action
    if (pendingActionRef.current) {
      pendingActionRef.current();
      pendingActionRef.current = null;
    }
  }, []);

  const logout = useCallback(() => {
    if (token) {
      fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      }).catch(() => {});
    }
    localStorage.removeItem(TOKEN_KEY);
    setToken(null);
    setUser(null);
    setProfileModalOpen(false);
    navigate('/login');
  }, [token, navigate]);

  const openAuthModal = useCallback((pendingAction) => {
    if (pendingAction) pendingActionRef.current = pendingAction;
    setAuthModalOpen(true);
  }, []);

  const openProfileModal = useCallback(() => {
    setProfileModalOpen(true);
  }, []);

  const value = {
    isAuthenticated: !!user,
    user,
    token,
    authEnabled,
    setAuthEnabled,
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
