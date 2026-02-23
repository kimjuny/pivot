import { useState, useEffect } from 'react';
import {
  Search,
  Plus,
  Pencil,
  Trash2,
  Loader2,
  Wrench,
  Code2,
  MoreHorizontal,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { toast } from 'sonner';
import {
  getToolsWithOwnership,
  getToolSource,
  createTool,
  updateTool,
  deleteTool,
} from '@/utils/api';
import type { ToolWithOwnership, ToolSource } from '@/types';
import ToolEditorDialog from './ToolEditorDialog';

type SortField = 'name' | 'tool_type' | 'owner_username';
type SortDir = 'asc' | 'desc';

/**
 * Tools list page component.
 *
 * Renders a sortable, searchable table of all tools (shared and private).
 * Edit / delete actions are only shown when the current user has permission.
 */
function ToolsList() {
  const [tools, setTools] = useState<ToolWithOwnership[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<'create' | 'edit'>('create');
  const [editingTool, setEditingTool] = useState<ToolWithOwnership | null>(null);
  const [editingSource, setEditingSource] = useState('');

  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    tool: ToolWithOwnership | null;
    isDeleting: boolean;
  }>({ isOpen: false, tool: null, isDeleting: false });

  const fetchTools = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getToolsWithOwnership();
      setTools(data);
    } catch (err) {
      const e = err as Error;
      setError(e.message || 'Failed to load tools');
      toast.error('Failed to load tools');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchTools();
  }, []);

  // ─── Sorting ─────────────────────────────────────────────────────────────────

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field)
      return <ChevronsUpDown className="w-3.5 h-3.5 opacity-40" />;
    return sortDir === 'asc' ? (
      <ChevronUp className="w-3.5 h-3.5" />
    ) : (
      <ChevronDown className="w-3.5 h-3.5" />
    );
  };

  // ─── Derived list ────────────────────────────────────────────────────────────

  const filteredAndSorted = tools
    .filter((tool) => {
      const q = searchQuery.toLowerCase();
      return (
        tool.name.toLowerCase().includes(q) ||
        tool.description.toLowerCase().includes(q) ||
        tool.tool_type.toLowerCase().includes(q) ||
        (tool.owner_username?.toLowerCase().includes(q) ?? false)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      const aVal = sortField === 'owner_username'
        ? (a.owner_username ?? '')
        : a[sortField];
      const bVal = sortField === 'owner_username'
        ? (b.owner_username ?? '')
        : b[sortField];
      cmp = aVal.localeCompare(bVal);
      return sortDir === 'asc' ? cmp : -cmp;
    });

  const sharedCount = tools.filter((t) => t.tool_type === 'shared').length;
  const privateCount = tools.filter((t) => t.tool_type === 'private').length;

  // ─── CRUD ─────────────────────────────────────────────────────────────────────

  const handleCreateTool = () => {
    setEditingTool(null);
    setEditingSource('');
    setEditorMode('create');
    setEditorOpen(true);
  };

  const handleEditTool = async (tool: ToolWithOwnership) => {
    try {
      const source: ToolSource = await getToolSource(tool.name);
      setEditingTool(tool);
      setEditingSource(source.source_code);
      setEditorMode('edit');
      setEditorOpen(true);
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || 'Failed to load tool source');
    }
  };

  /**
   * Persist a tool after the editor dialog saves.
   * Name and description are extracted server-side from the @tool decorator.
   */
  const handleSaveTool = async (sourceCode: string) => {
    if (editorMode === 'create') {
      await createTool({ source_code: sourceCode });
      toast.success('Tool created');
    } else if (editingTool) {
      await updateTool(editingTool.name, { source_code: sourceCode });
      toast.success('Tool updated');
    }
    void fetchTools();
  };

  const handleDeleteClick = (tool: ToolWithOwnership) => {
    setDeleteConfirmation({ isOpen: true, tool, isDeleting: false });
  };

  const handleConfirmDelete = async () => {
    const tool = deleteConfirmation.tool;
    if (!tool) return;
    try {
      setDeleteConfirmation((prev) => ({ ...prev, isDeleting: true }));
      await deleteTool(tool.name);
      toast.success('Tool deleted');
      setDeleteConfirmation({ isOpen: false, tool: null, isDeleting: false });
      void fetchTools();
    } catch (err) {
      const e = err as Error;
      toast.error(e.message || 'Failed to delete tool');
      setDeleteConfirmation((prev) => ({ ...prev, isDeleting: false }));
    }
  };

  // ─── Loading / Error states ──────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center h-64 gap-4">
        <p className="text-destructive text-sm">{error}</p>
        <Button size="sm" onClick={() => void fetchTools()}>
          Retry
        </Button>
      </div>
    );
  }

  // ─── Main render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col flex-1 min-h-0 bg-background text-foreground">
      {/* ── Page header ── */}
      <div className="flex flex-col gap-4 px-6 pt-6 pb-4">
        {/* Title row */}
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-primary/15 flex items-center justify-center">
              <Wrench className="w-4 h-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">Tools</h1>
              <p className="text-xs text-muted-foreground mt-0.5">
                {tools.length} tool{tools.length !== 1 ? 's' : ''}
                {tools.length > 0 && (
                  <span className="ml-1.5">
                    <span className="text-muted-foreground/60">·</span>
                    <span className="ml-1.5">{sharedCount} shared</span>
                    <span className="mx-1 text-muted-foreground/60">·</span>
                    <span>{privateCount} private</span>
                  </span>
                )}
              </p>
            </div>
          </div>

          <Button size="sm" onClick={handleCreateTool} className="gap-1.5" aria-label="Create a new tool">
            <Plus className="w-3.5 h-3.5" aria-hidden="true" />
            New Tool
          </Button>
        </div>

        {/* Search */}
        <div className="relative max-w-sm">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none z-10"
            aria-hidden="true"
          />
          <ButtonGroup>
            <Input
              placeholder="Search by name, description, owner…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-8 text-sm"
              autoComplete="off"
              aria-label="Search tools"
            />
            <Button variant="outline" size="sm" className="h-8" aria-label="Execute search">
              Search
            </Button>
          </ButtonGroup>
        </div>
      </div>

      {/* ── Table ── */}
      <div className="flex-1 overflow-auto px-6 pb-6">
        <div className="rounded-lg border border-border overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/30 hover:bg-muted/30">
                <TableHead className="pl-4 w-[220px]">
                  <button
                    onClick={() => handleSort('name')}
                    className="flex items-center gap-1.5 font-medium text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Name
                    <SortIcon field="name" />
                  </button>
                </TableHead>
                <TableHead>
                  <span className="text-xs uppercase tracking-wider font-medium text-muted-foreground">
                    Description
                  </span>
                </TableHead>
                <TableHead className="w-[110px]">
                  <button
                    onClick={() => handleSort('tool_type')}
                    className="flex items-center gap-1.5 font-medium text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Type
                    <SortIcon field="tool_type" />
                  </button>
                </TableHead>
                <TableHead className="w-[140px]">
                  <button
                    onClick={() => handleSort('owner_username')}
                    className="flex items-center gap-1.5 font-medium text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Owner
                    <SortIcon field="owner_username" />
                  </button>
                </TableHead>
                <TableHead className="w-[56px]" />
              </TableRow>
            </TableHeader>

            <TableBody>
              {filteredAndSorted.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={5} className="h-32 text-center">
                    <div className="flex flex-col items-center gap-2 text-muted-foreground">
                      <Wrench className="w-8 h-8 opacity-20" />
                      <span className="text-sm">
                        {searchQuery ? 'No tools match your search' : 'No tools yet'}
                      </span>
                      {!searchQuery && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleCreateTool}
                          className="mt-1"
                        >
                          <Plus className="w-3.5 h-3.5 mr-1.5" />
                          Create your first tool
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                filteredAndSorted.map((tool) => (
                  <TableRow key={tool.name} className="group">
                    {/* Name */}
                    <TableCell className="pl-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0">
                          {tool.tool_type === 'shared' ? (
                            <Code2 className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                          ) : (
                            <Wrench className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                          )}
                        </div>
                        <span className="font-mono text-sm font-medium">{tool.name}</span>
                      </div>
                    </TableCell>

                    {/* Description */}
                    <TableCell>
                      <span className="text-sm text-muted-foreground line-clamp-2 leading-relaxed">
                        {tool.description || (
                          <span className="italic opacity-50">No description</span>
                        )}
                      </span>
                    </TableCell>

                    {/* Type */}
                    <TableCell>
                      <Badge
                        variant={tool.tool_type === 'shared' ? 'secondary' : 'default'}
                        className="text-[11px] font-normal"
                      >
                        {tool.tool_type}
                      </Badge>
                    </TableCell>

                    {/* Owner */}
                    <TableCell>
                      <span className="text-sm text-muted-foreground">
                        {tool.owner_username ?? (
                          <span className="italic opacity-50">—</span>
                        )}
                      </span>
                    </TableCell>

                    {/* Actions */}
                    <TableCell className="pr-3">
                      {(tool.can_edit || tool.can_delete) ? (
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                              aria-label={`Options for ${tool.name}`}
                            >
                              <MoreHorizontal className="w-4 h-4" aria-hidden="true" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end">
                            {tool.can_edit && (
                              <DropdownMenuItem
                                onClick={() => void handleEditTool(tool)}
                              >
                                <Pencil className="w-3.5 h-3.5 mr-2" aria-hidden="true" />
                                Edit
                              </DropdownMenuItem>
                            )}
                            {tool.can_edit && tool.can_delete && (
                              <DropdownMenuSeparator />
                            )}
                            {tool.can_delete && (
                              <DropdownMenuItem
                                onClick={() => handleDeleteClick(tool)}
                                className="text-destructive focus:text-destructive"
                              >
                                <Trash2 className="w-3.5 h-3.5 mr-2" aria-hidden="true" />
                                Delete
                              </DropdownMenuItem>
                            )}
                          </DropdownMenuContent>
                        </DropdownMenu>
                      ) : null}
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* Footer count */}
        {filteredAndSorted.length > 0 && (
          <p className="mt-3 text-xs text-muted-foreground">
            Showing {filteredAndSorted.length} of {tools.length} tool
            {tools.length !== 1 ? 's' : ''}
            {searchQuery && ` matching "${searchQuery}"`}
          </p>
        )}
      </div>

      {/* ── Editor Dialog ── */}
      <ToolEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        mode={editorMode}
        tool={editingTool}
        initialSource={editingSource}
        onSave={handleSaveTool}
      />

      {/* ── Delete Confirmation ── */}
      <AlertDialog
        open={deleteConfirmation.isOpen}
        onOpenChange={(open) =>
          setDeleteConfirmation((prev) => ({ ...prev, isOpen: open }))
        }
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Tool</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete{' '}
              <span className="font-mono font-medium">
                {deleteConfirmation.tool?.name}
              </span>
              ? This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleteConfirmation.isDeleting}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={() => void handleConfirmDelete()}
              disabled={deleteConfirmation.isDeleting}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteConfirmation.isDeleting ? (
                <>
                  <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" aria-hidden="true" />
                  Deleting…
                </>
              ) : (
                'Delete'
              )}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default ToolsList;
