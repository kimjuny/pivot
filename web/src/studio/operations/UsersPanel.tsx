import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { toast } from "sonner";

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldError, FieldLabel } from "@/components/ui/field";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
} from "@/components/ui/input-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatTimestamp } from "@/utils/timestamp";
import {
  createOperationsUser,
  listOperationsRoles,
  listOperationsUsers,
  updateOperationsUser,
  type OperationsRole,
  type OperationsUser,
} from "@/studio/operations/api";
import { CirclePause, CirclePlay, KeyRound, Mail, Pencil, User, Users } from "lucide-react";

const EMPTY_USER_FORM = {
  username: "",
  password: "",
  roleId: "",
  email: "",
};

export interface PanelHandle {
  triggerCreate: () => void;
}

/** Panel for managing user accounts with create/edit dialog. */
const UsersPanel = forwardRef<PanelHandle>(function UsersPanel(_props, ref) {
  const [users, setUsers] = useState<OperationsUser[]>([]);
  const [roles, setRoles] = useState<OperationsRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<OperationsUser | null>(null);
  const [form, setForm] = useState(EMPTY_USER_FORM);
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  const isEditing = editingUser !== null;

  const roleOptions = useMemo(
    () => roles.map((role) => ({ id: role.id, key: role.key, name: role.name })),
    [roles],
  );

  const roleNameById = useMemo(() => {
    const map = new Map<number, string>();
    for (const role of roles) {
      if (role.id != null) map.set(role.id, role.name);
    }
    return map;
  }, [roles]);

  useImperativeHandle(ref, () => ({
    triggerCreate: () => openCreate(),
  }));

  function openCreate() {
    setEditingUser(null);
    setForm({
      ...EMPTY_USER_FORM,
      roleId: String(roles.find((r) => r.key === "user")?.id ?? roles[0]?.id ?? ""),
    });
    setFormErrors({});
    setDialogOpen(true);
  }

  function openEdit(user: OperationsUser) {
    setEditingUser(user);
    setForm({
      username: user.username,
      password: "",
      roleId: String(user.role_id),
      email: user.email ?? "",
    });
    setFormErrors({});
    setDialogOpen(true);
  }

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [nextUsers, nextRoles] = await Promise.all([
        listOperationsUsers(),
        listOperationsRoles(),
      ]);
      setUsers(nextUsers);
      setRoles(nextRoles);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function validateForm(): Record<string, string> {
    const errors: Record<string, string> = {};
    if (!isEditing && !form.username.trim()) errors.username = "Username is required";
    if (!isEditing && !form.password) errors.password = "Password is required";
    if (!form.roleId) errors.roleId = "Role is required";
    return errors;
  }

  async function toggleStatus(user: OperationsUser) {
    const next = user.status === "active" ? "disabled" : "active";
    try {
      const updated = await updateOperationsUser(user.id, { status: next });
      setUsers((current) =>
        current.map((u) => (u.id === updated.id ? updated : u)),
      );
      toast.success(`User ${next === "active" ? "enabled" : "disabled"}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update user");
    }
  }

  async function handleSubmit() {
    const errors = validateForm();
    if (Object.keys(errors).length > 0) {
      setFormErrors(errors);
      return;
    }
    setSaving(true);
    try {
      if (isEditing) {
        const updated = await updateOperationsUser(editingUser.id, {
          role_id: Number(form.roleId),
          email: form.email.trim() || null,
        });
        setUsers((current) =>
          current.map((u) => (u.id === updated.id ? updated : u)),
        );
        toast.success("User updated");
      } else {
        const created = await createOperationsUser({
          username: form.username.trim(),
          password: form.password,
          role_id: Number(form.roleId),
          email: form.email.trim() || null,
        });
        setUsers((current) => [created, ...current]);
        toast.success("User created");
      }
      setDialogOpen(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save user");
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      {error && (
        <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="rounded-md border">
        <Table className="table-fixed" containerClassName="overflow-hidden">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[60px]">ID</TableHead>
              <TableHead className="w-[25%]">User</TableHead>
              <TableHead className="w-[18%]">Role</TableHead>
              <TableHead className="w-[12%]">Status</TableHead>
              <TableHead className="w-[20%]">Created</TableHead>
              <TableHead className="w-[80px] text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center">
                  <CenteredLoadingIndicator
                    className="min-h-24 bg-transparent"
                    spinnerClassName="h-5 w-5"
                    label="Loading users"
                  />
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="h-24 text-center text-muted-foreground">
                  <div className="flex flex-col items-center gap-2">
                    <Users className="h-8 w-8 opacity-40" />
                    <span>No users found</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell className="text-muted-foreground">
                    {user.id}
                  </TableCell>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="font-medium">{user.username}</div>
                      {user.email && (
                        <div className="truncate text-xs text-muted-foreground">
                          {user.email}
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {roleNameById.get(user.role_id) ?? "Unknown"}
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">
                      {user.status === "active" ? "Active" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatTimestamp(user.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={user.status === "active" ? `Disable ${user.username}` : `Enable ${user.username}`}
                        onClick={() => void toggleStatus(user)}
                      >
                        {user.status === "active" ? (
                          <CirclePause className="h-3.5 w-3.5" />
                        ) : (
                          <CirclePlay className="h-3.5 w-3.5" />
                        )}
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={`Edit user ${user.username}`}
                        onClick={() => openEdit(user)}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={dialogOpen} onOpenChange={(open) => {
        setDialogOpen(open);
        if (!open) {
          setFormErrors({});
          setEditingUser(null);
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{isEditing ? "Edit user" : "Create user"}</DialogTitle>
            <DialogDescription>
              {isEditing
                ? "Update role and email for this user account."
                : "Add a user account and assign its initial role."}
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            {isEditing ? (
              <Field>
                <FieldLabel>Username</FieldLabel>
                <InputGroup>
                  <InputGroupAddon>
                    <User />
                  </InputGroupAddon>
                  <InputGroupInput
                    value={form.username}
                    readOnly
                    className="opacity-60"
                  />
                </InputGroup>
              </Field>
            ) : (
              <Field data-invalid={formErrors.username ? "" : undefined}>
                <FieldLabel htmlFor="new-username">
                  Username <span className="text-destructive">*</span>
                </FieldLabel>
                <InputGroup>
                  <InputGroupAddon>
                    <User />
                  </InputGroupAddon>
                  <InputGroupInput
                    id="new-username"
                    placeholder="johndoe"
                    value={form.username}
                    aria-invalid={formErrors.username ? true : undefined}
                    onChange={(event) => {
                      setForm((current) => ({ ...current, username: event.target.value }));
                      setFormErrors((current) => ({ ...current, username: "" }));
                    }}
                  />
                </InputGroup>
                {formErrors.username && (
                  <FieldError>{formErrors.username}</FieldError>
                )}
              </Field>
            )}

            {!isEditing && (
              <Field data-invalid={formErrors.password ? "" : undefined}>
                <FieldLabel htmlFor="new-password">
                  Password <span className="text-destructive">*</span>
                </FieldLabel>
                <InputGroup>
                  <InputGroupAddon>
                    <KeyRound />
                  </InputGroupAddon>
                  <InputGroupInput
                    id="new-password"
                    type="password"
                    placeholder="••••••••"
                    value={form.password}
                    aria-invalid={formErrors.password ? true : undefined}
                    onChange={(event) => {
                      setForm((current) => ({ ...current, password: event.target.value }));
                      setFormErrors((current) => ({ ...current, password: "" }));
                    }}
                  />
                </InputGroup>
                {formErrors.password && (
                  <FieldError>{formErrors.password}</FieldError>
                )}
              </Field>
            )}

            <Field data-invalid={formErrors.roleId ? "" : undefined}>
              <FieldLabel>
                Role <span className="text-destructive">*</span>
              </FieldLabel>
              <Select
                value={form.roleId}
                onValueChange={(value) => {
                  setForm((current) => ({ ...current, roleId: value }));
                  setFormErrors((current) => ({ ...current, roleId: "" }));
                }}
              >
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {roleOptions.map((role) => (
                    <SelectItem key={role.id} value={String(role.id)}>
                      {role.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {formErrors.roleId && (
                <FieldError>{formErrors.roleId}</FieldError>
              )}
            </Field>
            <Field>
              <FieldLabel htmlFor="new-email">Email</FieldLabel>
              <InputGroup>
                <InputGroupAddon>
                  <Mail />
                </InputGroupAddon>
                <InputGroupInput
                  id="new-email"
                  type="email"
                  placeholder="john@example.com"
                  value={form.email}
                  onChange={(event) =>
                    setForm((current) => ({ ...current, email: event.target.value }))
                  }
                />
              </InputGroup>
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void handleSubmit()} disabled={saving}>
              {saving ? "Saving…" : isEditing ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
});

export default UsersPanel;
