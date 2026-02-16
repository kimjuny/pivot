import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { LogIn, Eye, EyeOff } from 'lucide-react';
import { useAuth, isTokenValid } from '../contexts/AuthContext';
import Navigation from './Navigation';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldError } from '@/components/ui/field';

/**
 * Password input with show/hide toggle button.
 */
function PasswordInput({
  value,
  onChange,
  disabled,
  placeholder,
  id,
  invalid,
}: {
  value: string;
  onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  disabled?: boolean;
  placeholder?: string;
  id?: string;
  invalid?: boolean;
}) {
  const [showPassword, setShowPassword] = useState(false);

  return (
    <div className="relative">
      <Input
        id={id}
        type={showPassword ? 'text' : 'password'}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        autoComplete="current-password"
        disabled={disabled}
        aria-invalid={invalid}
        className="bg-background pr-9"
      />
      <button
        type="button"
        onClick={() => setShowPassword(!showPassword)}
        className="absolute right-0 top-0 h-full px-3 text-muted-foreground hover:text-foreground transition-colors z-10"
        tabIndex={-1}
        aria-label={showPassword ? 'Hide password' : 'Show password'}
      >
        {showPassword ? (
          <EyeOff className="w-4 h-4" />
        ) : (
          <Eye className="w-4 h-4" />
        )}
      </button>
    </div>
  );
}

/**
 * Login page component.
 * Full-page login form that serves as the entry point for unauthenticated users.
 * Automatically redirects to /agents if user is already logged in.
 */
function LoginPage() {
  const navigate = useNavigate();
  const { login, user } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  /**
   * Redirect to /agents if already logged in.
   */
  useEffect(() => {
    if (user && isTokenValid()) {
      navigate('/agents', { replace: true });
    }
  }, [user, navigate]);

  /**
   * Handle form submission.
   * Validates input and attempts login.
   */
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    // Clear previous errors
    setErrorMessage('');

    if (!username.trim() || !password.trim()) {
      setErrorMessage('Please enter both username and password');
      return;
    }

    setIsLoading(true);
    void (async () => {
      try {
        await login(username, password);
        // Navigate to agents page after successful login
        navigate('/agents', { replace: true });
      } catch (error) {
        setErrorMessage(error instanceof Error ? error.message : 'Incorrect username or password');
      } finally {
        setIsLoading(false);
      }
    })();
  };

  // Clear error when user starts typing
  const handleUsernameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUsername(e.target.value);
    if (errorMessage) setErrorMessage('');
  };

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPassword(e.target.value);
    if (errorMessage) setErrorMessage('');
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <Navigation />
      <div className="flex items-center justify-center p-4" style={{ minHeight: 'calc(100vh - 48px)' }}>
        <div className="w-full max-w-md">
          {/* Logo and title */}
          <div className="text-center mb-8">
            <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 mb-4">
              <LogIn className="w-8 h-8 text-primary" />
            </div>
            <h1 className="text-2xl font-semibold text-foreground">Welcome to Pivot</h1>
            <p className="text-muted-foreground mt-2">
              Sign in to access your agents and workflows
            </p>
          </div>

          {/* Login form card */}
          <div className="bg-card border border-border rounded-xl p-6 shadow-sm">
            <form onSubmit={handleSubmit} className="space-y-4">
              <Field data-invalid={!!errorMessage}>
                <FieldLabel htmlFor="username">Username</FieldLabel>
                <Input
                  id="username"
                  type="text"
                  placeholder="Enter your username"
                  value={username}
                  onChange={handleUsernameChange}
                  autoComplete="username"
                  disabled={isLoading}
                  aria-invalid={!!errorMessage}
                  className="bg-background"
                  autoFocus
                />
              </Field>

              <Field data-invalid={!!errorMessage}>
                <FieldLabel htmlFor="password">Password</FieldLabel>
                <PasswordInput
                  id="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={handlePasswordChange}
                  disabled={isLoading}
                  invalid={!!errorMessage}
                />
                {errorMessage && <FieldError>{errorMessage}</FieldError>}
              </Field>

              <Button
                type="submit"
                disabled={isLoading}
                className="w-full btn-accent"
                size="lg"
              >
                {isLoading ? 'Signing in...' : 'Sign in'}
              </Button>
            </form>
          </div>

          {/* Demo credentials hint */}
          <p className="text-center text-xs text-muted-foreground mt-6">
            Demo credentials: username <code className="bg-muted px-1 rounded">default</code> password <code className="bg-muted px-1 rounded">123456</code>
          </p>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
