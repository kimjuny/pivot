import { useMemo, useState } from 'react';

import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';

export interface ResourceAuthAccess {
  use_scope: 'all' | 'selected';
  use_user_ids: number[];
  use_group_ids: number[];
  edit_user_ids: number[];
  edit_group_ids: number[];
}

export interface ResourceAuthUserOption {
  id: number;
  username: string;
  display_name: string | null;
  email: string | null;
}

export interface ResourceAuthGroupOption {
  id: number;
  name: string;
  description: string;
  member_count: number;
}

interface ResourceAuthTabProps {
  access: ResourceAuthAccess;
  users: ResourceAuthUserOption[];
  groups: ResourceAuthGroupOption[];
  loading?: boolean;
  lockedEditUserIds?: number[];
  onAccessChange: (access: ResourceAuthAccess) => void;
}

type AccessSection = 'use' | 'edit';

function userLabel(user: ResourceAuthUserOption): string {
  return user.display_name || user.username;
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

function ResourceAuthTab({
  access,
  users,
  groups,
  loading = false,
  lockedEditUserIds = [],
  onAccessChange,
}: ResourceAuthTabProps) {
  const lockedEditUsers = useMemo(
    () => new Set(lockedEditUserIds),
    [lockedEditUserIds],
  );
  const [activeSection, setActiveSection] = useState<AccessSection>('use');
  const filteredUsers = users;
  const filteredGroups = groups;

  const selectedUseCountLabel =
    access.use_scope === 'all'
      ? '*'
      : String(access.use_user_ids.length + access.use_group_ids.length);
  const selectedEditCount = access.edit_user_ids.length + access.edit_group_ids.length;

  function updateUserGrant(
    section: AccessSection,
    userId: number,
    checked: boolean,
  ) {
    if (section === 'edit' && lockedEditUsers.has(userId) && !checked) {
      return;
    }
    onAccessChange({
      ...access,
      [section === 'use' ? 'use_user_ids' : 'edit_user_ids']: toggleId(
        section === 'use' ? access.use_user_ids : access.edit_user_ids,
        userId,
        checked,
      ),
    });
  }

  function updateGroupGrant(
    section: AccessSection,
    groupId: number,
    checked: boolean,
  ) {
    onAccessChange({
      ...access,
      [section === 'use' ? 'use_group_ids' : 'edit_group_ids']: toggleId(
        section === 'use' ? access.use_group_ids : access.edit_group_ids,
        groupId,
        checked,
      ),
    });
  }

  function renderUserList(section: AccessSection) {
    const selectedIds =
      section === 'use' ? access.use_user_ids : access.edit_user_ids;

    return (
      <div className="max-h-52 overflow-y-auto rounded-md border">
        {loading ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            Loading users...
          </div>
        ) : filteredUsers.length === 0 ? (
          <div className="px-3 py-6 text-center text-sm text-muted-foreground">
            No users
          </div>
        ) : (
          filteredUsers.map((user) => {
            const isLocked = section === 'edit' && lockedEditUsers.has(user.id);
            return (
              <label
                key={`${section}-user-${user.id}`}
                className="flex cursor-pointer items-center gap-3 border-b px-3 py-2 last:border-b-0"
              >
                <Checkbox
                  checked={selectedIds.includes(user.id) || isLocked}
                  disabled={isLocked}
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
                    {user.email ? ` / ${user.email}` : ''}
                  </span>
                </span>
                {isLocked ? (
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

  function updateUseScope(useScope: 'all' | 'selected') {
    onAccessChange({
      ...access,
      use_scope: useScope,
      use_user_ids: useScope === 'all' ? [] : access.use_user_ids,
      use_group_ids: useScope === 'all' ? [] : access.use_group_ids,
    });
  }

  function renderGroupList(section: AccessSection) {
    const selectedIds =
      section === 'use' ? access.use_group_ids : access.edit_group_ids;

    return (
      <div className="max-h-44 overflow-y-auto rounded-md border">
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
                  {group.description ? ` / ${group.description}` : ''}
                </span>
              </span>
            </label>
          ))
        )}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-md border p-3">
        <div className="mb-3 text-sm font-medium">Who can use</div>
        <RadioGroup
          value={access.use_scope}
          onValueChange={(value: string) =>
            updateUseScope(value === 'selected' ? 'selected' : 'all')
          }
          className="gap-3"
        >
          <Label className="flex cursor-pointer items-start gap-3">
            <RadioGroupItem value="all" className="mt-0.5" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">Everyone</span>
              <span className="block text-xs text-muted-foreground">
                All active users can use this entity.
              </span>
            </span>
          </Label>
          <Label className="flex cursor-pointer items-start gap-3">
            <RadioGroupItem value="selected" className="mt-0.5" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">Selected Members</span>
              <span className="block text-xs text-muted-foreground">
                Only selected users and groups can use this entity.
              </span>
            </span>
          </Label>
        </RadioGroup>
      </div>

      <Tabs
        value={activeSection}
        onValueChange={(value) => setActiveSection(value as AccessSection)}
        className="space-y-4"
      >
        <TabsList variant="line" className="relative grid w-full grid-cols-2">
          <span
            className="absolute bottom-[-1px] left-0 flex w-1/2 justify-center transition-transform duration-200 ease-out"
            style={{
              transform:
                activeSection === 'edit' ? 'translateX(100%)' : 'translateX(0)',
            }}
            aria-hidden="true"
          >
            <span className="h-0.5 w-16 bg-foreground" />
          </span>
          <TabsTrigger
            value="use"
            className="rounded-none bg-transparent px-0 pb-2 pt-0 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            Use ({selectedUseCountLabel})
          </TabsTrigger>
          <TabsTrigger
            value="edit"
            className="rounded-none bg-transparent px-0 pb-2 pt-0 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
          >
            Edit ({selectedEditCount})
          </TabsTrigger>
        </TabsList>

        <TabsContent value="use" className="space-y-3">
          {access.use_scope === 'all' ? (
            <div className="rounded-md border bg-muted/30 px-3 py-6 text-sm text-muted-foreground">
              Everyone can use this entity. Switch to Selected Members to choose
              specific users or groups.
            </div>
          ) : (
            <>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Users</p>
                {renderUserList('use')}
              </div>
              <div className="space-y-2">
                <p className="text-xs font-medium text-muted-foreground">Groups</p>
                {renderGroupList('use')}
              </div>
            </>
          )}
        </TabsContent>

        <TabsContent value="edit" className="space-y-3">
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Users</p>
            {renderUserList('edit')}
          </div>
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Groups</p>
            {renderGroupList('edit')}
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ResourceAuthTab;
