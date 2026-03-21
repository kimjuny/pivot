import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  ChevronDown,
  KeyRound,
  Pencil,
  Plus,
  Share2,
  Trash2,
  Lock,
  User as UserIcon,
  X,
} from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getSharedTools,
  getPrivateTools,
  getSharedToolSource,
  getPrivateToolSource,
  upsertPrivateTool,
  deletePrivateTool,
  type SharedTool,
  type PrivateTool,
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
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import DraggableDialog from './DraggableDialog';
import ToolEditor from './ToolEditor';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

const NEW_TOOL_TEMPLATE = `from app.orchestration.tool import tool


@tool
def my_tool(input: str) -> str:
    """Describe what your tool does.

    Args:
        input: Description of the input parameter.

    Returns:
        Description of the return value.
    """
    return input
`;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ToolRow =
  | { kind: 'shared'; tool: SharedTool }
  | { kind: 'private'; tool: PrivateTool };

// ---------------------------------------------------------------------------
// Pagination helper
// ---------------------------------------------------------------------------

/**
 * Build the page number list with ellipsis slots for a given total/current.
 * Returns either a number or the string 'ellipsis'.
 */
function buildPageList(current: number, total: number): (number | 'ellipsis')[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, i) => i + 1);
  }
  const pages: (number | 'ellipsis')[] = [1];
  if (current > 3) pages.push('ellipsis');
  const start = Math.max(2, current - 1);
  const end = Math.min(total - 1, current + 1);
  for (let i = start; i <= end; i++) pages.push(i);
  if (current < total - 2) pages.push('ellipsis');
  pages.push(total);
  return pages;
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

/**
 * Tools management page.
 *
 * Displays all shared (built-in, read-only) and private (user-owned, editable)
 * tools in a unified searchable, paginated table. Users can create, edit, and
 * delete their own private tools via a DraggableDialog with a Python editor.
 */
function ToolsPage() {
  const [sharedTools, setSharedTools] = useState<SharedTool[]>([]);
  const [privateTools, setPrivateTools] = useState<PrivateTool[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  // Search + filter state
  const [searchQuery, setSearchQuery] = useState('');
  const [kindFilter, setKindFilter] = useState<'all' | 'shared' | 'private'>('all');

  // Pagination state
  const [currentPage, setCurrentPage] = useState(1);

  // Editor dialog state
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editorSource, setEditorSource] = useState('');
  const [editorReadOnly, setEditorReadOnly] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isCreateMenuOpen, setIsCreateMenuOpen] = useState(false);

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadTools = useCallback(async () => {
    setIsLoading(true);
    try {
      const [shared, priv] = await Promise.all([getSharedTools(), getPrivateTools()]);
      setSharedTools(shared);
      setPrivateTools(priv);
    } catch {
      toast.error('Failed to load tools');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  // ---------------------------------------------------------------------------
  // Filtered + paginated rows
  // ---------------------------------------------------------------------------

  const allRows: ToolRow[] = useMemo(
    () => [
      ...sharedTools.map((t): ToolRow => ({ kind: 'shared', tool: t })),
      ...privateTools.map((t): ToolRow => ({ kind: 'private', tool: t })),
    ],
    [sharedTools, privateTools]
  );

  const filteredRows = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allRows.filter((row) => {
      if (kindFilter !== 'all' && row.kind !== kindFilter) return false;
      if (!q) return true;
      if (row.kind === 'shared') {
        return row.tool.name.toLowerCase().includes(q) || row.tool.description.toLowerCase().includes(q);
      }
      return row.tool.name.toLowerCase().includes(q);
    });
  }, [allRows, searchQuery, kindFilter]);

  // Counts for badge labels
  const sharedCount = allRows.filter(r => r.kind === 'shared').length;
  const privateCount = allRows.filter(r => r.kind === 'private').length;

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));

  // Reset to page 1 when filter changes
  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery]);

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredRows.slice(start, start + PAGE_SIZE);
  }, [filteredRows, currentPage]);

  // ---------------------------------------------------------------------------
  // Editor helpers
  // ---------------------------------------------------------------------------

  const openCreateDialog = () => {
    setEditingName(null);
    setEditorSource(NEW_TOOL_TEMPLATE);
    setEditorReadOnly(false);
    setEditorOpen(true);
  };

  const openEditDialog = useCallback(async (row: ToolRow) => {
    const toolName = row.tool.name;
    try {
      if (row.kind === 'shared') {
        const result = await getSharedToolSource(toolName);
        setEditingName(toolName);
        setEditorSource(result.source);
        setEditorReadOnly(true);
        setEditorOpen(true);
        return;
      }

      const result = await getPrivateToolSource(toolName);
      setEditingName(toolName);
      setEditorSource(result.source);
      setEditorReadOnly(false);
      setEditorOpen(true);
    } catch {
      toast.error(`Failed to load source for "${toolName}"`);
    }
  }, []);

  /**
   * Save callback – triggered by the Save button or Ctrl+S inside the editor.
   * Tool name is derived from the decorated function name when creating new.
   */
  const handleSave = useCallback(
    async (source: string) => {
      if (editorReadOnly) {
        toast.error('Built-in shared tools are read-only');
        return;
      }

      let toolName = editingName;
      if (!toolName) {
        const match = /^def\s+(\w+)\s*\(/m.exec(source);
        if (!match) {
          toast.error('Cannot determine tool name: no function definition found');
          return;
        }
        toolName = match[1];
      }

      setIsSaving(true);
      try {
        await upsertPrivateTool(toolName, source);
        toast.success(`Tool "${toolName}" saved`);
        setEditorOpen(false);
        await loadTools();
      } catch {
        toast.error(`Failed to save tool "${toolName}"`);
      } finally {
        setIsSaving(false);
      }
    },
    [editingName, editorReadOnly, loadTools]
  );

  const handleDelete = useCallback(async (toolName: string) => {
    try {
      await deletePrivateTool(toolName);
      toast.success(`Tool "${toolName}" deleted`);
      await loadTools();
    } catch {
      toast.error(`Failed to delete tool "${toolName}"`);
    }
  }, [loadTools]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <TooltipProvider>
      <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">Tools</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Built-in shared tools are read-only. Private tools are yours only.
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
                  toast.info('Shared tools are built-in and read-only');
                  setIsCreateMenuOpen(false);
                }}
                className="gap-2"
              >
                <Share2 className="w-4 h-4" />
                Shared
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => {
                  openCreateDialog();
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

      {/* Filter + search bar */}
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        {/* Badge filter tags */}
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
                <span className={kindFilter === value ? 'opacity-70' : 'text-muted-foreground'}>
                  {count}
                </span>
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

        {/* Search */}
        <ButtonGroup className="list-search-group">
          <Input
            placeholder="Search by name or description…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search tools"
            autoComplete="off"
          />
          <Button variant="outline" size="sm" aria-label="Search tools" tabIndex={-1}>
            Search
          </Button>
        </ButtonGroup>
      </div>

      {/* Tools table */}
      {isLoading ? (
        <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
          Loading tools…
        </div>
      ) : filteredRows.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          {allRows.length === 0 ? (
            <>
              <p className="text-sm">No tools found.</p>
              <Button size="sm" variant="outline" onClick={openCreateDialog}>
                <Plus className="w-4 h-4 mr-1.5" />
                Create your first tool
              </Button>
            </>
          ) : (
            <p className="text-sm">No tools match your search.</p>
          )}
        </div>
      ) : (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[200px]">Name</TableHead>
                <TableHead className="w-[80px]">Type</TableHead>
                <TableHead className="w-[120px]">Sandbox</TableHead>
                <TableHead>Description</TableHead>
                <TableHead className="w-[100px] text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pagedRows.map((row) => (
                <ToolTableRow
                  key={`${row.kind}-${row.tool.name}`}
                  row={row}
                  onEdit={openEditDialog}
                  onDelete={handleDelete}
                />
              ))}
            </TableBody>
          </Table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {filteredRows.length} tool{filteredRows.length !== 1 ? 's' : ''}
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

      {/* Editor dialog – Save button is now inside the editor status bar */}
        <DraggableDialog
          open={editorOpen}
          onOpenChange={setEditorOpen}
          title={editingName ? `${editorReadOnly ? 'View' : 'Edit'} Tool: ${editingName}` : 'New Tool'}
          size="large"
        >
          <ToolEditor
            value={editorSource}
            onChange={setEditorSource}
            onSave={editorReadOnly ? undefined : (src) => void handleSave(src)}
            isSaving={isSaving}
            readOnly={editorReadOnly}
          />
        </DraggableDialog>
      </div>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// ToolTableRow
// ---------------------------------------------------------------------------

interface ToolTableRowProps {
  row: ToolRow;
  onEdit: (row: ToolRow) => Promise<void>;
  onDelete: (name: string) => Promise<void>;
}

/**
 * Single row in the tools table.
 * Shared tools are read-only and only allow opening the source in view mode.
 */
function ToolTableRow({ row, onEdit, onDelete }: ToolTableRowProps) {
  const isShared = row.kind === 'shared';
  const name = row.tool.name;
  const description = isShared ? (row.tool).description : '—';
  const toolType = row.tool.tool_type;
  const isSandboxTool = toolType === 'sandbox';

  return (
    <TableRow>
      <TableCell className="font-mono text-xs font-medium">{name}</TableCell>

      <TableCell>
        {isShared ? (
          <Badge
            variant="secondary"
            className="flex w-fit shrink-0 items-center gap-1 whitespace-nowrap px-2.5 py-0.5 text-xs transition-colors"
          >
            <Lock className="w-2.5 h-2.5" />
            Shared
          </Badge>
        ) : (
          <Badge
            variant="secondary"
            className="flex w-fit shrink-0 items-center gap-1 whitespace-nowrap px-2.5 py-0.5 text-xs transition-colors"
          >
            <UserIcon className="w-2.5 h-2.5" />
            Private
          </Badge>
        )}
      </TableCell>

      <TableCell>
        <Badge
          variant="secondary"
          className="w-fit shrink-0 whitespace-nowrap px-2.5 py-0.5 text-xs transition-colors"
        >
          {isSandboxTool ? 'Yes' : 'No'}
        </Badge>
      </TableCell>

      <TableCell className="max-w-xs">
        {description === '—' ? (
          <span className="text-sm text-muted-foreground">{description}</span>
        ) : (
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="text-sm text-muted-foreground truncate cursor-help">
                {description}
              </div>
            </TooltipTrigger>
            <TooltipContent side="top" className="max-w-md whitespace-pre-wrap break-words">
              {description}
            </TooltipContent>
          </Tooltip>
        )}
      </TableCell>

      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={`Edit tool ${name}`}
            onClick={() => void onEdit(row)}
          >
            <Pencil className="w-3.5 h-3.5" />
          </Button>
          {!isShared && (
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7 text-destructive hover:text-destructive"
              aria-label={`Delete tool ${name}`}
              onClick={() => void onDelete(name)}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

export default ToolsPage;
