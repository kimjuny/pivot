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
 * Also checks whether the system needs initial admin setup on mount.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState<boolean | null>(null);

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
   * Initialize auth state from localStorage and check setup status on mount.
   */
  useEffect(() => {
    const storedUser = getStoredUser();
    if (storedUser) {
      setUser(storedUser);
    } else {
      clearAuthSession();
    }

    void (async () => {
      try {
        const response = await httpClient(`${getApiBaseUrl()}/auth/setup-status`);
        if (response.ok) {
          const data = await response.json() as { needs_setup: boolean };
          setNeedsSetup(data.needs_setup);
        }
      } catch {
        // Silently ignore — setup check is best-effort
      }
      setIsLoading(false);
    })();
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

    const data = await response.json() as {
      id: number;
      username: string;
      role: string;
      permissions: string[];
      access_token: string;
    };
    const loggedInUser: User = {
      id: data.id,
      username: data.username,
      role: data.role,
      permissions: data.permissions,
    };
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

  /**
   * Mark the initial setup as completed.
   */
  const setupCompleted = useCallback(() => {
    setNeedsSetup(false);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, needsSetup, login, logout, checkTokenValidity, forceLogout, setupCompleted }}>
      {children}
    </AuthContext.Provider>
  );
}
