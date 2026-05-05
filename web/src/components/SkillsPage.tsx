import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Globe2,
  Pencil,
  Plus,
  SlidersHorizontal,
  Trash2,
  Upload,
  User as UserIcon,
  X,
} from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getSharedSkills,
  getPrivateSkills,
  getUserSkillSource,
  getSharedSkillSource,
  upsertUserSkill,
  deleteUserSkill,
  getSkillAccess,
  getSkillAccessOptions,
  getSkillCreateAccessOptions,
  updateSkillAccess,
  type SkillAccess,
  type SkillAccessOptions,
  type SkillSource,
  type SharedSkill,
  type UserSkill,
} from '../utils/api';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { formatTimestamp } from '@/utils/timestamp';
import DraggableDialog from './DraggableDialog';
import SkillEditor from './SkillEditor';
import SkillImportDialog from './SkillImportDialog';
import ResourceAuthTab from '@/components/ResourceAuthTab';

const PAGE_SIZE = 10;

const NEW_SKILL_TEMPLATE = `---
name: my_skill
description: Briefly describe what this skill helps with.
---

# My Skill

Describe reusable guidance or process here.
`;

type SkillRow =
  | { kind: 'shared'; source: SkillSource; skill: SharedSkill }
  | { kind: 'private'; source: SkillSource; skill: UserSkill };

type SkillDialogTab = 'general' | 'auth';

const EMPTY_SKILL_ACCESS: SkillAccess = {
  skill_name: '',
  use_scope: 'all',
  use_user_ids: [],
  use_group_ids: [],
  edit_user_ids: [],
  edit_group_ids: [],
};

function buildPageList(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages: (number | 'ellipsis')[] = [1];
  if (current > 3) pages.push('ellipsis');
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);
  if (current < total - 2) pages.push('ellipsis');
  pages.push(total);
  return pages;
}

function sanitizeSkillName(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_.-]/g, '_')
    .replace(/^_+|_+$/g, '') || 'new_skill';
}

function extractFrontMatterName(source: string): string | null {
  const lines = source.split('\n');
  if (lines.length < 3 || lines[0].trim() !== '---') return null;
  for (let i = 1; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line === '---') break;
    if (line.toLowerCase().startsWith('name:')) {
      const val = line.split(':', 2)[1]?.trim();
      return val || null;
    }
  }
  return null;
}

/** Skill management page. */
function SkillsPage() {
  const [sharedSkills, setSharedSkills] = useState<SharedSkill[]>([]);
  const [privateSkills, setPrivateSkills] = useState<UserSkill[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  const [searchQuery, setSearchQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<'all' | 'shared' | 'private'>('all');
  const [currentPage, setCurrentPage] = useState(1);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editingKind, setEditingKind] = useState<'private' | 'shared'>('private');
  const [editorSource, setEditorSource] = useState('');
  const [editorReadOnly, setEditorReadOnly] = useState(false);
  const [editorSaveMode, setEditorSaveMode] = useState<'direct' | 'dialog'>('direct');
  const [isSaving, setIsSaving] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [skillDialogOpen, setSkillDialogOpen] = useState(false);
  const [skillDialogTab, setSkillDialogTab] = useState<SkillDialogTab>('general');
  const [skillDialogMode, setSkillDialogMode] = useState<'create' | 'edit'>('create');
  const [skillDialogKind, setSkillDialogKind] = useState<'private' | 'shared'>('private');
  const [skillDialogName, setSkillDialogName] = useState('');
  const [skillDialogSource, setSkillDialogSource] = useState(NEW_SKILL_TEMPLATE);
  const [skillAccess, setSkillAccess] = useState<SkillAccess>(EMPTY_SKILL_ACCESS);
  const [skillAccessUsers, setSkillAccessUsers] =
    useState<SkillAccessOptions['users']>([]);
  const [skillAccessGroups, setSkillAccessGroups] =
    useState<SkillAccessOptions['groups']>([]);
  const [skillAccessLoading, setSkillAccessLoading] = useState(false);

  const loadSkills = useCallback(async () => {
    setIsLoading(true);
    try {
      const [shared, priv] = await Promise.all([getSharedSkills(), getPrivateSkills()]);
      setSharedSkills(shared);
      setPrivateSkills(priv);
    } catch {
      toast.error('Failed to load skills');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSkills();
  }, [loadSkills]);

  const allRows: SkillRow[] = useMemo(
    () => [
      ...sharedSkills.map((s): SkillRow => ({ kind: 'shared', source: s.source, skill: s })),
      ...privateSkills.map((s): SkillRow => ({ kind: 'private', source: s.source, skill: s })),
    ],
    [sharedSkills, privateSkills]
  );

  const filteredRows = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allRows.filter((row) => {
      if (kindFilter !== 'all' && row.kind !== kindFilter) return false;
      if (!q) return true;
      return row.skill.name.toLowerCase().includes(q) || row.skill.description.toLowerCase().includes(q);
    });
  }, [allRows, searchQuery, kindFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, kindFilter]);

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredRows.slice(start, start + PAGE_SIZE);
  }, [filteredRows, currentPage]);

  const openCreateDialog = async () => {
    setSkillDialogMode('create');
    setSkillDialogKind('private');
    setSkillDialogTab('general');
    setSkillDialogName('my_skill');
    setSkillDialogSource(NEW_SKILL_TEMPLATE);
    setSkillAccess(EMPTY_SKILL_ACCESS);
    setSkillDialogOpen(true);
    setSkillAccessLoading(true);
    try {
      const options = await getSkillCreateAccessOptions();
      setSkillAccessUsers(options.users);
      setSkillAccessGroups(options.groups);
    } catch {
      toast.error('Failed to load skill auth options');
    } finally {
      setSkillAccessLoading(false);
    }
  };

  const openDialogSourceEditor = async () => {
    setEditingName(skillDialogMode === 'edit' ? skillDialogName : null);
    setEditingKind(skillDialogKind);
    if (skillDialogMode === 'edit') {
      try {
        const result = await getUserSkillSource(skillDialogKind, skillDialogName);
        setEditorSource(result.source);
      } catch {
        toast.error(`Failed to load skill "${skillDialogName}"`);
        return;
      }
    } else {
      setEditorSource(skillDialogSource);
    }
    setEditorReadOnly(false);
    setEditorSaveMode('dialog');
    setEditorOpen(true);
  };

  const openSkillDialog = useCallback(async (row: SkillRow) => {
    if (row.skill.read_only) {
      toast.error('This skill is read-only');
      return;
    }
    setSkillDialogMode('edit');
    setSkillDialogKind(row.kind);
    setSkillDialogTab('general');
    setSkillDialogName(row.skill.name);
    setSkillDialogSource('');
    setSkillAccessLoading(true);
    setSkillDialogOpen(true);
    try {
      const [nextAccess, options] = await Promise.all([
        getSkillAccess(row.skill.name),
        getSkillAccessOptions(row.skill.name),
      ]);
      setSkillAccess(nextAccess);
      setSkillAccessUsers(options.users);
      setSkillAccessGroups(options.groups);
    } catch {
      toast.error(`Failed to load skill auth for "${row.skill.name}"`);
      setSkillDialogOpen(false);
    } finally {
      setSkillAccessLoading(false);
    }
  }, []);

  const openSourceEditor = useCallback(async (row: SkillRow) => {
    try {
      if (row.kind === 'private') {
        const result = await getUserSkillSource('private', row.skill.name);
        setEditorSaveMode('direct');
        setEditingKind('private');
        setEditingName(row.skill.name);
        setEditorSource(result.source);
        setEditorReadOnly(false);
        setEditorOpen(true);
        return;
      }

      if (!row.skill.read_only) {
        const result = await getUserSkillSource('shared', row.skill.name);
        setEditorSaveMode('direct');
        setEditingKind('shared');
        setEditingName(row.skill.name);
        setEditorSource(result.source);
        setEditorReadOnly(false);
        setEditorOpen(true);
        return;
      }

      const result = await getSharedSkillSource(row.skill.name);
      setEditorSaveMode('direct');
      setEditingKind('shared');
      setEditingName(row.skill.name);
      setEditorSource(result.source);
      setEditorReadOnly(true);
      setEditorOpen(true);
    } catch {
      toast.error(`Failed to load skill "${row.skill.name}"`);
    }
  }, []);

  const handleSave = useCallback(async (source: string) => {
    if (editorReadOnly) {
      toast.error('This skill is read-only');
      return;
    }

    let targetName = editingName;
    if (!targetName) {
      targetName = sanitizeSkillName(extractFrontMatterName(source) ?? 'new_skill');
    }

    setIsSaving(true);
    try {
      await upsertUserSkill(editingKind, targetName, source);
      toast.success(`Skill "${targetName}" saved`);
      setEditorOpen(false);
      await loadSkills();
    } catch {
      toast.error(`Failed to save skill "${targetName}"`);
    } finally {
      setIsSaving(false);
    }
  }, [editingKind, editingName, editorReadOnly, loadSkills]);

  const handleSkillDialogSave = useCallback(async () => {
    const targetName = sanitizeSkillName(skillDialogName);
    if (!targetName) {
      toast.error('Skill name is required');
      return;
    }

    setIsSaving(true);
    try {
      if (skillDialogMode === 'create') {
        await upsertUserSkill('private', targetName, skillDialogSource);
      }
      await updateSkillAccess(targetName, {
        use_scope: skillAccess.use_scope,
        use_user_ids: skillAccess.use_user_ids,
        use_group_ids: skillAccess.use_group_ids,
        edit_user_ids: skillAccess.edit_user_ids,
        edit_group_ids: skillAccess.edit_group_ids,
      });
      toast.success(`Skill "${targetName}" saved`);
      setSkillDialogOpen(false);
      await loadSkills();
    } catch {
      toast.error(`Failed to save skill "${targetName}"`);
    } finally {
      setIsSaving(false);
    }
  }, [
    skillAccess,
    skillDialogMode,
    skillDialogName,
    skillDialogSource,
    loadSkills,
  ]);

  const handleDelete = useCallback(async (row: SkillRow) => {
    if (row.skill.read_only) {
      toast.error('This skill is read-only');
      return;
    }

    const kind = row.kind === 'private' ? 'private' : 'shared';
    try {
      await deleteUserSkill(kind, row.skill.name);
      toast.success(`Skill "${row.skill.name}" deleted`);
      await loadSkills();
    } catch {
      toast.error(`Failed to delete skill "${row.skill.name}"`);
    }
  }, [loadSkills]);

  const sharedCount = allRows.filter((r) => r.kind === 'shared').length;
  const privateCount = allRows.filter((r) => r.kind === 'private').length;
  const existingSkillNames = useMemo(
    () => new Set(allRows.map((row) => row.skill.name)),
    [allRows]
  );
  const skillDialogCreatorId = useMemo(
    () =>
      allRows.find((row) => row.skill.name === skillDialogName)?.skill.creator_id ??
      null,
    [allRows, skillDialogName],
  );

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Skills</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage reusable skills and control who can use or edit each one.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => setImportDialogOpen(true)}
            className="flex items-center gap-1.5"
          >
            <Upload className="w-4 h-4" />
            Import
          </Button>
          <Button
            size="sm"
            className="flex items-center gap-1.5"
            onClick={() => void openCreateDialog()}
          >
            <Plus className="w-4 h-4" />
            New
          </Button>
        </div>
      </div>

      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {(
            [
              { value: 'all', label: 'All', count: allRows.length },
              { value: 'shared', label: 'Shared', count: sharedCount },
              { value: 'private', label: 'Private', count: privateCount },
            ] as const
          ).map(({ value, label, count }) => (
            <button
              key={value}
              onClick={() => setKindFilter(value)}
              className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
            >
              <Badge
                variant={kindFilter === value ? 'default' : 'outline'}
                className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                  kindFilter === value ? 'list-filter-badge-active' : ''
                }`}
              >
                {label}
                <span className={kindFilter === value ? 'opacity-70' : 'text-muted-foreground'}>{count}</span>
              </Badge>
            </button>
          ))}
          {kindFilter !== 'all' && (
            <button
              onClick={() => setKindFilter('all')}
              className="text-muted-foreground hover:text-foreground transition-colors"
              aria-label="Clear filter"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}
        </div>

        <ButtonGroup className="list-search-group">
          <Input
            placeholder="Search by name or description…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search skills"
            autoComplete="off"
          />
          <Button variant="outline" size="sm" aria-label="Search skills" tabIndex={-1}>
            Search
          </Button>
        </ButtonGroup>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">Loading skills…</div>
      ) : filteredRows.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          {allRows.length === 0 ? (
            <>
              <p className="text-sm">No skills found.</p>
              <Button size="sm" variant="outline" onClick={() => void openCreateDialog()}>
                <Plus className="w-4 h-4 mr-1.5" />
                Create your first skill
              </Button>
            </>
          ) : (
            <p className="text-sm">No skills match your search.</p>
          )}
        </div>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[220px]">Name</TableHead>
                <TableHead className="w-[120px]">Kind</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="w-[170px]">Updated</TableHead>
                <TableHead className="w-[120px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pagedRows.map((row) => (
                <TableRow key={`${row.kind}-${row.source}-${row.skill.name}`}>
                  <TableCell className="font-mono text-xs font-medium">{row.skill.name}</TableCell>
                  <TableCell>
                    {row.kind === 'private' ? (
                      <Badge variant="outline" className="flex items-center gap-1 w-fit text-[11px] px-1.5">
                        <UserIcon className="w-2.5 h-2.5" />
                        Private
                      </Badge>
                    ) : row.skill.read_only ? (
                      <Badge variant="secondary" className="flex items-center gap-1 w-fit text-[11px] px-1.5">
                        <Globe2 className="w-2.5 h-2.5" />
                        {`Shared / ${row.skill.creator ?? 'Unknown'}`}
                      </Badge>
                    ) : (
                      <Badge variant="secondary" className="flex items-center gap-1 w-fit text-[11px] px-1.5">
                        <Globe2 className="w-2.5 h-2.5" />
                        Shared / You
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-sm text-muted-foreground max-w-xs truncate">
                    {row.skill.description || '—'}
                  </TableCell>
                  <TableCell className="text-xs text-muted-foreground">
                    {formatTimestamp(row.skill.updated_at)}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1 flex-wrap">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={`Configure skill ${row.skill.name}`}
                        onClick={() => void openSkillDialog(row)}
                        disabled={row.skill.read_only}
                      >
                        <SlidersHorizontal className="w-3.5 h-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={`Edit SKILL.md for ${row.skill.name}`}
                        onClick={() => void openSourceEditor(row)}
                      >
                        <Pencil className="w-3.5 h-3.5" />
                      </Button>
                      {!row.skill.read_only && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-destructive hover:text-destructive"
                          aria-label={`Delete skill ${row.skill.name}`}
                          onClick={() => void handleDelete(row)}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {filteredRows.length} skill{filteredRows.length !== 1 ? 's' : ''}
                {searchQuery ? ' found' : ' total'}
              </span>
              <Pagination className="w-auto mx-0 justify-end">
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        if (currentPage > 1) setCurrentPage((p) => p - 1);
                      }}
                      className={currentPage === 1 ? 'pointer-events-none opacity-50' : ''}
                    />
                  </PaginationItem>

                  {buildPageList(currentPage, totalPages).map((page, idx) =>
                    page === 'ellipsis' ? (
                      <PaginationItem key={`ellipsis-${idx}`}>
                        <PaginationEllipsis />
                      </PaginationItem>
                    ) : (
                      <PaginationItem key={page}>
                        <PaginationLink
                          href="#"
                          isActive={page === currentPage}
                          onClick={(e) => {
                            e.preventDefault();
                            setCurrentPage(page);
                          }}
                        >
                          {page}
                        </PaginationLink>
                      </PaginationItem>
                    )
                  )}

                  <PaginationItem>
                    <PaginationNext
                      href="#"
                      onClick={(e) => {
                        e.preventDefault();
                        if (currentPage < totalPages) setCurrentPage((p) => p + 1);
                      }}
                      className={currentPage === totalPages ? 'pointer-events-none opacity-50' : ''}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </div>
          )}
        </>
      )}

      <Dialog open={skillDialogOpen} onOpenChange={setSkillDialogOpen}>
        <DialogContent className="flex max-h-[90vh] min-h-0 flex-col overflow-hidden sm:max-w-[720px]">
          <DialogHeader>
            <DialogTitle>
              {skillDialogMode === 'create' ? 'New Skill' : 'Edit Skill'}
            </DialogTitle>
          </DialogHeader>
          <Tabs
            value={skillDialogTab}
            onValueChange={(value) => setSkillDialogTab(value as SkillDialogTab)}
            className="min-h-0 flex-1"
          >
            <TabsList className="grid h-auto w-full grid-cols-2">
              <TabsTrigger value="general">General</TabsTrigger>
              <TabsTrigger value="auth">Auth</TabsTrigger>
            </TabsList>
            <TabsContent value="general" className="space-y-4 pt-4">
              <div className="space-y-2">
                <Label htmlFor="skill-name">Name</Label>
                <Input
                  id="skill-name"
                  value={skillDialogName}
                  onChange={(event) => setSkillDialogName(event.target.value)}
                  disabled={skillDialogMode === 'edit' || isSaving}
                  autoComplete="off"
                />
              </div>
              <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium">Edit SKILL.md file</div>
                  <div className="text-xs text-muted-foreground">
                    Open the markdown source editor for this skill.
                  </div>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void openDialogSourceEditor()}
                  disabled={isSaving}
                >
                  <Pencil className="h-3.5 w-3.5" />
                  Edit
                </Button>
              </div>
            </TabsContent>
            <TabsContent value="auth" className="pt-4">
              <ResourceAuthTab
                access={skillAccess}
                users={skillAccessUsers}
                groups={skillAccessGroups}
                loading={skillAccessLoading}
                lockedEditUserIds={
                  skillDialogMode === 'edit' && skillDialogCreatorId !== null
                    ? [skillDialogCreatorId]
                    : []
                }
                onAccessChange={(nextAccess) =>
                  setSkillAccess((current) => ({
                    ...current,
                    ...nextAccess,
                  }))
                }
              />
            </TabsContent>
          </Tabs>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setSkillDialogOpen(false)}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleSkillDialogSave()}
              disabled={isSaving || skillAccessLoading || !skillDialogName.trim()}
            >
              {isSaving ? 'Saving…' : 'Save'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <DraggableDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        title={
          editingName
            ? `${editorReadOnly ? 'View' : 'Edit'} Skill: ${editingName}`
            : 'Edit SKILL.md'
        }
        size="large"
      >
        <SkillEditor
          value={editorSource}
          onChange={setEditorSource}
          onSave={
            editorReadOnly
              ? undefined
              : (src) => {
                  if (editorSaveMode === 'dialog') {
                    setSkillDialogSource(src);
                    setEditorOpen(false);
                    return;
                  }
                  void handleSave(src);
                }
          }
          isSaving={isSaving}
          readOnly={editorReadOnly}
        />
      </DraggableDialog>

      <SkillImportDialog
        open={importDialogOpen}
        onOpenChange={setImportDialogOpen}
        existingSkillNames={existingSkillNames}
        onImported={loadSkills}
      />
    </div>
  );
}

export default SkillsPage;
