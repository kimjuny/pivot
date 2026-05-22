import React, { useState } from 'react';
import { Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { useNavigate } from 'react-router-dom';

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Field, FieldLabel, FieldError } from '@/components/ui/field';
import PasswordInput from '@/components/PasswordInput';
import { apiRequest } from '@/utils/api';
import { useAuth } from '@/contexts/auth-core';

/** Dialog for an authenticated user to change their own password. */
function ChangePasswordDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  const resetForm = () => {
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setFormErrors({});
    setIsLoading(false);
  };

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (!currentPassword) errors['current'] = 'Current password is required';
    if (!newPassword) errors['new'] = 'New password is required';
    else if (newPassword.length < 8) errors['new'] = 'Must be at least 8 characters';
    if (!confirmPassword) errors['confirm'] = 'Please confirm your new password';
    else if (confirmPassword !== newPassword) errors['confirm'] = 'Passwords do not match';
    if (currentPassword && newPassword && currentPassword === newPassword) {
      errors['new'] = 'Must be different from current password';
    }
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    setIsLoading(true);
    try {
      await apiRequest('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });
      toast.success('Password changed successfully');
      resetForm();
      onOpenChange(false);
      logout();
      navigate('/', { replace: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to change password';
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) resetForm(); onOpenChange(v); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Change password</DialogTitle>
          <DialogDescription>
            Enter your current password and choose a new one.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => { void handleSubmit(e); }} className="grid gap-4 py-2">
          <Field data-invalid={!!formErrors['current']}>
            <FieldLabel htmlFor="change-current-password">Current password</FieldLabel>
            <PasswordInput
              id="change-current-password"
              value={currentPassword}
              onChange={(e) => { setCurrentPassword(e.target.value); setFormErrors((p) => { const n = { ...p }; delete n['current']; return n; }); }}
              disabled={isLoading}
              invalid={!!formErrors['current']}
              autoComplete="current-password"
            />
            {formErrors['current'] && <FieldError>{formErrors['current']}</FieldError>}
          </Field>

          <Field data-invalid={!!formErrors['new']}>
            <FieldLabel htmlFor="change-new-password">New password</FieldLabel>
            <PasswordInput
              id="change-new-password"
              value={newPassword}
              onChange={(e) => { setNewPassword(e.target.value); setFormErrors((p) => { const n = { ...p }; delete n['new']; return n; }); }}
              disabled={isLoading}
              invalid={!!formErrors['new']}
              autoComplete="new-password"
            />
            {formErrors['new'] && <FieldError>{formErrors['new']}</FieldError>}
          </Field>

          <Field data-invalid={!!formErrors['confirm']}>
            <FieldLabel htmlFor="change-confirm-password">Confirm new password</FieldLabel>
            <PasswordInput
              id="change-confirm-password"
              value={confirmPassword}
              onChange={(e) => { setConfirmPassword(e.target.value); setFormErrors((p) => { const n = { ...p }; delete n['confirm']; return n; }); }}
              disabled={isLoading}
              invalid={!!formErrors['confirm']}
              autoComplete="new-password"
            />
            {formErrors['confirm'] && <FieldError>{formErrors['confirm']}</FieldError>}
          </Field>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => { resetForm(); onOpenChange(false); }} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Change password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default ChangePasswordDialog;
