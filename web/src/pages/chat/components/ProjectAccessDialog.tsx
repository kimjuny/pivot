import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  getProjectAccess,
  getProjectAccessOptions,
  updateProjectAccess,
  type ProjectAccess,
  type ProjectAccessGroupOption,
  type ProjectAccessUserOption,
} from "@/utils/api";

interface ProjectAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string | null;
  projectName?: string | null;
  onSaved?: () => void | Promise<void>;
}

type AccessSection = "use" | "edit";

const EMPTY_ACCESS: ProjectAccess = {
  project_id: "",
  use_user_ids: [],
  use_group_ids: [],
  edit_user_ids: [],
  edit_group_ids: [],
};

function userLabel(user: ProjectAccessUserOption): string {
  return user.display_name || user.username;
}

function userMatchesSearch(
  user: ProjectAccessUserOption,
  search: string,
): boolean {
  const haystack = [
    user.username,
    user.display_name ?? "",
    user.email ?? "",
  ].join(" ").toLowerCase();
  return haystack.includes(search.trim().toLowerCase());
}

function groupMatchesSearch(
  group: ProjectAccessGroupOption,
  search: string,
): boolean {
  const haystack = [group.name, group.description].join(" ").toLowerCase();
  return haystack.includes(search.trim().toLowerCase());
}

function toggleId(ids: number[], id: number, checked: boolean): number[] {
  const next = new Set(ids);
  if (checked) {
    next.add(id);
  } else {
    next.delete(id);
  }
  return Array.from(next).sort((left, right) => left - right);
}

function ProjectAccessDialog({
  open,
  onOpenChange,
  projectId,
  projectName,
  onSaved,
}: ProjectAccessDialogProps) {
  const [access, setAccess] = useState<ProjectAccess>(EMPTY_ACCESS);
  const [users, setUsers] = useState<ProjectAccessUserOption[]>([]);
  const [groups, setGroups] = useState<ProjectAccessGroupOption[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  const filteredUsers = useMemo(
    () => users.filter((user) => userMatchesSearch(user, search)),
    [search, users],
  );
  const filteredGroups = useMemo(
    () => groups.filter((group) => groupMatchesSearch(group, search)),
    [groups, search],
  );

  const selectedUseCount = access.use_user_ids.length + access.use_group_ids.length;
  const selectedEditCount =
    access.edit_user_ids.length + access.edit_group_ids.length;

  useEffect(() => {
    if (!open || !projectId) {
      return;
    }

    let isCancelled = false;
    setLoading(true);
    void Promise.all([
      getProjectAccess(projectId),
      getProjectAccessOptions(projectId),
    ])
      .then(([nextAccess, options]) => {
        if (isCancelled) {
          return;
        }
        setAccess(nextAccess);
        setUsers(options.users);
        setGroups(options.groups);
      })
      .catch((err) => {
        toast.error(err instanceof Error ? err.message : "Failed to load access");
      })
      .finally(() => {
        if (!isCancelled) {
          setLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [open, projectId]);

  function updateUserGrant(
    section: AccessSection,
    userId: number,
    checked: boolean,
  ) {
    setAccess((current) => ({
      ...current,
      [section === "use" ? "use_user_ids" : "edit_user_ids"]: toggleId(
        section === "use" ? current.use_user_ids : current.edit_user_ids,
        userId,
        checked,
      ),
    }));
  }

  function updateGroupGrant(
    section: AccessSection,
    groupId: number,
    checked: boolean,
  ) {
    setAccess((current) => ({
      ...current,
      [section === "use" ? "use_group_ids" : "edit_group_ids"]: toggleId(
        section === "use" ? current.use_group_ids : current.edit_group_ids,
        groupId,
        checked,
      ),
    }));
  }

  async function handleSave() {
    if (!projectId) {
      return;
    }
    setSaving(true);
    try {
      const saved = await updateProjectAccess(projectId, access);
      setAccess(saved);
      toast.success("Project access updated");
      await onSaved?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to update access");
    } finally {
      setSaving(false);
    }
  }

  function renderUserList(section: AccessSection) {
    const selectedIds =
      section === "use" ? access.use_user_ids : access.edit_user_ids;

    return (
      <div className="max-h-64 overflow-y-auto rounded-md border">
        {loading ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Loading users...
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            No users
          </div>
        ) : (
          filteredUsers.map((user) => (
            <label
              key={`${section}-${user.id}`}
              className={cn(
                "flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-b-0",
              )}
            >
              <Checkbox
                checked={selectedIds.includes(user.id)}
                onCheckedChange={(value) =>
                  updateUserGrant(section, user.id, value === true)
                }
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {userLabel(user)}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {user.username}
                  {user.email ? ` / ${user.email}` : ""}
                </span>
              </span>
            </label>
          ))
        )}
      </div>
    );
  }

  function renderGroupList(section: AccessSection) {
    const selectedIds =
      section === "use" ? access.use_group_ids : access.edit_group_ids;

    return (
      <div className="max-h-52 overflow-y-auto rounded-md border">
        {loading ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Loading groups...
          </div>
        ) : filteredGroups.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            No groups
          </div>
        ) : (
          filteredGroups.map((group) => (
            <label
              key={`${section}-group-${group.id}`}
              className="flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-b-0"
            >
              <Checkbox
                checked={selectedIds.includes(group.id)}
                onCheckedChange={(value) =>
                  updateGroupGrant(section, group.id, value === true)
                }
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {group.name}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {group.member_count} members
                  {group.description ? ` / ${group.description}` : ""}
                </span>
              </span>
            </label>
          ))
        )}
      </div>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>
            {projectName ? `Project Access: ${projectName}` : "Project Access"}
          </DialogTitle>
        </DialogHeader>

        <div className="grid gap-4">
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search users or groups"
          />

          <div className="grid gap-4 md:grid-cols-2">
            <section className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium">Use</h3>
                <span className="text-xs text-muted-foreground">
                  {selectedUseCount}
                </span>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Users</p>
                {renderUserList("use")}
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Groups</p>
                {renderGroupList("use")}
              </div>
            </section>

            <section className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium">Edit</h3>
                <span className="text-xs text-muted-foreground">
                  {selectedEditCount}
                </span>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Users</p>
                {renderUserList("edit")}
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Groups</p>
                {renderGroupList("edit")}
              </div>
            </section>
          </div>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || !projectId}
          >
            {saving ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default ProjectAccessDialog;
