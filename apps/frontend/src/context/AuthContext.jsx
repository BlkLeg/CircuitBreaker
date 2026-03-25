import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth.js';
import { activateMasqueradeInterceptor, deactivateMasqueradeInterceptor } from '../api/client.jsx';

export const AuthContext = createContext({
  isAuthenticated: false,
  authReady: false,
  user: null,
  token: null,
  isMasquerade: false,
  login: () => {},
  logout: () => {},
  endMasquerade: () => {},
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
  const [isMasquerade, setIsMasquerade] = useState(false);
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const pendingActionRef = useRef(null);
  const loginJustSucceededAtRef = useRef(0);
  const navigate = useNavigate();

  // Validate session on mount. If a masquerade token is in sessionStorage, activate
  // the Bearer-header interceptor and load the masqueraded user. Falls back to the
  // admin's own httpOnly cookie session if the masquerade token has expired.
  useEffect(() => {
    let cancelled = false;
    const masqToken = sessionStorage.getItem('cb_masquerade_token');

    if (masqToken) {
      activateMasqueradeInterceptor(masqToken);
      authApi
        .meWithToken(masqToken)
        .then((res) => {
          if (cancelled) return;
          setUser(res?.data || null);
          setToken('masquerade');
          setIsMasquerade(true);
        })
        .catch(() => {
          // Masquerade token expired — clear it and fall back to the admin cookie session
          if (cancelled) return;
          sessionStorage.removeItem('cb_masquerade_token');
          deactivateMasqueradeInterceptor();
          authApi
            .me()
            .then((res) => {
              if (cancelled) return;
              setUser(res?.data || null);
              setToken('cookie');
            })
            .catch(() => {
              if (cancelled) return;
              setUser(null);
              setToken(null);
            });
        })
        .finally(() => {
          if (!cancelled) setMeReady(true);
        });
    } else {
      authApi
        .me()
        .then((res) => {
          if (cancelled) return;
          setUser(res?.data || null);
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
    }

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
    authApi.logout().catch((err) => {
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

  const endMasquerade = useCallback(() => {
    sessionStorage.removeItem('cb_masquerade_token');
    deactivateMasqueradeInterceptor();
    window.location.reload();
  }, []);

  const value = {
    isAuthenticated: !!user,
    authReady: meReady,
    user,
    token,
    isMasquerade,
    login,
    logout,
    endMasquerade,
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
