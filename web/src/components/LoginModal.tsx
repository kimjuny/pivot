import React, { useState } from 'react';
import { LogIn, Eye, EyeOff } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Field, FieldLabel, FieldError } from '@/components/ui/field';
import { toast } from 'sonner';

interface LoginModalProps {
  /** Whether the modal is currently open */
  open: boolean;
  /** Callback when modal is closed (without logging in) */
  onOpenChange: (open: boolean) => void;
}

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
 * Login modal component.
 * Provides a clean, simple login form matching the project's design language.
 * Uses inline field errors for validation feedback.
 */
function LoginModal({ open, onOpenChange }: LoginModalProps) {
  const { login } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  /**
   * Handle form submission.
   * Validates input and attempts login, showing inline errors.
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
        toast.success('Login successful');
        onOpenChange(false);
        // Reset form after successful login
        setUsername('');
        setPassword('');
        setErrorMessage('');
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[400px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center">
                <LogIn className="w-4 h-4 text-primary" />
              </div>
              Welcome to Pivot
            </DialogTitle>
            <DialogDescription>
              Sign in to access your agents and workflows
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
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
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="ghost"
              onClick={() => {
                onOpenChange(false);
                setErrorMessage('');
              }}
              disabled={isLoading}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading} className="btn-accent">
              {isLoading ? 'Signing in...' : 'Sign in'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default LoginModal;
