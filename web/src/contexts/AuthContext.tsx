import React, { useState, useEffect, useCallback } from 'react';
import {
  AUTH_EXPIRED_EVENT,
  AuthContext,
  clearAuthSession,
  getStoredUser,
  isTokenValid,
  saveAuthSession,
  type User,
} from './auth-core';
import { getApiBaseUrl, httpClient } from '@/utils/api';

/**
 * Authentication Provider component.
 *
 * Manages user authentication state across the application using localStorage.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  /**
   * Check if the current token is valid (exists and not expired).
   */
  const checkTokenValidity = useCallback((): boolean => {
    return isTokenValid();
  }, []);

  /**
   * Force logout and dispatch event for the app to handle.
   */
  const forceLogout = useCallback(() => {
    clearAuthSession();
    setUser(null);
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
  }, []);

  /**
   * Initialize auth state from localStorage on mount.
   */
  useEffect(() => {
    const storedUser = getStoredUser();
    if (storedUser) {
      setUser(storedUser);
    } else {
      clearAuthSession();
    }
    setIsLoading(false);
  }, []);

  /**
   * Login with username and password.
   *
   * Stores the access token and user data in localStorage for persistence.
   */
  const login = useCallback(async (username: string, password: string) => {
    const response = await httpClient(`${getApiBaseUrl()}/auth/login`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ username, password }),
    });

    if (!response.ok) {
      const errorData = await response.json() as { detail?: string };
      throw new Error(errorData.detail || 'Login failed');
    }

    const data = await response.json() as { id: number; username: string; access_token: string };
    const loggedInUser: User = { id: data.id, username: data.username };
    saveAuthSession(loggedInUser, data.access_token);
    setUser(loggedInUser);
  }, []);

  /**
   * Logout by clearing stored auth state.
   */
  const logout = useCallback(() => {
    clearAuthSession();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, checkTokenValidity, forceLogout }}>
      {children}
    </AuthContext.Provider>
  );
}
