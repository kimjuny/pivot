import { type ReactNode, useEffect, useMemo, useState } from 'react';

import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import { Info } from '@/lib/lucide';

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
  disabled?: boolean;
  hideEdit?: boolean;
  editDisabled?: boolean;
  editTooltip?: ReactNode;
  editDisabledMessage?: string;
  useTitle?: string;
  useEveryoneDescription?: string;
  useSelectedDescription?: string;
  useEveryoneMessage?: string;
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
  disabled = false,
  hideEdit = false,
  editDisabled = false,
  editTooltip,
  editDisabledMessage,
  useTitle = 'Who can use',
  useEveryoneDescription = 'All active users can use this entity.',
  useSelectedDescription = 'Only selected users and groups can use this entity.',
  useEveryoneMessage = 'Everyone can use this entity. Switch to Selected Members to choose specific users or groups.',
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

  useEffect(() => {
    if (hideEdit && activeSection === 'edit') {
      setActiveSection('use');
    }
  }, [activeSection, hideEdit]);

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
    if (disabled) return;
    if (section === 'edit' && editDisabled) return;
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
    if (disabled) return;
    if (section === 'edit' && editDisabled) return;
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
                className={`flex items-center gap-3 border-b px-3 py-2 last:border-b-0 ${
                  disabled || (section === 'edit' && editDisabled)
                    ? 'cursor-default'
                    : 'cursor-pointer'
                }`}
              >
                <Checkbox
                  checked={selectedIds.includes(user.id) || isLocked}
                  disabled={disabled || isLocked || (section === 'edit' && editDisabled)}
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
    if (disabled) return;
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
              className={`flex items-center gap-3 border-b px-3 py-2 last:border-b-0 ${
                disabled || (section === 'edit' && editDisabled)
                  ? 'cursor-default'
                  : 'cursor-pointer'
              }`}
            >
              <Checkbox
                checked={selectedIds.includes(group.id)}
                disabled={disabled || (section === 'edit' && editDisabled)}
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
        <div className="mb-3 text-sm font-medium">{useTitle}</div>
        <RadioGroup
          value={access.use_scope}
          disabled={disabled}
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
                {useEveryoneDescription}
              </span>
            </span>
          </Label>
          <Label className="flex cursor-pointer items-start gap-3">
            <RadioGroupItem value="selected" className="mt-0.5" />
            <span className="min-w-0">
              <span className="block text-sm font-medium">Selected Members</span>
              <span className="block text-xs text-muted-foreground">
                {useSelectedDescription}
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
        <TabsList
          variant="line"
          className={`relative grid w-full ${hideEdit ? 'grid-cols-1' : 'grid-cols-2'}`}
        >
          <span
            className={`absolute bottom-[-1px] left-0 flex justify-center transition-transform duration-200 ease-out ${
              hideEdit ? 'w-full' : 'w-1/2'
            }`}
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
          {!hideEdit ? (
            <TabsTrigger
              value="edit"
              className="rounded-none bg-transparent px-0 pb-2 pt-0 shadow-none data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              <span className="flex items-center gap-1.5">
                Edit ({selectedEditCount})
                {editTooltip ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Info className="h-3.5 w-3.5 cursor-help text-muted-foreground" />
                    </TooltipTrigger>
                    <TooltipContent side="top" className="max-w-xs">
                      {typeof editTooltip === 'string' ? <p>{editTooltip}</p> : editTooltip}
                    </TooltipContent>
                  </Tooltip>
                ) : null}
              </span>
            </TabsTrigger>
          ) : null}
        </TabsList>

        <TabsContent value="use" className="space-y-3">
          {access.use_scope === 'all' ? (
            <div className="rounded-md border bg-muted/30 px-3 py-6 text-sm text-muted-foreground">
              {useEveryoneMessage}
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

        {!hideEdit ? (
          <TabsContent value="edit" className="space-y-3">
            {editDisabledMessage ? (
              <div className="rounded-md border bg-muted/30 px-3 py-3 text-xs text-muted-foreground">
                {editDisabledMessage}
              </div>
            ) : null}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Users</p>
              {renderUserList('edit')}
            </div>
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground">Groups</p>
              {renderGroupList('edit')}
            </div>
          </TabsContent>
        ) : null}
      </Tabs>
    </div>
  );
}

export default ResourceAuthTab;
