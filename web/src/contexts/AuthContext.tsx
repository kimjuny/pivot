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
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'pivot_auth_token';
const USER_KEY = 'pivot_auth_user';

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
   * Initialize auth state from localStorage on mount.
   * This ensures the user stays logged in across page refreshes.
   */
  useEffect(() => {
    const storedToken = localStorage.getItem(TOKEN_KEY);
    const storedUser = localStorage.getItem(USER_KEY);

    if (storedToken && storedUser) {
      try {
        const parsedUser = JSON.parse(storedUser) as User;
        setUser(parsedUser);
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
    <AuthContext.Provider value={{ user, isLoading, login, logout }}>
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
