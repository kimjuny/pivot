import { forwardRef, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { toast } from "sonner";

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Trash2, Users } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  createOperationsGroup,
  deleteOperationsGroup,
  listOperationsGroupMembers,
  listOperationsGroupUserOptions,
  listOperationsGroups,
  updateOperationsGroup,
  updateOperationsGroupMembers,
  type OperationsGroup,
  type OperationsGroupMember,
} from "@/studio/operations/api";
import { formatTimestamp } from "@/utils/timestamp";
import type { PanelHandle } from "@/studio/operations/UsersPanel";

const EMPTY_GROUP_FORM = {
  name: "",
  description: "",
};

function memberLabel(user: OperationsGroupMember): string {
  return user.username;
}

function matchesSearch(user: OperationsGroupMember, search: string): boolean {
  const haystack = [
    user.username,
    user.email ?? "",
  ].join(" ").toLowerCase();
  return haystack.includes(search.trim().toLowerCase());
}

function toggleId(ids: Set<number>, id: number, checked: boolean): Set<number> {
  const next = new Set(ids);
  if (checked) {
    next.add(id);
  } else {
    next.delete(id);
  }
  return next;
}

/** Panel for managing authorization groups — master-detail with member assignment. */
const GroupsPanel = forwardRef<PanelHandle>(function GroupsPanel(_props, ref) {
  const [groups, setGroups] = useState<OperationsGroup[]>([]);
  const [userOptions, setUserOptions] = useState<OperationsGroupMember[]>([]);
  const [selectedGroupId, setSelectedGroupId] = useState<number | null>(null);
  const [selectedMemberIds, setSelectedMemberIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [memberBaselineIds, setMemberBaselineIds] = useState<Set<number>>(
    () => new Set(),
  );
  const [search, setSearch] = useState("");
  const [form, setForm] = useState(EMPTY_GROUP_FORM);
  const [createForm, setCreateForm] = useState(EMPTY_GROUP_FORM);
  const [loading, setLoading] = useState(true);
  const [loadingMembers, setLoadingMembers] = useState(false);
  const [savingGroup, setSavingGroup] = useState(false);
  const [savingMembers, setSavingMembers] = useState(false);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isCreateOpen, setIsCreateOpen] = useState(false);

  const selectedGroup = useMemo(
    () => groups.find((group) => group.id === selectedGroupId) ?? null,
    [groups, selectedGroupId],
  );

  const filteredUsers = useMemo(
    () => userOptions.filter((user) => matchesSearch(user, search)),
    [search, userOptions],
  );

  const membersDirty = useMemo(() => {
    if (selectedMemberIds.size !== memberBaselineIds.size) {
      return true;
    }
    for (const id of selectedMemberIds) {
      if (!memberBaselineIds.has(id)) {
        return true;
      }
    }
    return false;
  }, [memberBaselineIds, selectedMemberIds]);

  useImperativeHandle(ref, () => ({
    triggerCreate: () => setIsCreateOpen(true),
  }));

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [nextGroups, nextUsers] = await Promise.all([
        listOperationsGroups(),
        listOperationsGroupUserOptions(),
      ]);
      setGroups(nextGroups);
      setUserOptions(nextUsers);
      setSelectedGroupId((current) => current ?? nextGroups[0]?.id ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load groups");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  useEffect(() => {
    if (!selectedGroup) {
      setForm(EMPTY_GROUP_FORM);
      setSelectedMemberIds(new Set());
      setMemberBaselineIds(new Set());
      return;
    }
    setForm({
      name: selectedGroup.name,
      description: selectedGroup.description,
    });
  }, [selectedGroup]);

  useEffect(() => {
    if (selectedGroupId === null) {
      return;
    }
    let isCancelled = false;
    setLoadingMembers(true);
    void listOperationsGroupMembers(selectedGroupId)
      .then((members) => {
        if (isCancelled) {
          return;
        }
        const nextIds = new Set(members.map((member) => member.id));
        setSelectedMemberIds(nextIds);
        setMemberBaselineIds(nextIds);
      })
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : "Failed to load members");
      })
      .finally(() => {
        if (!isCancelled) {
          setLoadingMembers(false);
        }
      });
    return () => {
      isCancelled = true;
    };
  }, [selectedGroupId]);

  async function handleCreateGroup() {
    if (!createForm.name.trim()) {
      toast.error("Group name is required");
      return;
    }
    setCreating(true);
    try {
      const created = await createOperationsGroup({
        name: createForm.name.trim(),
        description: createForm.description.trim(),
      });
      setGroups((current) => [...current, created].sort((a, b) => a.name.localeCompare(b.name)));
      setSelectedGroupId(created.id);
      setCreateForm(EMPTY_GROUP_FORM);
      setIsCreateOpen(false);
      toast.success("Group created");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to create group");
    } finally {
      setCreating(false);
    }
  }

  async function handleSaveGroup() {
    if (!selectedGroup) {
      return;
    }
    setSavingGroup(true);
    try {
      const updated = await updateOperationsGroup(selectedGroup.id, {
        name: form.name.trim(),
        description: form.description.trim(),
      });
      setGroups((current) =>
        current
          .map((group) => (group.id === updated.id ? updated : group))
          .sort((a, b) => a.name.localeCompare(b.name)),
      );
      toast.success("Group updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update group");
    } finally {
      setSavingGroup(false);
    }
  }

  async function handleSaveMembers() {
    if (!selectedGroup) {
      return;
    }
    setSavingMembers(true);
    try {
      const members = await updateOperationsGroupMembers(
        selectedGroup.id,
        Array.from(selectedMemberIds),
      );
      const nextIds = new Set(members.map((member) => member.id));
      setSelectedMemberIds(nextIds);
      setMemberBaselineIds(nextIds);
      setGroups((current) =>
        current.map((group) =>
          group.id === selectedGroup.id
            ? { ...group, member_count: members.length }
            : group,
        ),
      );
      toast.success("Members updated");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update members");
    } finally {
      setSavingMembers(false);
    }
  }

  async function handleDeleteGroup() {
    if (!selectedGroup) {
      return;
    }
    setDeleting(true);
    try {
      await deleteOperationsGroup(selectedGroup.id);
      const nextGroups = groups.filter((group) => group.id !== selectedGroup.id);
      setGroups(nextGroups);
      setSelectedGroupId(nextGroups[0]?.id ?? null);
      toast.success("Group deleted");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to delete group");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <>
      {error && (
        <div className="mb-4 rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      )}

      {loading ? (
        <CenteredLoadingIndicator className="min-h-80" label="Loading groups" />
      ) : groups.length === 0 ? (
        <div className="rounded-md border border-dashed py-16 text-center text-muted-foreground">
          <Users className="mx-auto mb-3 h-8 w-8 opacity-40" />
          <p>No groups yet</p>
        </div>
      ) : (
        <div className="grid gap-6 lg:grid-cols-[320px_1fr]">
          <div className="rounded-md border">
            {groups.map((group) => (
              <button
                key={group.id}
                type="button"
                onClick={() => setSelectedGroupId(group.id)}
                className={cn(
                  "flex w-full items-center justify-between gap-3 border-b px-4 py-3 text-left last:border-b-0 hover:bg-accent/50",
                  selectedGroupId === group.id && "bg-accent",
                )}
              >
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium">
                    {group.name}
                  </span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {group.description || "No description"}
                  </span>
                </span>
                <Badge variant="secondary">{group.member_count}</Badge>
              </button>
            ))}
          </div>

          {selectedGroup && (
            <div className="space-y-6">
              <section className="rounded-md border p-4">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-base font-semibold">Group Details</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Created {formatTimestamp(selectedGroup.created_at)}
                    </p>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    className="gap-2 text-destructive hover:text-destructive"
                    disabled={deleting}
                    onClick={() => void handleDeleteGroup()}
                  >
                    <Trash2 className="h-4 w-4" />
                    Delete
                  </Button>
                </div>
                <div className="grid gap-4">
                  <Field>
                    <FieldLabel htmlFor="group-name">Name</FieldLabel>
                    <Input
                      id="group-name"
                      value={form.name}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          name: event.target.value,
                        }))
                      }
                    />
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="group-description">Description</FieldLabel>
                    <Textarea
                      id="group-description"
                      value={form.description}
                      onChange={(event) =>
                        setForm((current) => ({
                          ...current,
                          description: event.target.value,
                        }))
                      }
                    />
                  </Field>
                  <div className="flex justify-end">
                    <Button
                      type="button"
                      disabled={savingGroup}
                      onClick={() => void handleSaveGroup()}
                    >
                      {savingGroup ? "Saving…" : "Save Details"}
                    </Button>
                  </div>
                </div>
              </section>

              <section className="rounded-md border p-4">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <div>
                    <h3 className="text-base font-semibold">Members</h3>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {selectedMemberIds.size} selected
                    </p>
                  </div>
                  <Button
                    type="button"
                    disabled={!membersDirty || savingMembers}
                    onClick={() => void handleSaveMembers()}
                  >
                    {savingMembers ? "Saving…" : "Save Members"}
                  </Button>
                </div>
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Search users"
                  className="mb-3"
                />
                <div className="max-h-[420px] overflow-y-auto rounded-md border">
                  {loadingMembers ? (
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                      Loading members…
                    </div>
                  ) : filteredUsers.length === 0 ? (
                    <div className="px-3 py-8 text-center text-sm text-muted-foreground">
                      No users
                    </div>
                  ) : (
                    filteredUsers.map((user) => (
                      <label
                        key={user.id}
                        className="flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-b-0"
                      >
                        <Checkbox
                          checked={selectedMemberIds.has(user.id)}
                          onCheckedChange={(value) =>
                            setSelectedMemberIds((current) =>
                              toggleId(current, user.id, value === true),
                            )
                          }
                        />
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm font-medium">
                            {memberLabel(user)}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {user.username}
                            {user.email ? ` · ${user.email}` : ""}
                          </span>
                        </span>
                      </label>
                    ))
                  )}
                </div>
              </section>
            </div>
          )}
        </div>
      )}

      <Dialog open={isCreateOpen} onOpenChange={setIsCreateOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create group</DialogTitle>
          </DialogHeader>
          <div className="grid gap-4">
            <Field>
              <FieldLabel htmlFor="new-group-name">Name</FieldLabel>
              <Input
                id="new-group-name"
                value={createForm.name}
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="new-group-description">Description</FieldLabel>
              <Textarea
                id="new-group-description"
                value={createForm.description}
                onChange={(event) =>
                  setCreateForm((current) => ({
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
            <Button onClick={() => void handleCreateGroup()} disabled={creating}>
              {creating ? "Creating…" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
});

export default GroupsPanel;
