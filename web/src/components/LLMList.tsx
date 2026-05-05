import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { Plus, Pencil, Trash2, Server, X, Download, Upload, Copy } from "@/lib/lucide";
import { toast } from 'sonner';
import {
  getLLMs,
  deleteLLM,
  updateLLM,
  updateLLMAccess,
  createLLM,
  type LLMAccess,
} from '../utils/api';
import type { LLM } from '../types';
import LLMModal from './LLMModal';
import ConfirmationModal from './ConfirmationModal';
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
import { CenteredLoadingIndicator } from '@/components/CenteredLoadingIndicator';
import { LLMBrandAvatar } from '@/components/LLMBrandAvatar';
import { formatThinkingPolicyLabel } from '@/utils/llmThinking';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

const PROTOCOL_LABELS: Record<string, string> = {
  openai_completion_llm: 'Completion',
  openai_response_llm: 'Response',
  anthropic_compatible: 'Anthropic',
};

function formatProtocolLabel(protocol: string): string {
  return PROTOCOL_LABELS[protocol] ?? protocol;
}

function formatMaxContext(maxContext: number): string {
  if (maxContext >= 1_000_000) {
    return `${Math.round(maxContext / 1_000_000)}M`;
  }
  if (maxContext >= 1024 && maxContext % 1024 === 0) {
    return `${Math.round(maxContext / 1024)}K`;
  }
  if (maxContext >= 1000) {
    return `${Math.round(maxContext / 1000)}K`;
  }
  return `${maxContext}`;
}

function formatCachePolicyLabel(cachePolicy: string): string {
  const cachePolicyLabels: Record<string, string> = {
    'qwen-completion-block-cache': 'Cache Control',
    'kimi-completion-prompt-cache-key': 'Cache Control',
    'openai-response-prompt-cache-key': 'Cache Control',
    'doubao-response-previous-id': 'Cache Control',
    'anthropic-auto-cache': 'Cache Control',
    'anthropic-block-cache': 'Cache Control',
  };

  return cachePolicyLabels[cachePolicy] ?? cachePolicy;
}

// ---------------------------------------------------------------------------
// Pagination helper
// ---------------------------------------------------------------------------

/**
 * Build the page number list with ellipsis slots for a given total/current.
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
 * LLM configuration list page.
 *
 * Displays all LLM configurations in a searchable, paginated table.
 * Supports create, edit, and delete operations via modal dialogs.
 */
function LLMList() {
  const [llms, setLLMs] = useState<LLM[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copyingLLMId, setCopyingLLMId] = useState<number | null>(null);

  // Modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editingLLM, setEditingLLM] = useState<LLM | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    llm: LLM | null;
  }>({ isOpen: false, llm: null });

  // Search + filter + pagination state
  const [searchQuery, setSearchQuery] = useState('');
  const [protocolFilter, setProtocolFilter] = useState<string>('all');
  const [currentPage, setCurrentPage] = useState(1);

  // Import state
  const [isImporting, setIsImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // ---------------------------------------------------------------------------
  // Data loading
  // ---------------------------------------------------------------------------

  const loadLLMs = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getLLMs();
      setLLMs(data);
    } catch (err) {
      const e = err as Error;
      setError(e.message || 'Failed to load LLMs');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadLLMs();
  }, [loadLLMs]);

  // ---------------------------------------------------------------------------
  // Filtered + paginated rows
  // ---------------------------------------------------------------------------

  // Unique protocol values for badge filters
  const protocols = useMemo(
    () => Array.from(new Set(llms.map(l => l.protocol).filter(Boolean))).sort(),
    [llms]
  );

  const filteredLLMs = useMemo(() => {
    const q = searchQuery.toLowerCase().trim();
    return llms.filter((llm) => {
      if (protocolFilter !== 'all' && llm.protocol !== protocolFilter) return false;
      if (!q) return true;
      return (
        llm.name.toLowerCase().includes(q) ||
        llm.model.toLowerCase().includes(q) ||
        llm.endpoint.toLowerCase().includes(q) ||
        llm.protocol.toLowerCase().includes(q)
      );
    });
  }, [llms, searchQuery, protocolFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredLLMs.length / PAGE_SIZE));

  useEffect(() => {
    setCurrentPage(1);
  }, [searchQuery, protocolFilter]);

  const pagedLLMs = useMemo(() => {
    const start = (currentPage - 1) * PAGE_SIZE;
    return filteredLLMs.slice(start, start + PAGE_SIZE);
  }, [filteredLLMs, currentPage]);

  // ---------------------------------------------------------------------------
  // CRUD handlers
  // ---------------------------------------------------------------------------

  const handleCreate = () => {
    setModalMode('create');
    setEditingLLM(null);
    setIsModalOpen(true);
  };

  const handleEdit = useCallback((llm: LLM) => {
    setModalMode('edit');
    setEditingLLM(llm);
    setIsModalOpen(true);
  }, []);

  const handleDelete = useCallback((llm: LLM) => {
    setDeleteConfirmation({ isOpen: true, llm });
  }, []);

  const handleCopy = useCallback(async (llm: LLM) => {
    const escapedName = llm.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const copyNamePattern = new RegExp(`^${escapedName}_copy_(\\d+)$`);
    const nextIndex = llms.reduce((max, item) => {
      const match = item.name.match(copyNamePattern);
      if (!match) return max;
      const index = Number.parseInt(match[1], 10);
      return Number.isNaN(index) ? max : Math.max(max, index);
    }, 0) + 1;

    setCopyingLLMId(llm.id);
    try {
      await createLLM({
        name: `${llm.name}_copy_${nextIndex}`,
        endpoint: llm.endpoint,
        model: llm.model,
        api_key: llm.api_key,
        protocol: llm.protocol,
        cache_policy: llm.cache_policy,
        thinking_policy: llm.thinking_policy,
        thinking_effort: llm.thinking_effort,
        thinking_budget_tokens: llm.thinking_budget_tokens,
        streaming: llm.streaming,
        image_input: llm.image_input,
        image_output: llm.image_output,
        max_context: llm.max_context,
        extra_config: llm.extra_config,
      });
      toast.success('LLM copied');
      await loadLLMs();
    } catch (err) {
      const e = err as Error;
      toast.error(`Failed to copy: ${e.message}`);
    } finally {
      setCopyingLLMId(null);
    }
  }, [llms, loadLLMs]);

  const confirmDelete = async () => {
    if (!deleteConfirmation.llm) return;
    try {
      await deleteLLM(deleteConfirmation.llm.id);
      setDeleteConfirmation({ isOpen: false, llm: null });
      toast.success('LLM deleted');
      await loadLLMs();
    } catch (err) {
      const e = err as Error;
      toast.error(`Failed to delete: ${e.message}`);
      setDeleteConfirmation({ isOpen: false, llm: null });
    }
  };

  // ---------------------------------------------------------------------------
  // Export
  // ---------------------------------------------------------------------------

  /**
   * Serialise all LLMs (stripping server-generated fields id / created_at / updated_at)
   * and trigger a JSON file download in the browser.
   */
  const handleExport = () => {
    const exportable = llms.map(({ id: _id, created_at: _ca, updated_at: _ua, ...rest }) => rest);
    const json = JSON.stringify(exportable, null, 2);
    const blob = new Blob([json], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pivot-llms-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${llms.length} LLM${llms.length !== 1 ? 's' : ''}`);
  };

  // ---------------------------------------------------------------------------
  // Import
  // ---------------------------------------------------------------------------

  /**
   * Read a JSON file, validate the shape, then create each entry via the API.
   * Duplicate names (server-side 400) are skipped with a warning.
   */
  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset so the same file can be re-selected after a failed import
    e.target.value = '';

    let parsed: unknown;
    try {
      parsed = JSON.parse(await file.text());
    } catch {
      toast.error('Invalid JSON file');
      return;
    }

    if (!Array.isArray(parsed)) {
      toast.error('Expected a JSON array of LLM objects');
      return;
    }

    setIsImporting(true);
    let created = 0;
    let skipped = 0;

    for (const item of parsed as Record<string, unknown>[]) {
      if (typeof item.name !== 'string' || typeof item.endpoint !== 'string') {
        skipped++;
        continue;
      }
      try {
        await createLLM({
          name: item.name,
          endpoint: item.endpoint,
          model: (item.model as string) ?? '',
          api_key: (item.api_key as string) ?? '',
          protocol: (item.protocol as string) ?? 'openai_completion_llm',
          cache_policy: (item.cache_policy as string) ?? 'none',
          thinking_policy: (item.thinking_policy as string) ?? 'auto',
          thinking_effort: (item.thinking_effort as string) ?? null,
          thinking_budget_tokens:
            (item.thinking_budget_tokens as number | null) ?? null,
          streaming: (item.streaming as boolean) ?? true,
          image_input: (item.image_input as boolean) ?? false,
          image_output: (item.image_output as boolean) ?? false,
          max_context: (item.max_context as number) ?? 128000,
          extra_config: (item.extra_config as string) ?? '',
        });
        created++;
      } catch {
        // Name collision or validation error — skip silently and count
        skipped++;
      }
    }

    setIsImporting(false);
    await loadLLMs();

    if (created > 0 && skipped === 0) {
      toast.success(`Imported ${created} LLM${created !== 1 ? 's' : ''}`);
    } else if (created > 0) {
      toast.success(`Imported ${created}, skipped ${skipped} (duplicates or invalid)`);
    } else {
      toast.error('No LLMs were imported. Check the file format.');
    }
  };

  const handleModalSave = async (llmData: {
    name: string;
    endpoint: string;
    model: string;
    api_key: string;
    protocol: string;
    cache_policy: string;
    thinking_policy: string;
    thinking_effort?: string | null;
    thinking_budget_tokens?: number | null;
    streaming: boolean;
    image_input: boolean;
    image_output: boolean;
    max_context: number;
    extra_config: string;
  }, access: LLMAccess) => {
    if (modalMode === 'create') {
      await createLLM({
        ...llmData,
        use_scope: access.use_scope,
        use_user_ids: access.use_user_ids,
        use_group_ids: access.use_group_ids,
        edit_user_ids: access.edit_user_ids,
        edit_group_ids: access.edit_group_ids,
      });
      toast.success('LLM created');
    } else if (modalMode === 'edit' && editingLLM) {
      await updateLLM(editingLLM.id, llmData);
      await updateLLMAccess(editingLLM.id, access);
      toast.success('LLM updated');
    }
    await loadLLMs();
  };

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  if (isLoading) {
    return <CenteredLoadingIndicator className="h-screen" label="Loading models" />;
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-background">
        <div className="text-xl text-destructive mb-4 font-medium">Error: {error}</div>
        <Button onClick={() => void loadLLMs()}>Retry</Button>
      </div>
    );
  }

  return (
    <div className="max-w-5xl mx-auto px-6 py-8">
      {/* Page header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-foreground">LLMs</h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Manage LLM configurations used by your agents.
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Export */}
          <Button
            size="sm"
            variant="outline"
            onClick={handleExport}
            disabled={llms.length === 0}
            className="flex items-center gap-1.5"
            aria-label="Export all LLMs as JSON"
          >
            <Download className="w-4 h-4" />
            Export
          </Button>

          {/* Import — hidden file input triggered by button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={e => void handleImportFile(e)}
            aria-label="Import LLMs from JSON file"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInputRef.current?.click()}
            disabled={isImporting}
            className="flex items-center gap-1.5"
          >
            <Upload className="w-4 h-4" />
            {isImporting ? 'Importing…' : 'Import'}
          </Button>

          <Button size="sm" onClick={handleCreate} className="flex items-center gap-1.5">
            <Plus className="w-4 h-4" />
            New
          </Button>
        </div>
      </div>

      {/* Filter + search bar */}
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        {/* Protocol badge filters */}
        <div className="flex items-center gap-1.5 flex-shrink-0 flex-wrap">
          <button
            onClick={() => setProtocolFilter('all')}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
          >
            <Badge
              variant={protocolFilter === 'all' ? 'default' : 'outline'}
              className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                protocolFilter === 'all' ? 'list-filter-badge-active' : ''
              }`}
            >
              All
              <span className={protocolFilter === 'all' ? 'opacity-70' : 'text-muted-foreground'}>
                {llms.length}
              </span>
            </Badge>
          </button>
          {protocols.map((proto) => {
            const count = llms.filter(l => l.protocol === proto).length;
            return (
              <button
                key={proto}
                onClick={() => setProtocolFilter(proto)}
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-full"
              >
                <Badge
                  variant={protocolFilter === proto ? 'default' : 'outline'}
                  className={`cursor-pointer gap-1 px-2.5 py-0.5 text-xs transition-colors ${
                    protocolFilter === proto ? 'list-filter-badge-active' : ''
                  }`}
                >
                    {formatProtocolLabel(proto)}
                  <span className={protocolFilter === proto ? 'opacity-70' : 'text-muted-foreground'}>
                    {count}
                  </span>
                </Badge>
              </button>
            );
          })}
          {protocolFilter !== 'all' && (
            <button
              onClick={() => setProtocolFilter('all')}
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
            placeholder="Search by name, model or protocol…"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="Search LLMs"
            autoComplete="off"
          />
          <Button variant="outline" size="sm" aria-label="Search LLMs" tabIndex={-1}>
            Search
          </Button>
        </ButtonGroup>
      </div>

      {/* Table */}
      {filteredLLMs.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-40 gap-3 text-muted-foreground">
          {llms.length === 0 ? (
            <>
              <p className="text-sm">No LLM configurations yet.</p>
              <Button size="sm" variant="outline" onClick={handleCreate}>
                <Plus className="w-4 h-4 mr-1.5" />
                Add your first LLM
              </Button>
            </>
          ) : (
            <p className="text-sm">No LLMs match your search.</p>
          )}
        </div>
      ) : (
        <>
          <Table className="w-full table-fixed" containerClassName="overflow-hidden">
            <TableHeader>
              <TableRow>
                <TableHead className="w-[148px] whitespace-nowrap">Name</TableHead>
                <TableHead className="w-[188px] whitespace-nowrap">Model</TableHead>
                <TableHead className="w-[92px] whitespace-nowrap">Max Context</TableHead>
                <TableHead className="w-[96px] whitespace-nowrap">Protocol</TableHead>
                <TableHead className="w-[252px] whitespace-nowrap">Capabilities</TableHead>
                <TableHead className="w-[96px] whitespace-nowrap text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {pagedLLMs.map((llm) => (
                <LLMTableRow
                  key={llm.id}
                  llm={llm}
                  isCopying={copyingLLMId === llm.id}
                  onEdit={handleEdit}
                  onCopy={(targetLlm) => void handleCopy(targetLlm)}
                  onDelete={handleDelete}
                />
              ))}
            </TableBody>
          </Table>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-between">
              <span className="text-xs text-muted-foreground">
                {filteredLLMs.length} LLM{filteredLLMs.length !== 1 ? 's' : ''}
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

      {/* Modals */}
      <LLMModal
        isOpen={isModalOpen}
        mode={modalMode}
        llmId={editingLLM?.id ?? null}
        creatorUserId={editingLLM?.created_by_user_id ?? null}
        onClose={() => setIsModalOpen(false)}
        onSave={handleModalSave}
        initialData={
          editingLLM
            ? {
                name: editingLLM.name,
                endpoint: editingLLM.endpoint,
                model: editingLLM.model,
                api_key: editingLLM.api_key,
                protocol: editingLLM.protocol,
                cache_policy: editingLLM.cache_policy,
                thinking_policy: editingLLM.thinking_policy,
                thinking_effort: editingLLM.thinking_effort ?? '',
                thinking_budget_tokens: editingLLM.thinking_budget_tokens ?? null,
                streaming: editingLLM.streaming,
                image_input: editingLLM.image_input,
                image_output: editingLLM.image_output,
                max_context: editingLLM.max_context,
                extra_config: editingLLM.extra_config,
              }
            : undefined
        }
      />

      <ConfirmationModal
        isOpen={deleteConfirmation.isOpen}
        title="Delete LLM"
        message={`Are you sure you want to delete "${deleteConfirmation.llm?.name}"? This action cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        onConfirm={() => void confirmDelete()}
        onCancel={() => setDeleteConfirmation({ isOpen: false, llm: null })}
        variant="danger"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// LLMTableRow
// ---------------------------------------------------------------------------

interface LLMTableRowProps {
  llm: LLM;
  isCopying: boolean;
  onEdit: (llm: LLM) => void;
  onCopy: (llm: LLM) => void;
  onDelete: (llm: LLM) => void;
}

/**
 * Single row in the LLM table.
 * Shows key fields and a compact capability badge list.
 */
function LLMTableRow({ llm, isCopying, onEdit, onCopy, onDelete }: LLMTableRowProps) {
  const capabilityLabels = [
    llm.cache_policy !== 'none' ? formatCachePolicyLabel(llm.cache_policy) : null,
    formatThinkingPolicyLabel(llm.thinking_policy, llm.thinking_effort),
    llm.streaming ? 'Streaming' : null,
    llm.image_input ? 'Image Input' : null,
    llm.image_output ? 'Image Output' : null,
  ].filter((label): label is string => Boolean(label));

  return (
    <TableRow className="whitespace-nowrap">
      {/* Name + icon */}
      <TableCell className="overflow-hidden">
        <div className="flex items-center gap-2 overflow-hidden">
          <LLMBrandAvatar
            model={llm.model}
            containerClassName="w-6 h-6 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0"
            imageClassName="w-3.5 h-3.5"
            fallback={<Server className="w-3.5 h-3.5 text-primary" aria-hidden="true" />}
          />
          <span className="truncate text-sm font-medium" title={llm.name}>
            {llm.name}
          </span>
        </div>
      </TableCell>

      {/* Model */}
      <TableCell
        className="truncate font-mono text-xs text-muted-foreground"
        title={llm.model}
      >
        {llm.model}
      </TableCell>

      {/* Max Context */}
      <TableCell className="text-xs text-muted-foreground">
        <Badge
          variant="secondary"
          className="shrink-0 whitespace-nowrap px-2.5 py-0.5 text-xs transition-colors"
        >
          {formatMaxContext(llm.max_context)}
        </Badge>
      </TableCell>

      {/* Protocol */}
      <TableCell className="truncate text-xs text-muted-foreground">
        <span title={formatProtocolLabel(llm.protocol)}>
          {formatProtocolLabel(llm.protocol)}
        </span>
      </TableCell>

      {/* Capabilities */}
      <TableCell className="overflow-hidden">
        <div className="flex flex-nowrap items-center gap-1.5 overflow-hidden">
          {capabilityLabels.length > 0 ? (
            capabilityLabels.map((label) => (
              <Badge
                key={`${llm.id}-${label}`}
                variant="secondary"
                title={label}
                className="shrink-0 whitespace-nowrap px-2.5 py-0.5 text-xs transition-colors"
              >
                {label}
              </Badge>
            ))
          ) : (
            <span className="truncate text-xs text-muted-foreground">None</span>
          )}
        </div>
      </TableCell>

      {/* Actions */}
      <TableCell className="text-right">
        <div className="flex items-center justify-end gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={`Copy LLM ${llm.name}`}
            onClick={() => onCopy(llm)}
            disabled={isCopying}
          >
            <Copy className="w-3.5 h-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={`Edit LLM ${llm.name}`}
            onClick={() => onEdit(llm)}
          >
            <Pencil className="w-3.5 h-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-destructive hover:text-destructive"
            aria-label={`Delete LLM ${llm.name}`}
            onClick={() => onDelete(llm)}
          >
            <Trash2 className="w-3.5 h-3.5" />
          </Button>
        </div>
      </TableCell>
    </TableRow>
  );
}

export default LLMList;
