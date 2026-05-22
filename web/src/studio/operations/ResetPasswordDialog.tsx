import { useState } from "react";
import { Loader2 } from "lucide-react";
import { toast } from "sonner";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Field, FieldLabel, FieldError } from "@/components/ui/field";
import PasswordInput from "@/components/PasswordInput";
import { resetOperationsUserPassword } from "@/studio/operations/api";

/** Dialog for an admin to reset another user's password. */
function ResetPasswordDialog({
  user,
  open,
  onOpenChange,
}: {
  user: { id: number; username: string } | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});

  const resetForm = () => {
    setNewPassword("");
    setConfirmPassword("");
    setFormErrors({});
    setIsLoading(false);
  };

  const validate = (): boolean => {
    const errors: Record<string, string> = {};
    if (!newPassword) errors["new"] = "New password is required";
    else if (newPassword.length < 8) errors["new"] = "Must be at least 8 characters";
    if (!confirmPassword) errors["confirm"] = "Please confirm the new password";
    else if (confirmPassword !== newPassword) errors["confirm"] = "Passwords do not match";
    setFormErrors(errors);
    return Object.keys(errors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate() || !user) return;

    setIsLoading(true);
    try {
      await resetOperationsUserPassword(user.id, { new_password: newPassword });
      toast.success(`Password reset for ${user.username}`);
      resetForm();
      onOpenChange(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reset password";
      toast.error(message);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) resetForm(); onOpenChange(v); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reset password</DialogTitle>
          <DialogDescription>
            Set a new password for <span className="font-medium">{user?.username}</span>.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={(e) => { void handleSubmit(e); }} className="grid gap-4 py-2">
          <Field data-invalid={!!formErrors["new"]}>
            <FieldLabel htmlFor="reset-new-password">New password</FieldLabel>
            <PasswordInput
              id="reset-new-password"
              value={newPassword}
              onChange={(e) => { setNewPassword(e.target.value); setFormErrors((p) => { const n = { ...p }; delete n["new"]; return n; }); }}
              disabled={isLoading}
              invalid={!!formErrors["new"]}
              autoComplete="new-password"
            />
            {formErrors["new"] && <FieldError>{formErrors["new"]}</FieldError>}
          </Field>

          <Field data-invalid={!!formErrors["confirm"]}>
            <FieldLabel htmlFor="reset-confirm-password">Confirm new password</FieldLabel>
            <PasswordInput
              id="reset-confirm-password"
              value={confirmPassword}
              onChange={(e) => { setConfirmPassword(e.target.value); setFormErrors((p) => { const n = { ...p }; delete n["confirm"]; return n; }); }}
              disabled={isLoading}
              invalid={!!formErrors["confirm"]}
              autoComplete="new-password"
            />
            {formErrors["confirm"] && <FieldError>{formErrors["confirm"]}</FieldError>}
          </Field>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => { resetForm(); onOpenChange(false); }} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
              Reset password
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export default ResetPasswordDialog;
