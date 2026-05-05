import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createOperationsRole,
  listOperationsPermissions,
  listOperationsRoles,
  updateOperationsRolePermissions,
  type OperationsPermission,
  type OperationsRole,
} from "@/studio/operations/api";
import { Plus, ShieldCheck } from "@/lib/lucide";
import { cn } from "@/lib/utils";

const EMPTY_ROLE_FORM = {
  key: "",
  name: "",
  description: "",
};

function groupPermissions(permissions: OperationsPermission[]) {
  return permissions.reduce<Record<string, OperationsPermission[]>>(
    (groups, permission) => {
      const next = groups[permission.category] ?? [];
      return {
        ...groups,
        [permission.category]: [...next, permission],
      };
    },
    {},
  );
}

export default function RolesPage() {
  const [roles, setRoles] = useState<OperationsRole[]>([]);
  const [permissions, setPermissions] = useState<OperationsPermission[]>([]);
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(null);
  const [selectedPermissionKeys, setSelectedPermissionKeys] = useState<Set<string>>(
    new Set(),
  );
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);
  const [form, setForm] = useState(EMPTY_ROLE_FORM);
  const [creating, setCreating] = useState(false);

  const selectedRole = roles.find((role) => role.id === selectedRoleId) ?? null;
  const groupedPermissions = useMemo(
    () => groupPermissions(permissions),
    [permissions],
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [nextRoles, nextPermissions] = await Promise.all([
        listOperationsRoles(),
        listOperationsPermissions(),
      ]);
      setRoles(nextRoles);
      setPermissions(nextPermissions);
      const nextSelected = nextRoles.find((role) => role.key === "builder") ?? nextRoles[0] ?? null;
      setSelectedRoleId(nextSelected?.id ?? null);
      setSelectedPermissionKeys(new Set(nextSelected?.permissions ?? []));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load roles");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function handleSelectRole(role: OperationsRole) {
    setSelectedRoleId(role.id);
    setSelectedPermissionKeys(new Set(role.permissions));
  }

  function togglePermission(permissionKey: string, checked: boolean) {
    setSelectedPermissionKeys((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(permissionKey);
      } else {
        next.delete(permissionKey);
      }
      return next;
    });
  }

  async function handleSavePermissions() {
    if (!selectedRole) return;
    setSaving(true);
    try {
      const updated = await updateOperationsRolePermissions(
        selectedRole.id,
        Array.from(selectedPermissionKeys).sort(),
      );
      setRoles((current) =>
        current.map((role) => (role.id === updated.id ? updated : role)),
      );
      setSelectedPermissionKeys(new Set(updated.permissions));
      toast.success("Role permissions updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save role");
    } finally {
      setSaving(false);
    }
  }

  async function handleCreateRole() {
    if (!form.key.trim() || !form.name.trim()) {
      toast.error("Role key and name are required");
      return;
    }
    setCreating(true);
    try {
      const created = await createOperationsRole({
        key: form.key.trim(),
        name: form.name.trim(),
        description: form.description.trim(),
      });
      setRoles((current) => [...current, created]);
      setSelectedRoleId(created.id);
      setSelectedPermissionKeys(new Set(created.permissions));
      setForm(EMPTY_ROLE_FORM);
      setIsCreateOpen(false);
      toast.success("Role created");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create role");
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-8">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Roles</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Configure system permissions assigned to each role
          </p>
        </div>
        <Button onClick={() => setIsCreateOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" />
          New Role
        </Button>
      </div>

      {error && (
        <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <CenteredLoadingIndicator className="min-h-64" label="Loading roles" />
      ) : (
        <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
          <div className="rounded-md border">
            <Table className="table-fixed" containerClassName="overflow-hidden">
              <TableHeader>
                <TableRow>
                  <TableHead>Role</TableHead>
                  <TableHead className="w-[96px] text-right">Permissions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {roles.map((role) => (
                  <TableRow
                    key={role.id}
                    className={cn(
                      "cursor-pointer",
                      selectedRoleId === role.id && "bg-accent/50",
                    )}
                    onClick={() => handleSelectRole(role)}
                  >
                    <TableCell>
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{role.name}</span>
                          {role.is_system && <Badge variant="outline">System</Badge>}
                        </div>
                        <div className="font-mono text-xs text-muted-foreground">
                          {role.key}
                        </div>
                        {role.description && (
                          <div className="line-clamp-2 text-xs text-muted-foreground">
                            {role.description}
                          </div>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <Badge variant="secondary">{role.permissions.length}</Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>

          <div className="rounded-md border p-5">
            {selectedRole ? (
              <>
                <div className="mb-5 flex items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <ShieldCheck className="h-4 w-4 text-primary" />
                      <h2 className="font-semibold">{selectedRole.name}</h2>
                      <Badge variant="outline">{selectedRole.key}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-muted-foreground">
                      {selectedRole.description || "No description"}
                    </p>
                  </div>
                  <Button onClick={() => void handleSavePermissions()} disabled={saving}>
                    Save
                  </Button>
                </div>

                <div className="space-y-6">
                  {Object.entries(groupedPermissions).map(
                    ([category, categoryPermissions]) => (
                      <section key={category}>
                        <h3 className="mb-3 text-sm font-medium">{category}</h3>
                        <div className="grid gap-3 sm:grid-cols-2">
                          {categoryPermissions.map((permission) => {
                            const checked = selectedPermissionKeys.has(permission.key);
                            return (
                              <label
                                key={permission.key}
                                className="flex cursor-pointer gap-3 rounded-md border p-3 hover:bg-accent/40"
                              >
                                <Checkbox
                                  checked={checked}
                                  onCheckedChange={(value) =>
                                    togglePermission(permission.key, value === true)
                                  }
                                  className="mt-0.5"
                                />
                                <span className="min-w-0">
                                  <span className="block text-sm font-medium">
                                    {permission.name}
                                  </span>
                                  <span className="block font-mono text-xs text-muted-foreground">
                                    {permission.key}
                                  </span>
                                  <span className="mt-1 block text-xs text-muted-foreground">
                                    {permission.description}
                                  </span>
                                </span>
                              </label>
                            );
                          })}
                        </div>
                      </section>
                    ),
                  )}
                </div>
              </>
            ) : (
              <div className="flex min-h-64 items-center justify-center text-sm text-muted-foreground">
                Select a role
              </div>
            )}
          </div>
        </div>
      )}

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create role</DialogTitle>
            <DialogDescription>
              Add a role, then select the permissions it should receive.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4">
            <Field>
              <FieldLabel htmlFor="role-key">Key</FieldLabel>
              <Input
                id="role-key"
                value={form.key}
                placeholder="support_operator"
                onChange={(event) =>
                  setForm((current) => ({ ...current, key: event.target.value }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="role-name">Name</FieldLabel>
              <Input
                id="role-name"
                value={form.name}
                placeholder="Support Operator"
                onChange={(event) =>
                  setForm((current) => ({ ...current, name: event.target.value }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="role-description">Description</FieldLabel>
              <Textarea
                id="role-description"
                value={form.description}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
            </Field>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => void handleCreateRole()} disabled={creating}>
              Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
