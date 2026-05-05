import { useEffect, useMemo, useState } from "react";
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
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
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
import { Plus, Users } from "@/lib/lucide";

const EMPTY_USER_FORM = {
  username: "",
  password: "",
  roleId: "",
  displayName: "",
  email: "",
};

export default function UsersPage() {
  const [users, setUsers] = useState<OperationsUser[]>([]);
  const [roles, setRoles] = useState<OperationsRole[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_USER_FORM);
  const [savingUserId, setSavingUserId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const roleOptions = useMemo(
    () => roles.map((role) => ({ id: role.id, key: role.key, name: role.name })),
    [roles],
  );

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
      setForm((current) => ({
        ...current,
        roleId: current.roleId || String(nextRoles.find((role) => role.key === "user")?.id ?? nextRoles[0]?.id ?? ""),
      }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function patchUser(userId: number, payload: { role_id?: number; status?: "active" | "disabled" }) {
    setSavingUserId(userId);
    try {
      const updated = await updateOperationsUser(userId, payload);
      setUsers((current) =>
        current.map((user) => (user.id === updated.id ? updated : user)),
      );
      toast.success("User updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update user");
    } finally {
      setSavingUserId(null);
    }
  }

  async function handleCreateUser() {
    if (!form.username.trim() || !form.password || !form.roleId) {
      toast.error("Username, password, and role are required");
      return;
    }
    setCreating(true);
    try {
      const created = await createOperationsUser({
        username: form.username.trim(),
        password: form.password,
        role_id: Number(form.roleId),
        display_name: form.displayName.trim() || null,
        email: form.email.trim() || null,
      });
      setUsers((current) => [created, ...current]);
      setForm({
        ...EMPTY_USER_FORM,
        roleId: form.roleId,
      });
      setIsCreateOpen(false);
      toast.success("User created");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create user");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Users</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Manage account status and role assignment
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" />
          New User
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      <div className="rounded-md border">
        <Table className="table-fixed" containerClassName="overflow-hidden">
          <TableHeader>
            <TableRow>
              <TableHead className="w-[30%]">User</TableHead>
              <TableHead className="w-[20%]">Role</TableHead>
              <TableHead className="w-[18%]">Status</TableHead>
              <TableHead className="w-[20%]">Created</TableHead>
              <TableHead className="w-[12%] text-right">ID</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center">
                  <CenteredLoadingIndicator
                    className="min-h-24 bg-transparent"
                    spinnerClassName="h-5 w-5"
                    label="Loading users"
                  />
                </TableCell>
              </TableRow>
            ) : users.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                  <div className="flex flex-col items-center gap-2">
                    <Users className="h-8 w-8 opacity-40" />
                    <span>No users found</span>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              users.map((user) => (
                <TableRow key={user.id}>
                  <TableCell>
                    <div className="space-y-1">
                      <div className="font-medium">{user.display_name || user.username}</div>
                      <div className="text-sm text-muted-foreground">{user.username}</div>
                      {user.email && (
                        <div className="truncate text-xs text-muted-foreground">
                          {user.email}
                        </div>
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Select
                      value={String(user.role_id)}
                      disabled={savingUserId === user.id}
                      onValueChange={(value) =>
                        void patchUser(user.id, { role_id: Number(value) })
                      }
                    >
                      <SelectTrigger size="small" className="w-[160px]">
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
                  </TableCell>
                  <TableCell>
                    <Select
                      value={user.status}
                      disabled={savingUserId === user.id}
                      onValueChange={(value) =>
                        void patchUser(user.id, {
                          status: value as "active" | "disabled",
                        })
                      }
                    >
                      <SelectTrigger size="small" className="w-[130px]">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="active">Active</SelectItem>
                        <SelectItem value="disabled">Disabled</SelectItem>
                      </SelectContent>
                    </Select>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {formatTimestamp(user.created_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <Badge variant="outline">{user.id}</Badge>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create user</DialogTitle>
            <DialogDescription>
              Add a user account and assign its initial role.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <Field>
              <FieldLabel htmlFor="new-username">Username</FieldLabel>
              <Input
                id="new-username"
                value={form.username}
                onChange={(event) =>
                  setForm((current) => ({ ...current, username: event.target.value }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="new-password">Password</FieldLabel>
              <Input
                id="new-password"
                type="password"
                value={form.password}
                onChange={(event) =>
                  setForm((current) => ({ ...current, password: event.target.value }))
                }
              />
            </Field>
            <Field>
              <FieldLabel>Role</FieldLabel>
              <Select
                value={form.roleId}
                onValueChange={(value) =>
                  setForm((current) => ({ ...current, roleId: value }))
                }
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
            </Field>
            <Field>
              <FieldLabel htmlFor="new-display-name">Display name</FieldLabel>
              <Input
                id="new-display-name"
                value={form.displayName}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    displayName: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="new-email">Email</FieldLabel>
              <Input
                id="new-email"
                type="email"
                value={form.email}
                onChange={(event) =>
                  setForm((current) => ({ ...current, email: event.target.value }))
                }
              />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void handleCreateUser()} disabled={creating}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
