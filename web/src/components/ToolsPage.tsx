import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ExternalLink,
  Pencil,
  Plus,
  Search,
  SlidersHorizontal,
  Trash2,
  Wrench,
  X,
} from 'lucide-react';
import { toast } from 'sonner';

import { CenteredLoadingIndicator } from "@/components/CenteredLoadingIndicator";
import ResourceAuthTab from '@/components/ResourceAuthTab';
import { Badge } from '@/components/ui/badge';
import {
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Pagination,
  PaginationContent,
  PaginationEllipsis,
  PaginationItem,
  PaginationLink,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import {
  deleteToolSource,
  getManageableTools,
  getToolAccess,
  getToolAccessOptions,
  getToolCreateAccessOptions,
  getToolSource,
  updateToolAccess,
  updateToolSource,
  type ManagedTool,
  type ToolInventorySourceType,
  type ToolAccess,
  type ToolAccessOptions,
  type ToolSourceType,
} from '../utils/api';
import DraggableDialog from './DraggableDialog';
import ToolEditor from './ToolEditor';

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

const EMPTY_TOOL_ACCESS: ToolAccess = {
  tool_name: '',
  source_type: 'manual',
  read_only: false,
  use_scope: 'all',
  use_user_ids: [],
  use_group_ids: [],
  edit_user_ids: [],
  edit_group_ids: [],
};

const TOOL_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;

type ToolRow = { sourceType: ToolInventorySourceType; tool: ManagedTool };

type ToolDialogTab = 'general' | 'auth';
type SourceFilter = 'all' | 'builtin' | 'builder' | 'extension';

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

function normalizeToolName(raw: string): string {
  return raw.trim();
}

function isValidToolName(name: string): boolean {
  return TOOL_NAME_PATTERN.test(name);
}

function getToolNameError(name: string): string | null {
  if (!name.trim()) {
    return 'Tool name is required.';
  }
  if (!isValidToolName(name.trim())) {
    return 'Use a Python function name: letters, numbers, and underscores; cannot start with a number.';
  }
  return null;
}

function getToolFileNameLabel(name: string): string {
  const normalizedName = normalizeToolName(name);
  return isValidToolName(normalizedName) ? `${normalizedName}.py` : 'tool.py';
}

function getToolSourceLabel(sourceCategory: ManagedTool['source_category']): string {
  if (sourceCategory === 'builtin') {
    return 'Built-in';
  }
  if (sourceCategory === 'extension') {
    return 'Extension';
  }
  return 'Builder';
}

function getExtensionDetailPath(packageId: string | null | undefined): string | null {
  if (!packageId || !packageId.startsWith('@')) {
    return null;
  }

  const trimmed = packageId.slice(1);
  const separatorIndex = trimmed.indexOf('/');
  if (separatorIndex <= 0 || separatorIndex === trimmed.length - 1) {
    return null;
  }

  return `/studio/assets/extensions/${trimmed.slice(0, separatorIndex)}/${trimmed.slice(separatorIndex + 1)}`;
}

function extractFunctionName(source: string): string | null {
  return /^def\s+(\w+)\s*\(/m.exec(source)?.[1] ?? null;
}

function ToolsPage() {
  const navigate = useNavigate();
  const [tools, setTools] = useState<ManagedTool[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [currentPage, setCurrentPage] = useState(1);

  const [editorOpen, setEditorOpen] = useState(false);
  const [editorSaveMode, setEditorSaveMode] = useState<'direct' | 'dialog'>('direct');
  const [editingName, setEditingName] = useState<string | null>(null);
  const [editingSourceType, setEditingSourceType] = useState<ToolSourceType>('manual');
  const [editorSource, setEditorSource] = useState('');
  const [editorReadOnly, setEditorReadOnly] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const [toolDialogOpen, setToolDialogOpen] = useState(false);
  const [toolDialogMode, setToolDialogMode] = useState<'create' | 'edit'>('create');
  const [toolDialogTab, setToolDialogTab] = useState<ToolDialogTab>('general');
  const [toolDialogSourceType, setToolDialogSourceType] =
    useState<ToolSourceType>('manual');
  const [toolDialogReadOnly, setToolDialogReadOnly] = useState(false);
  const [toolDialogName, setToolDialogName] = useState('my_tool');
  const [toolDialogSource, setToolDialogSource] = useState(NEW_TOOL_TEMPLATE);
  const [toolDialogSourceDirty, setToolDialogSourceDirty] = useState(false);
  const [toolAccess, setToolAccess] = useState<ToolAccess>(EMPTY_TOOL_ACCESS);
  const [toolAccessUsers, setToolAccessUsers] =
    useState<ToolAccessOptions['users']>([]);
  const [toolAccessGroups, setToolAccessGroups] =
    useState<ToolAccessOptions['groups']>([]);
  const [toolAccessLoading, setToolAccessLoading] = useState(false);
  const toolDialogNameError =
    toolDialogSourceType === 'builtin' ? null : getToolNameError(toolDialogName);
  const toolDialogFileName = getToolFileNameLabel(toolDialogName);

  const loadTools = useCallback(async () => {
    setIsLoading(true);
    try {
      setTools(await getManageableTools());
    } catch {
      toast.error('Failed to load tools');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTools();
  }, [loadTools]);

  const allRows: ToolRow[] = useMemo(
    () => [
      ...tools.map((tool): ToolRow => ({ sourceType: tool.source_type, tool })),
    ],
    [tools],
  );

  const sourceCounts = useMemo(
    () => ({
      all: allRows.length,
      builtin: allRows.filter((row) => row.tool.source_category === 'builtin').length,
      builder: allRows.filter((row) => row.tool.source_category === 'builder').length,
      extension: allRows.filter((row) => row.tool.source_category === 'extension').length,
    }),
    [allRows],
  );

  const filteredRows = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return allRows.filter((row) => {
      if (sourceFilter !== 'all' && row.tool.source_category !== sourceFilter) {
        return false;
      }
      if (!q) return true;
      return (
        row.tool.name.toLowerCase().includes(q) ||
        row.tool.description.toLowerCase().includes(q) ||
        getToolSourceLabel(row.tool.source_category).toLowerCase().includes(q) ||
        (row.tool.from_label ?? '').toLowerCase().includes(q)
      );
    });
  }, [allRows, searchQuery, sourceFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, sourceFilter]);

  const pagedRows = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredRows.slice(start, start + PAGE_SIZE);
  }, [filteredRows, currentPage]);

  const openCreateDialog = async () => {
    setToolDialogMode('create');
    setToolDialogTab('general');
    setToolDialogSourceType('manual');
    setToolDialogReadOnly(false);
    setToolDialogName('my_tool');
    setToolDialogSource(NEW_TOOL_TEMPLATE);
    setToolDialogSourceDirty(false);
    setToolAccess(EMPTY_TOOL_ACCESS);
    setToolDialogOpen(true);
    setToolAccessLoading(true);
    try {
      const options = await getToolCreateAccessOptions();
      setToolAccessUsers(options.users);
      setToolAccessGroups(options.groups);
    } catch {
      toast.error('Failed to load tool auth options');
    } finally {
      setToolAccessLoading(false);
    }
  };

  const openToolDialog = useCallback(async (row: ToolRow) => {
    if (row.sourceType === 'extension') {
      return;
    }
    const toolName = row.tool.name;
    setToolDialogMode('edit');
    setToolDialogTab('general');
    setToolDialogSourceType(row.sourceType);
    setToolDialogReadOnly(row.tool.read_only);
    setToolDialogName(toolName);
    setToolDialogSource('');
    setToolDialogSourceDirty(false);
    setToolDialogOpen(true);
    setToolAccessLoading(true);
    try {
      const access = await getToolAccess(row.sourceType, toolName);
      const options = row.tool.read_only
        ? { users: [], groups: [] }
        : await getToolAccessOptions(row.sourceType, toolName);
      const source = await getToolSource(row.sourceType, toolName);
      setToolAccess(access);
      setToolAccessUsers(options.users);
      setToolAccessGroups(options.groups);
      setToolDialogSource(source.source);
    } catch {
      toast.error(`Failed to load tool "${toolName}"`);
      setToolDialogOpen(false);
    } finally {
      setToolAccessLoading(false);
    }
  }, []);

  const openSourceEditor = useCallback(async (row: ToolRow) => {
    if (row.sourceType === 'extension') {
      return;
    }
    const toolName = row.tool.name;
    try {
      const result = await getToolSource(row.sourceType, toolName);
      setEditorSaveMode('direct');
      setEditingName(toolName);
      setEditingSourceType(row.sourceType);
      setEditorSource(result.source);
      setEditorReadOnly(row.tool.read_only);
      setEditorOpen(true);
    } catch {
      toast.error(`Failed to load source for "${toolName}"`);
    }
  }, []);

  const openDialogSourceEditor = () => {
    setEditorSaveMode('dialog');
    setEditingName(
      isValidToolName(normalizeToolName(toolDialogName))
        ? normalizeToolName(toolDialogName)
        : null,
    );
    setEditingSourceType(toolDialogSourceType);
    setEditorSource(toolDialogSource);
    setEditorReadOnly(toolDialogReadOnly);
    setToolDialogOpen(false);
    setEditorOpen(true);
  };

  const handleEditorOpenChange = useCallback((open: boolean) => {
    setEditorOpen(open);
    if (!open && editorSaveMode === 'dialog') {
      setToolDialogOpen(true);
    }
  }, [editorSaveMode]);

  const handleDirectSourceSave = useCallback(
    async (source: string) => {
      if (editorReadOnly || editingSourceType === 'builtin') {
        toast.error('Built-in tools are read-only');
        return;
      }

      const targetName = normalizeToolName(editingName ?? extractFunctionName(source) ?? '');
      const nameError = getToolNameError(targetName);
      if (nameError) {
        toast.error(nameError);
        return;
      }

      setIsSaving(true);
      try {
      await updateToolSource(editingSourceType, targetName, source);
        toast.success(`Tool "${targetName}" saved`);
        setEditorOpen(false);
        await loadTools();
      } catch {
        toast.error(`Failed to save tool "${targetName}"`);
      } finally {
        setIsSaving(false);
      }
    },
    [editingName, editingSourceType, editorReadOnly, loadTools],
  );

  const handleEditorSave = useCallback(
    async (source: string) => {
      if (editorSaveMode === 'dialog') {
        setToolDialogSource(source);
        setToolDialogSourceDirty(true);
        if (toolDialogMode === 'create') {
          setToolDialogName(normalizeToolName(extractFunctionName(source) ?? toolDialogName));
        }
        setEditorOpen(false);
        setToolDialogOpen(true);
        return;
      }
      await handleDirectSourceSave(source);
    },
    [editorSaveMode, handleDirectSourceSave, toolDialogMode, toolDialogName],
  );

  const handleToolDialogSave = useCallback(async () => {
    if (toolDialogReadOnly) {
      toast.error('This tool is read-only');
      return;
    }

    const targetName = normalizeToolName(toolDialogName);
    const nameError = getToolNameError(targetName);
    if (nameError) {
      toast.error(nameError);
      return;
    }
    if (toolDialogMode === 'create' || toolDialogSourceDirty) {
      const sourceFunctionName = extractFunctionName(toolDialogSource);
      if (sourceFunctionName !== targetName) {
        toast.error(`Tool source must define function "${targetName}".`);
        return;
      }
    }

    setIsSaving(true);
    try {
      if (toolDialogMode === 'create') {
        await updateToolSource('manual', targetName, toolDialogSource);
      } else if (toolDialogSourceDirty) {
        await updateToolSource(toolDialogSourceType, targetName, toolDialogSource);
      }
      await updateToolAccess(toolDialogSourceType, targetName, {
        use_scope: toolAccess.use_scope,
        use_user_ids: toolAccess.use_user_ids,
        use_group_ids: toolAccess.use_group_ids,
        edit_user_ids: toolAccess.edit_user_ids,
        edit_group_ids: toolAccess.edit_group_ids,
      });
      toast.success(`Tool "${targetName}" saved`);
      setToolDialogOpen(false);
      await loadTools();
    } catch {
      toast.error(`Failed to save tool "${targetName}"`);
    } finally {
      setIsSaving(false);
    }
  }, [
    loadTools,
    toolAccess,
    toolDialogMode,
    toolDialogName,
    toolDialogReadOnly,
    toolDialogSource,
    toolDialogSourceDirty,
    toolDialogSourceType,
  ]);

  const handleDelete = useCallback(async (row: ToolRow) => {
    if (row.sourceType === 'extension') {
      return;
    }
    if (row.sourceType === 'builtin') {
      toast.error('Built-in tools are read-only');
      return;
    }
    try {
      await deleteToolSource(row.sourceType, row.tool.name);
      toast.success(`Tool "${row.tool.name}" deleted`);
      await loadTools();
    } catch {
      toast.error(`Failed to delete tool "${row.tool.name}"`);
    }
  }, [loadTools]);

  const openOwningExtension = useCallback((row: ToolRow) => {
    const detailPath = getExtensionDetailPath(row.tool.extension_package_id);
    if (!detailPath) {
      toast.error('Extension detail page is unavailable for this tool.');
      return;
    }
    navigate(detailPath);
  }, [navigate]);

  const isBuiltinDialog = toolDialogSourceType === 'builtin';
  const isReadOnlyDialog = toolDialogReadOnly || isBuiltinDialog;
  const toolDialogTabIndex = toolDialogTab === 'auth' ? 1 : 0;

  return (
    <TooltipProvider>
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="mb-6 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-foreground">Tools</h1>
            <p className="mt-0.5 text-sm text-muted-foreground">
              Browse available tools across built-in, builder, and extension sources, and manage editable ones here.
            </p>
          </div>
          <Button
            size="sm"
            className="flex items-center gap-1.5"
            onClick={() => void openCreateDialog()}
          >
            <Plus className="h-4 w-4" />
            New
          </Button>
        </div>

        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-1.5 flex-wrap">
            {(
              [
                { value: 'all', label: 'All', count: sourceCounts.all },
                { value: 'builtin', label: 'Built-in', count: sourceCounts.builtin },
                { value: 'builder', label: 'Builder', count: sourceCounts.builder },
                { value: 'extension', label: 'Extension', count: sourceCounts.extension },
              ] as const
            ).map(({ value, label, count }) => (
              <button
                key={value}
                onClick={() => setSourceFilter(value)}
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
              >
                <Badge
                  variant={sourceFilter === value ? 'default' : 'outline'}
                  className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                    sourceFilter === value ? 'list-filter-badge-active' : ''
                  }`}
                >
                  {label}
                  <span className={sourceFilter === value ? 'opacity-70' : 'text-muted-foreground'}>
                    {count}
                  </span>
                </Badge>
              </button>
            ))}
            {sourceFilter !== 'all' && (
              <button
                onClick={() => setSourceFilter('all')}
                className="text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Clear source filter"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          <ButtonGroup className="list-search-group">
            <Input
              placeholder="Search by name, description, source, or origin…"
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              aria-label="Search tools"
              autoComplete="off"
            />
            <Button variant="outline" size="sm" aria-label="Search tools" tabIndex={-1}>
              <Search className="w-4 h-4" />
              Search
            </Button>
          </ButtonGroup>
        </div>

        {isLoading ? (
          <CenteredLoadingIndicator label="Loading tools…" className="min-h-[50vh]" />
        ) : filteredRows.length === 0 ? (
          <Empty>
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <Wrench className="size-6" />
              </EmptyMedia>
              {allRows.length === 0 ? (
                <>
                  <EmptyTitle>No tools yet</EmptyTitle>
                  <EmptyDescription>
                    Create your first tool to get started.
                  </EmptyDescription>
                </>
              ) : (
                <>
                  <EmptyTitle>No tools found</EmptyTitle>
                  <EmptyDescription>
                    No tools match your search.
                  </EmptyDescription>
                </>
              )}
            </EmptyHeader>
            {allRows.length === 0 ? (
              <EmptyContent>
                <Button size="sm" variant="outline" onClick={() => void openCreateDialog()}>
                  Create Tool
                </Button>
              </EmptyContent>
            ) : null}
          </Empty>
        ) : (
          <>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[220px]">Name</TableHead>
                  <TableHead className="w-[110px]">Source</TableHead>
                  <TableHead className="w-[220px]">From</TableHead>
                  <TableHead className="w-[120px]">Sandbox</TableHead>
                  <TableHead>Description</TableHead>
                  <TableHead className="w-[120px] text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pagedRows.map((row) => {
                  const description = row.tool.description || '—';
                  return (
                    <TableRow key={`${row.sourceType}-${row.tool.name}`}>
                      <TableCell className="font-mono text-xs font-medium">
                        {row.tool.name}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {getToolSourceLabel(row.tool.source_category)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {row.tool.from_label ?? '—'}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {row.tool.tool_type === 'sandbox' ? 'Yes' : 'No'}
                      </TableCell>
                      <TableCell className="max-w-xs">
                        {description === '—' ? (
                          <span className="text-sm text-muted-foreground">—</span>
                        ) : (
                          <Tooltip>
                            <TooltipTrigger asChild>
                              <div className="cursor-help truncate text-sm text-muted-foreground">
                                {description}
                              </div>
                            </TooltipTrigger>
                            <TooltipContent
                              side="top"
                              className="max-w-md whitespace-pre-wrap break-words"
                            >
                              {description}
                            </TooltipContent>
                          </Tooltip>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          {row.sourceType === 'extension' ? (
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-7 w-7"
                              aria-label={`Open owning extension for ${row.tool.name}`}
                              onClick={() => openOwningExtension(row)}
                            >
                              <ExternalLink className="h-3.5 w-3.5" />
                            </Button>
                          ) : (
                            <>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                aria-label={`Configure tool ${row.tool.name}`}
                                onClick={() => void openToolDialog(row)}
                              >
                                <SlidersHorizontal className="h-3.5 w-3.5" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                aria-label={`${row.sourceType === 'builtin' ? 'View' : 'Edit'} tool.py for ${row.tool.name}`}
                                onClick={() => void openSourceEditor(row)}
                              >
                                <Pencil className="h-3.5 w-3.5" />
                              </Button>
                              {!row.tool.read_only ? (
                                <Button
                                  variant="ghost"
                                  size="icon"
                                  className="h-7 w-7 text-destructive hover:text-destructive"
                                  aria-label={`Delete tool ${row.tool.name}`}
                                  onClick={() => void handleDelete(row)}
                                >
                                  <Trash2 className="h-3.5 w-3.5" />
                                </Button>
                              ) : null}
                            </>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>

            {totalPages > 1 && (
              <div className="mt-4 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  {filteredRows.length} tool{filteredRows.length !== 1 ? 's' : ''}
                  {searchQuery ? ' found' : ' total'}
                </span>
                <Pagination className="mx-0 w-auto justify-end">
                  <PaginationContent>
                    <PaginationItem>
                      <PaginationPrevious
                        href="#"
                        onClick={(event) => {
                          event.preventDefault();
                          if (currentPage > 1) setCurrentPage((page) => page - 1);
                        }}
                        className={currentPage === 1 ? 'pointer-events-none opacity-50' : ''}
                      />
                    </PaginationItem>

                    {buildPageList(currentPage, totalPages).map((page, index) =>
                      page === 'ellipsis' ? (
                        <PaginationItem key={`ellipsis-${index}`}>
                          <PaginationEllipsis />
                        </PaginationItem>
                      ) : (
                        <PaginationItem key={page}>
                          <PaginationLink
                            href="#"
                            isActive={page === currentPage}
                            onClick={(event) => {
                              event.preventDefault();
                              setCurrentPage(page);
                            }}
                          >
                            {page}
                          </PaginationLink>
                        </PaginationItem>
                      ),
                    )}

                    <PaginationItem>
                      <PaginationNext
                        href="#"
                        onClick={(event) => {
                          event.preventDefault();
                          if (currentPage < totalPages) setCurrentPage((page) => page + 1);
                        }}
                        className={
                          currentPage === totalPages ? 'pointer-events-none opacity-50' : ''
                        }
                      />
                    </PaginationItem>
                  </PaginationContent>
                </Pagination>
              </div>
            )}
          </>
        )}

        <Dialog open={toolDialogOpen} onOpenChange={setToolDialogOpen}>
          <DialogContent className="flex max-h-[90vh] min-h-0 flex-col overflow-hidden sm:max-w-[720px]">
            <DialogHeader>
              <DialogTitle>
                {toolDialogMode === 'create' ? 'New Tool' : 'Edit Tool'}
              </DialogTitle>
            </DialogHeader>
            <Tabs
              value={toolDialogTab}
              onValueChange={(value) => setToolDialogTab(value as ToolDialogTab)}
              orientation="vertical"
              className="flex min-h-0 flex-1 gap-3 py-2"
            >
              <TabsList className="relative flex h-[560px] max-h-[calc(90vh-150px)] w-24 shrink-0 flex-col items-stretch justify-start gap-1 bg-transparent p-0">
                <span
                  className="absolute left-0 top-1.5 h-6 w-0.5 bg-foreground transition-transform duration-200 ease-out"
                  style={{
                    transform: `translateY(${toolDialogTabIndex * 40}px)`,
                  }}
                  aria-hidden="true"
                />
                <TabsTrigger
                  value="general"
                  className="h-9 justify-start rounded-none bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                >
                  General
                </TabsTrigger>
                <TabsTrigger
                  value="auth"
                  className="h-9 justify-start rounded-none bg-transparent px-3 data-[state=active]:bg-transparent data-[state=active]:shadow-none"
                >
                  Auth
                </TabsTrigger>
              </TabsList>

              <div className="min-w-0 flex-1">
                <TabsContent
                  value="general"
                  className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
                >
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="tool-name">
                        Name <span className="text-destructive">*</span>
                      </Label>
                      <Input
                        id="tool-name"
                        value={toolDialogName}
                        onChange={(event) => setToolDialogName(event.target.value)}
                        disabled={toolDialogMode === 'edit' || isSaving}
                        aria-invalid={toolDialogNameError ? true : undefined}
                        autoComplete="off"
                      />
                      {toolDialogNameError ? (
                        <p className="text-xs text-destructive">{toolDialogNameError}</p>
                      ) : (
                        <p className="text-xs text-muted-foreground">
                          This name is also the .py filename and the decorated Python
                          function name.
                        </p>
                      )}
                    </div>
                    <div className="flex items-center justify-between gap-3 rounded-md border px-3 py-2">
                      <div className="min-w-0">
                        <div className="text-sm font-medium">
                          {isReadOnlyDialog
                            ? `View ${toolDialogFileName} file`
                            : `Edit ${toolDialogFileName} file`}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          Open the Python source editor for this tool.
                        </div>
                      </div>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={openDialogSourceEditor}
                        disabled={isSaving}
                      >
                        {isReadOnlyDialog ? 'View' : 'Edit'}
                      </Button>
                    </div>
                  </div>
                </TabsContent>
                <TabsContent
                  value="auth"
                  className="mt-0 h-[560px] max-h-[calc(90vh-150px)] overflow-y-auto pr-2"
                >
                  <ResourceAuthTab
                    access={toolAccess}
                    users={toolAccessUsers}
                    groups={toolAccessGroups}
                    loading={toolAccessLoading}
                    disabled={isReadOnlyDialog || isSaving}
                    onAccessChange={(access) =>
                      setToolAccess((current) => ({ ...current, ...access }))
                    }
                  />
                </TabsContent>
              </div>
            </Tabs>
            <DialogFooter>
              <Button
                variant="outline"
                type="button"
                onClick={() => setToolDialogOpen(false)}
                disabled={isSaving}
              >
                {isReadOnlyDialog ? 'Close' : 'Cancel'}
              </Button>
              {!isReadOnlyDialog ? (
                <Button
                  type="button"
                  onClick={() => void handleToolDialogSave()}
                  disabled={isSaving || Boolean(toolDialogNameError)}
                >
                  {isSaving ? 'Saving…' : 'Save'}
                </Button>
              ) : null}
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <DraggableDialog
          open={editorOpen}
          onOpenChange={handleEditorOpenChange}
          title={
            editingName
              ? `${editorReadOnly ? 'View' : 'Edit'} tool.py: ${editingName}`
              : 'Edit tool.py'
          }
          size="large"
        >
          <ToolEditor
            value={editorSource}
            onChange={setEditorSource}
            onSave={editorReadOnly ? undefined : (source) => void handleEditorSave(source)}
            isSaving={isSaving}
            readOnly={editorReadOnly}
          />
        </DraggableDialog>
      </div>
    </TooltipProvider>
  );
}

export default ToolsPage;
