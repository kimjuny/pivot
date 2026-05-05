import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import {
  getAgentAccess,
  getAgentAccessOptions,
  updateAgentAccess,
  type AgentAccess,
  type AgentAccessGroupOption,
  type AgentAccessUserOption,
} from '@/utils/api';

interface AgentAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agentId: number;
  creatorUserId?: number | null;
  onSaved?: () => void | Promise<void>;
}

type AccessSection = 'use' | 'edit';

const EMPTY_ACCESS: AgentAccess = {
  agent_id: 0,
  use_scope: 'selected',
  use_user_ids: [],
  use_group_ids: [],
  edit_user_ids: [],
  edit_group_ids: [],
};

function userLabel(user: AgentAccessUserOption): string {
  return user.display_name || user.username;
}

function userMatchesSearch(user: AgentAccessUserOption, search: string): boolean {
  const haystack = [
    user.username,
    user.display_name ?? '',
    user.email ?? '',
  ].join(' ').toLowerCase();
  return haystack.includes(search.trim().toLowerCase());
}

function groupMatchesSearch(group: AgentAccessGroupOption, search: string): boolean {
  const haystack = [group.name, group.description].join(' ').toLowerCase();
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

function AgentAccessDialog({
  open,
  onOpenChange,
  agentId,
  creatorUserId,
  onSaved,
}: AgentAccessDialogProps) {
  const [access, setAccess] = useState<AgentAccess>(EMPTY_ACCESS);
  const [users, setUsers] = useState<AgentAccessUserOption[]>([]);
  const [groups, setGroups] = useState<AgentAccessGroupOption[]>([]);
  const [search, setSearch] = useState('');
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

  const selectedUseCount =
    access.use_scope === 'all'
      ? users.length
      : access.use_user_ids.length + access.use_group_ids.length;
  const selectedEditCount = access.edit_user_ids.length + access.edit_group_ids.length;

  useEffect(() => {
    if (!open) {
      return;
    }

    let isCancelled = false;
    setLoading(true);
    void Promise.all([
      getAgentAccess(agentId),
      getAgentAccessOptions(agentId),
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
        toast.error(err instanceof Error ? err.message : 'Failed to load access');
      })
      .finally(() => {
        if (!isCancelled) {
          setLoading(false);
        }
      });

    return () => {
      isCancelled = true;
    };
  }, [agentId, open]);

  function updateUserGrant(
    section: AccessSection,
    userId: number,
    checked: boolean,
  ) {
    setAccess((current) => ({
      ...current,
      [section === 'use' ? 'use_user_ids' : 'edit_user_ids']: toggleId(
        section === 'use' ? current.use_user_ids : current.edit_user_ids,
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
      [section === 'use' ? 'use_group_ids' : 'edit_group_ids']: toggleId(
        section === 'use' ? current.use_group_ids : current.edit_group_ids,
        groupId,
        checked,
      ),
    }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      const saved = await updateAgentAccess(agentId, {
        ...access,
        agent_id: agentId,
        use_user_ids: access.use_scope === 'all' ? [] : access.use_user_ids,
        use_group_ids: access.use_scope === 'all' ? [] : access.use_group_ids,
      });
      setAccess(saved);
      toast.success('Agent access updated');
      await onSaved?.();
      onOpenChange(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update access');
    } finally {
      setSaving(false);
    }
  }

  function renderUserList(section: AccessSection) {
    const selectedIds =
      section === 'use' ? access.use_user_ids : access.edit_user_ids;
    const isUseAll = section === 'use' && access.use_scope === 'all';

    return (
      <div className="max-h-64 overflow-y-auto rounded-md border">
        {loading ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Loading users…
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            No users
          </div>
        ) : (
          filteredUsers.map((user) => {
            const isCreator = creatorUserId === user.id;
            const checked = isUseAll || selectedIds.includes(user.id);
            const disabled = isUseAll || (section === 'edit' && isCreator);
            return (
              <label
                key={`${section}-${user.id}`}
                className={cn(
                  'flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-b-0',
                  disabled && 'cursor-default opacity-70',
                )}
              >
                <Checkbox
                  checked={checked}
                  disabled={disabled}
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
                    {user.email ? ` · ${user.email}` : ''}
                  </span>
                </span>
                {isCreator ? (
                  <span className="rounded border px-1.5 py-0.5 text-[10px] text-muted-foreground">
                    Creator
                  </span>
                ) : null}
              </label>
            );
          })
        )}
      </div>
    );
  }

  function renderGroupList(section: AccessSection) {
    const selectedIds =
      section === 'use' ? access.use_group_ids : access.edit_group_ids;
    const isUseAll = section === 'use' && access.use_scope === 'all';

    if (isUseAll) {
      return null;
    }

    return (
      <div className="max-h-52 overflow-y-auto rounded-md border">
        {loading ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Loading groups…
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
                  {group.description ? ` · ${group.description}` : ''}
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
          <DialogTitle>Agent Access</DialogTitle>
        </DialogHeader>

        <div className="grid gap-4">
          <div className="grid grid-cols-2 gap-2 rounded-md border p-1">
            <Button
              type="button"
              variant={access.use_scope === 'all' ? 'default' : 'ghost'}
              onClick={() =>
                setAccess((current) => ({ ...current, use_scope: 'all' }))
              }
            >
              All users
            </Button>
            <Button
              type="button"
              variant={access.use_scope === 'selected' ? 'default' : 'ghost'}
              onClick={() =>
                setAccess((current) => ({ ...current, use_scope: 'selected' }))
              }
            >
              Selected
            </Button>
          </div>

          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search users"
          />

          <div className="grid gap-4 md:grid-cols-2">
            <section className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-sm font-medium">Use</h3>
                <span className="text-xs text-muted-foreground">
                  {access.use_scope === 'all' ? 'All' : selectedUseCount}
                </span>
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Users</p>
                {renderUserList('use')}
              </div>
              {access.use_scope === 'selected' ? (
                <div className="space-y-2">
                  <p className="text-xs font-medium text-muted-foreground">Groups</p>
                  {renderGroupList('use')}
                </div>
              ) : null}
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
                {renderUserList('edit')}
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Groups</p>
                {renderGroupList('edit')}
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
          <Button type="button" onClick={() => void handleSave()} disabled={saving}>
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default AgentAccessDialog;
