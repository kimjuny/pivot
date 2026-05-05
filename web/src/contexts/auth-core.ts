import { createContext, useContext } from 'react';

/** User data interface from authentication response. */
export interface User {
  id: number;
  username: string;
  role: string;
  permissions: string[];
}

/** Authentication context type. */
export interface AuthContextType {
  /** Current authenticated user, or null if not logged in. */
  user: User | null;
  /** Whether authentication is currently being checked. */
  isLoading: boolean;
  /** Login function with username and password. */
  login: (username: string, password: string) => Promise<void>;
  /** Logout function to clear authentication state. */
  logout: () => void;
  /** Check if current token is valid. */
  checkTokenValidity: () => boolean;
  /** Force logout and redirect to login. */
  forceLogout: () => void;
}

export const AuthContext = createContext<AuthContextType | undefined>(undefined);

const TOKEN_KEY = 'pivot_auth_token';
const USER_KEY = 'pivot_auth_user';

/** Event name for auth expiry events. */
export const AUTH_EXPIRED_EVENT = 'pivot:auth-expired';

/**
 * Decode a JWT payload segment from base64url into UTF-8 text.
 *
 * Why: JWT uses base64url encoding without padding, while `atob()` expects
 * standard base64 input. Normalizing here keeps auth checks reliable across
 * browsers and token shapes.
 */
function decodeBase64Url(segment: string): string {
  const normalized = segment.replace(/-/g, '+').replace(/_/g, '/');
  const paddingLength = (4 - (normalized.length % 4)) % 4;
  const padded = normalized.padEnd(normalized.length + paddingLength, '=');
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
  return new TextDecoder().decode(bytes);
}

/**
 * Decode JWT token to extract payload.
 *
 * Returns null if token is invalid or cannot be decoded.
 */
function decodeToken(token: string): { exp?: number; sub?: string } | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    return JSON.parse(decodeBase64Url(parts[1])) as { exp?: number; sub?: string };
  } catch {
    return null;
  }
}

/**
 * Check if a token is valid (not expired).
 *
 * Returns true if token exists and has not expired.
 */
export function isTokenValid(): boolean {
  const token = localStorage.getItem(TOKEN_KEY);
  if (!token) return false;

  const decoded = decodeToken(token);
  if (!decoded || !decoded.exp) return false;

  const now = Math.floor(Date.now() / 1000);
  return decoded.exp > now + 60;
}

/**
 * Get the current auth token from localStorage.
 *
 * Used by API helpers to include auth headers in requests.
 */
export function getAuthToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/**
 * Persist authenticated user session to localStorage.
 */
export function saveAuthSession(user: User, token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

/**
 * Clear authenticated user session from localStorage.
 */
export function clearAuthSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
}

/**
 * Read persisted user from localStorage if token is valid.
 */
export function getStoredUser(): User | null {
  const storedToken = localStorage.getItem(TOKEN_KEY);
  const storedUser = localStorage.getItem(USER_KEY);
  if (!storedToken || !storedUser) return null;

  const decoded = decodeToken(storedToken);
  if (!decoded || !decoded.exp) return null;

  const now = Math.floor(Date.now() / 1000);
  if (decoded.exp <= now) return null;

  try {
    return JSON.parse(storedUser) as User;
  } catch {
    return null;
  }
}

/**
 * Return whether a user has one effective backend permission.
 */
export function hasPermission(user: User | null | undefined, permission: string): boolean {
  return user?.permissions?.includes(permission) ?? false;
}

/**
 * Hook to access authentication context.
 *
 * @throws Error if used outside of AuthProvider
 */
export function useAuth(): AuthContextType {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
