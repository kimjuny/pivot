import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth, isTokenValid, hasPermission, getStoredUser } from '../contexts/auth-core';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import PasswordInput from '@/components/PasswordInput';
import LightRays from '@/components/backgrounds/LightRays';
import BorderGlow from '@/components/backgrounds/BorderGlow';
import {
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { useReducedMotion } from '@/hooks/use-reduced-motion';

/**
 * Returns the post-login destination in priority order:
 * 1. The page the user was trying to reach before being sent to login.
 * 2. /app if the user has client access.
 * 3. /studio for studio-only accounts.
 *
 * The `from` value is sanitised to guard against open-redirect attacks.
 */
function resolvePostLoginDestination(from: string | undefined): string {
  if (from && from.startsWith('/') && !from.startsWith('//') && from !== '/') {
    return from;
  }
  const loggedInUser = getStoredUser();
  if (loggedInUser && hasPermission(loggedInUser, 'client.access')) {
    return '/app';
  }
  return '/studio';
}

/**
 * Full-page login form.
 *
 * After a successful login the user is sent back to their original destination
 * (carried in router state), or to the appropriate default surface based on
 * their permissions.
 */
function LoginPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login, user, needsSetup } = useAuth();
  const from = (location.state as { from?: string } | null)?.from;

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');
  const reducedMotion = useReducedMotion();

  /** Redirect already-authenticated users away from the login page. */
  useEffect(() => {
    if (user && isTokenValid()) {
      navigate(resolvePostLoginDestination(from), { replace: true });
    }
  }, [user, navigate, from]);

  /** Redirect to setup when no admin has been created yet. */
  useEffect(() => {
    if (needsSetup === true) {
      navigate('/setup', { replace: true });
    }
  }, [needsSetup, navigate]);

  const clearError = () => {
    if (errorMessage) setErrorMessage('');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage('');

    if (!username.trim() || !password.trim()) {
      setErrorMessage('Please enter both username and password.');
      return;
    }

    setIsLoading(true);
    void (async () => {
      try {
        await login(username, password);
        // getStoredUser() is populated synchronously by saveAuthSession inside
        // login(), so resolvePostLoginDestination can read permissions here
        // before the React state update fires.
        navigate(resolvePostLoginDestination(from), { replace: true });
      } catch (error) {
        setErrorMessage(
          error instanceof Error ? error.message : 'Incorrect username or password.',
        );
      } finally {
        setIsLoading(false);
      }
    })();
  };

  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden bg-background px-4">
      {!reducedMotion && (
        <div className="pointer-events-none fixed inset-0 z-0">
          <LightRays
            raysOrigin="top-center"
            raysColor="#e8e0ff"
            raysSpeed={0.5}
            lightSpread={1.2}
            rayLength={2.2}
            fadeDistance={1.2}
            saturation={0.9}
            mouseInfluence={0.15}
            className="opacity-60 dark:opacity-90"
          />
        </div>
      )}
      <div className="relative z-10 w-full max-w-sm animate-fade-in">
        {/* Brand wordmark */}
        <div className="mb-7 flex items-center justify-center gap-3 select-none">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary">
            <svg
              viewBox="0 0 16 16"
              className="h-5 w-5 text-primary-foreground"
              fill="currentColor"
              aria-hidden="true"
            >
              <polygon points="8,1 15,8 8,15 1,8" />
            </svg>
          </div>
          <span className="text-xl font-semibold tracking-tight text-foreground">Pivot</span>
        </div>

        {/* Login card */}
        <BorderGlow borderRadius={20} animated={!reducedMotion}>
          <CardHeader className="pb-4">
            <CardTitle className="text-base font-semibold">Sign in</CardTitle>
            <CardDescription>Enter your credentials to continue</CardDescription>
          </CardHeader>

          <CardContent>
            <form onSubmit={handleSubmit} className="space-y-4" noValidate>
              <div className="space-y-1.5">
                <Label htmlFor="username">Username</Label>
                <Input
                  id="username"
                  type="text"
                  placeholder="Username"
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); clearError(); }}
                  autoComplete="username"
                  disabled={isLoading}
                  aria-invalid={!!errorMessage}
                  autoFocus
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <PasswordInput
                  id="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); clearError(); }}
                  disabled={isLoading}
                  invalid={!!errorMessage}
                />
                {errorMessage && (
                  <p role="alert" className="text-xs text-destructive">
                    {errorMessage}
                  </p>
                )}
              </div>

              <Button
                type="submit"
                disabled={isLoading}
                className="w-full"
                size="default"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Signing in…
                  </>
                ) : (
                  'Sign in'
                )}
              </Button>
            </form>
          </CardContent>
        </BorderGlow>

        {/* Demo credentials hint */}
      </div>
    </div>
  );
}

export default LoginPage;
