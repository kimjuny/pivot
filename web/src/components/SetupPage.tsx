import React, { useState, useEffect, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Info, Loader2 } from 'lucide-react';
import { useAuth, isTokenValid, saveAuthSession, type User } from '../contexts/auth-core';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import PasswordInput from '@/components/PasswordInput';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
import { getApiBaseUrl, httpClient } from '@/utils/api';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

/**
 * Detect the user's current IANA timezone via the Intl API.
 * Falls back to "UTC" when unavailable.
 */
function detectBrowserTimezone(): string {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return tz || 'UTC';
  } catch {
    return 'UTC';
  }
}

/**
 * First-time setup page for creating the initial admin account.
 *
 * Only accessible when no users exist in the database. After creating the
 * admin account the user is automatically signed in and redirected to the
 * main application.
 */
function SetupPage() {
  const navigate = useNavigate();
  const { needsSetup, setupCompleted } = useAuth();

  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [email, setEmail] = useState('');
  const [timeZone, setTimeZone] = useState(detectBrowserTimezone);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const timeZones = useMemo(
    () => {
      try {
        return Intl.supportedValuesOf('timeZone');
      } catch {
        return ['UTC'];
      }
    },
    [],
  );

  /** Redirect to login if setup is already completed. */
  useEffect(() => {
    if (needsSetup === false) {
      navigate('/', { replace: true });
    }
  }, [needsSetup, navigate]);

  /** Redirect to login if already authenticated. */
  useEffect(() => {
    if (isTokenValid()) {
      navigate('/app', { replace: true });
    }
  }, [navigate]);

  const clearError = () => {
    if (errorMessage) setErrorMessage('');
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage('');

    if (username.trim().length < 3 || username.trim().length > 20) {
      setErrorMessage('Username must be 3–20 characters.');
      return;
    }

    if (!/^[a-zA-Z0-9_]+$/.test(username.trim())) {
      setErrorMessage('Username can only contain letters, numbers, and underscores.');
      return;
    }

    if (password.length < 8) {
      setErrorMessage('Password must be at least 8 characters.');
      return;
    }

    if (password !== confirmPassword) {
      setErrorMessage('Passwords do not match.');
      return;
    }

    setIsLoading(true);
    void (async () => {
      try {
        const response = await httpClient(`${getApiBaseUrl()}/auth/setup`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            username: username.trim(),
            password,
            email: email.trim() || null,
            time_zone: timeZone,
            language: 'en-US',
          }),
        });

        if (!response.ok) {
          const errorData = await response.json() as { detail?: string };
          throw new Error(errorData.detail || 'Setup failed');
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
        setupCompleted(loggedInUser);
        navigate('/studio', { replace: true });
      } catch (error) {
        setErrorMessage(
          error instanceof Error ? error.message : 'Setup failed. Please try again.',
        );
      } finally {
        setIsLoading(false);
      }
    })();
  };

  return (
    <div
      className="flex min-h-screen flex-col items-center justify-center bg-background px-4"
      style={{
        backgroundImage:
          'radial-gradient(circle, oklch(var(--foreground) / 0.1) 1px, transparent 1px)',
        backgroundSize: '22px 22px',
      }}
    >
      <div className="w-full max-w-sm animate-fade-in">
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

        {/* Setup card */}
        <Card className="rounded-2xl border-border/50 shadow-2xl shadow-black/30">
          <CardHeader className="pb-4">
            <CardTitle className="text-base font-semibold">Welcome to Pivot</CardTitle>
            <CardDescription>
              Create your admin account to get started
            </CardDescription>
          </CardHeader>

          <CardContent>
            <TooltipProvider>
            <form onSubmit={handleSubmit} className="space-y-3" noValidate>
              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="username">Username <span className="text-destructive">*</span></Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      3–20 characters. Letters, numbers, and underscores only.
                    </TooltipContent>
                  </Tooltip>
                </div>
                <Input
                  id="username"
                  type="text"
                  placeholder="3–20 characters"
                  value={username}
                  onChange={(e) => { setUsername(e.target.value); clearError(); }}
                  autoComplete="username"
                  disabled={isLoading}
                  aria-invalid={!!errorMessage}
                  autoFocus
                />
              </div>

              <div className="space-y-1">
                <div className="flex items-center gap-1.5">
                  <Label htmlFor="password">Password <span className="text-destructive">*</span></Label>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      At least 8 characters.
                    </TooltipContent>
                  </Tooltip>
                </div>
                <PasswordInput
                  id="password"
                  value={password}
                  onChange={(e) => { setPassword(e.target.value); clearError(); }}
                  disabled={isLoading}
                  invalid={!!errorMessage}
                  autoComplete="new-password"
                />
              </div>

              <div className="space-y-1">
                <Label htmlFor="confirm-password">Confirm password <span className="text-destructive">*</span></Label>
                <PasswordInput
                  id="confirm-password"
                  value={confirmPassword}
                  onChange={(e) => { setConfirmPassword(e.target.value); clearError(); }}
                  disabled={isLoading}
                  invalid={!!errorMessage}
                  autoComplete="new-password"
                />
              </div>

              <div className="space-y-1">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="admin@example.com"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); clearError(); }}
                  autoComplete="email"
                  disabled={isLoading}
                />
              </div>

              <div className="space-y-1">
                <Label htmlFor="timezone">Timezone</Label>
                <select
                  id="timezone"
                  value={timeZone}
                  onChange={(e) => { setTimeZone(e.target.value); clearError(); }}
                  disabled={isLoading}
                  className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-xs transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {timeZones.map((tz) => (
                    <option key={tz} value={tz}>{tz}</option>
                  ))}
                </select>
              </div>

              {errorMessage && (
                <p role="alert" className="text-xs text-destructive">
                  {errorMessage}
                </p>
              )}

              <Button
                type="submit"
                disabled={isLoading}
                className="w-full"
                size="default"
              >
                {isLoading ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Creating account…
                  </>
                ) : (
                  'Create admin account'
                )}
              </Button>
            </form>
            </TooltipProvider>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default SetupPage;
