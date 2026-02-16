import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';

/** User data interface from authentication response */
export interface User {
  id: number;
  username: string;
}

/** Authentication context type */
interface AuthContextType {
  /** Current authenticated user, or null if not logged in */
  user: User | null;
  /** Whether authentication is currently being checked */
  isLoading: boolean;
  /** Login function with username and password */
  login: (username: string, password: string) => Promise<void>;
  /** Logout function to clear authentication state */
  logout: () => void;
  /** Check if current token is valid */
  checkTokenValidity: () => boolean;
  /** Force logout and redirect to login */
  forceLogout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'pivot_auth_token';
const USER_KEY = 'pivot_auth_user';

/** Event name for auth expiry events */
export const AUTH_EXPIRED_EVENT = 'pivot:auth-expired';

/**
 * Decode JWT token to extract payload.
 * Returns null if token is invalid or cannot be decoded.
 */
const decodeToken = (token: string): { exp?: number; sub?: string } | null => {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const payload = JSON.parse(atob(parts[1])) as { exp?: number; sub?: string };
    return payload;
  } catch {
    return null;
  }
};

/**
 * Check if a token is valid (not expired).
 * Returns true if token exists and hasn't expired.
 */
export const isTokenValid = (): boolean => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return false;

  const decoded = decodeToken(token);
  if (!decoded || !decoded.exp) return false;

  // Check with 60 second buffer
  const now = Math.floor(Date.now() / 1000);
  return decoded.exp > now + 60;
};

/**
 * Authentication Provider Component.
 * Manages user authentication state across the application using localStorage.
 *
 * On mount, retrieves stored auth state from localStorage to persist login across sessions.
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
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
    // Dispatch custom event for app-wide handling
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
  }, []);

  /**
   * Initialize auth state from localStorage on mount.
   * Validates token and clears invalid/expired tokens.
   */
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);

    if (storedToken && storedUser) {
      try {
        // Validate token before setting user
        const decoded = decodeToken(storedToken);
        if (decoded && decoded.exp) {
          const now = Math.floor(Date.now() / 1000);
          if (decoded.exp > now) {
            const parsedUser = JSON.parse(storedUser) as User;
            setUser(parsedUser);
          } else {
            // Token expired, clear storage
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(USER_KEY);
          }
        } else {
          // Invalid token, clear storage
          localStorage.removeItem(TOKEN_KEY);
          localStorage.removeItem(USER_KEY);
        }
      } catch {
        // Clear invalid stored data
        localStorage.removeItem(TOKEN_KEY);
        localStorage.removeItem(USER_KEY);
      }
    }
    setIsLoading(false);
  }, []);

  /**
   * Login with username and password.
   * Stores the access token and user data in localStorage for persistence.
   */
  const login = useCallback(async (username: string, password: string) => {
    const response = await fetch(`${import.meta.env.VITE_API_BASE_URL || 'http://localhost:8003/api'}/auth/login`, {
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

    // Store token and user data
    localStorage.setItem(TOKEN_KEY, data.access_token);
    localStorage.setItem(USER_KEY, JSON.stringify({ id: data.id, username: data.username }));
    setUser({ id: data.id, username: data.username });
  }, []);

  /**
   * Logout by clearing stored auth state.
   * Removes both token and user data from localStorage.
   */
  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, checkTokenValidity, forceLogout }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Hook to access authentication context.
 * Provides login, logout, and current user state.
 *
 * @throws Error if used outside of AuthProvider
 */
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

/**
 * Get the current auth token from localStorage.
 * Used by api.ts to include auth headers in requests.
 */
export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
