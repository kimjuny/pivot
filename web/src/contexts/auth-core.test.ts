import { beforeEach, describe, expect, it } from 'vitest';

import {
  clearAuthSession,
  getStoredUser,
  isTokenValid,
  saveAuthSession,
} from './auth-core';

/**
 * Build a lightweight unsigned JWT for frontend auth state tests.
 *
 * Why: the client only decodes the payload to validate expiry; it does not
 * verify the signature locally.
 */
function buildToken(payload: Record<string, unknown>): string {
  const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
  const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
  return `${header}.${body}.signature`;
}

describe('auth-core', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('accepts base64url-encoded JWT payloads without padding', () => {
    const token = buildToken({
      sub: '1',
      exp: Math.floor(Date.now() / 1000) + 3600,
      nickname: 'Test/User+One',
    });

    saveAuthSession({ id: 1, username: 'default' }, token);

    expect(isTokenValid()).toBe(true);
    expect(getStoredUser()).toEqual({ id: 1, username: 'default' });
  });

  it('clears invalid sessions cleanly', () => {
    saveAuthSession({ id: 1, username: 'default' }, 'invalid.token.value');

    expect(isTokenValid()).toBe(false);
    expect(getStoredUser()).toBeNull();

    clearAuthSession();
    expect(localStorage.getItem('pivot_auth_token')).toBeNull();
  });
});
