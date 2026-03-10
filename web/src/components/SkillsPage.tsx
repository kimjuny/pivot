import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ChevronDown,
  Globe2,
  KeyRound,
  Lock,
  Pencil,
  Plus,
  Share2,
  Trash2,
  User as UserIcon,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import {
  getSharedSkills,
  getPrivateSkills,
  getUserSkillSource,
  getSharedSkillSource,
  upsertUserSkill,
  deleteUserSkill,
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
import { Badge } from '@/components/ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { formatTimestamp } from '@/utils/timestamp';
import DraggableDialog from './DraggableDialog';
import SkillEditor from './SkillEditor';

const PAGE_SIZE = 10;

const NEW_SKILL_TEMPLATE = `---
name: my_skill
description: Briefly describe what this skill helps with.
---

# My Skill

Describe reusable guidance or process here.
`;

type SkillRow =
  | { kind: 'shared'; source: 'builtin' | 'user'; skill: SharedSkill }
  | { kind: 'private'; source: 'user'; skill: UserSkill };

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
  const [isSaving, setIsSaving] = useState(false);
  const [isCreateMenuOpen, setIsCreateMenuOpen] = useState(false);

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
      ...privateSkills.map((s): SkillRow => ({ kind: 'private', source: 'user', skill: s })),
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

  const openCreateDialog = (kind: 'private' | 'shared') => {
    setEditingName(null);
    setEditingKind(kind);
    setEditorSource(NEW_SKILL_TEMPLATE);
    setEditorReadOnly(false);
    setEditorOpen(true);
  };

  const openEditDialog = useCallback(async (row: SkillRow) => {
    try {
      if (row.kind === 'private') {
        const result = await getUserSkillSource('private', row.skill.name);
        setEditingKind('private');
        setEditingName(row.skill.name);
        setEditorSource(result.source);
        setEditorReadOnly(false);
        setEditorOpen(true);
        return;
      }

      if (!row.skill.read_only) {
        const result = await getUserSkillSource('shared', row.skill.name);
        setEditingKind('shared');
        setEditingName(row.skill.name);
        setEditorSource(result.source);
        setEditorReadOnly(false);
        setEditorOpen(true);
        return;
      }

      const result = await getSharedSkillSource(row.skill.name);
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

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Skills</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Shared skills are visible to everyone, but only the creator can edit them.
          </p>
        </div>
        <div
          onMouseEnter={() => setIsCreateMenuOpen(true)}
          onMouseLeave={() => setIsCreateMenuOpen(false)}
        >
          <DropdownMenu open={isCreateMenuOpen} onOpenChange={setIsCreateMenuOpen}>
            <DropdownMenuTrigger asChild>
              <Button size="sm" className="flex items-center gap-1.5">
                <Plus className="w-4 h-4" />
                New
                <ChevronDown className="w-3.5 h-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
              align="end"
              className="w-44"
              onMouseEnter={() => setIsCreateMenuOpen(true)}
              onMouseLeave={() => setIsCreateMenuOpen(false)}
            >
              <DropdownMenuItem
                onClick={() => {
                  openCreateDialog('shared');
                  setIsCreateMenuOpen(false);
                }}
                className="gap-2"
              >
                <Share2 className="w-4 h-4" />
                Shared
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  openCreateDialog('private');
                  setIsCreateMenuOpen(false);
                }}
                className="gap-2"
              >
                <KeyRound className="w-4 h-4" />
                Private
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
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
                className="cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors"
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
              <Button size="sm" variant="outline" onClick={() => openCreateDialog('private')}>
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
                <TableHead className="w-[100px] text-right">Actions</TableHead>
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
                    ) : row.source === 'builtin' ? (
                      <Badge variant="secondary" className="flex items-center gap-1 w-fit text-[11px] px-1.5">
                        <Lock className="w-2.5 h-2.5" />
                        Shared / Builtin
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
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7"
                        aria-label={`Edit skill ${row.skill.name}`}
                        onClick={() => void openEditDialog(row)}
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

      <DraggableDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        title={
          editingName
            ? `${editorReadOnly ? 'View' : 'Edit'} Skill: ${editingName}`
            : `New ${editingKind === 'shared' ? 'Shared' : 'Private'} Skill`
        }
        size="large"
      >
        <SkillEditor
          value={editorSource}
          onChange={setEditorSource}
          onSave={editorReadOnly ? undefined : (src) => void handleSave(src)}
          isSaving={isSaving}
          readOnly={editorReadOnly}
        />
      </DraggableDialog>
    </div>
  );
}

export default SkillsPage;
