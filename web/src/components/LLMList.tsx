import { useState, useEffect, useRef, MouseEvent } from 'react';
import {
  Plus,
  Search,
  Download,
  Upload,
  Server,
  MoreHorizontal,
  Loader2,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
} from 'lucide-react';
import { toast } from 'sonner';
import { getLLMs, deleteLLM, updateLLM, createLLM } from '../utils/api';
import type { LLM } from '../types';
import LLMModal from './LLMModal';
import ConfirmationModal from './ConfirmationModal';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { ButtonGroup } from '@/components/ui/button-group';
import { Badge } from '@/components/ui/badge';
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

/** Fields exported/imported in JSON — intentionally excludes server-assigned ids and timestamps. */
type LLMExportRecord = Omit<LLM, 'id' | 'created_at' | 'updated_at'>;

type SortField = 'name' | 'model' | 'protocol' | 'max_context';
type SortDir = 'asc' | 'desc';

/**
 * LLM list page component.
 *
 * Renders a sortable, searchable table of LLM configurations with full
 * CRUD support plus JSON import / export capabilities.
 */
function LLMList() {
  const [llms, setLLMs] = useState<LLM[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [importing, setImporting] = useState(false);

  const [searchQuery, setSearchQuery] = useState('');
  const [sortField, setSortField] = useState<SortField>('name');
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editingLLM, setEditingLLM] = useState<LLM | null>(null);
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    llm: LLM | null;
  }>({ isOpen: false, llm: null });

  /** Hidden file input used to trigger JSON import. */
  const importInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    void loadLLMs();
  }, []);

  const loadLLMs = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getLLMs();
      setLLMs(data);
    } catch (err) {
      const e = err as Error;
      setError(e.message || 'Failed to load LLMs');
    } finally {
      setLoading(false);
    }
  };

  // ─── Sorting ────────────────────────────────────────────────────────────────

  /**
   * Toggle sort direction when clicking the same field, or switch to a new
   * field in ascending order.
   */
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

  // ─── Derived list ───────────────────────────────────────────────────────────

  const filteredAndSorted = llms
    .filter((llm) => {
      const q = searchQuery.toLowerCase();
      return (
        llm.name.toLowerCase().includes(q) ||
        llm.model.toLowerCase().includes(q) ||
        llm.endpoint.toLowerCase().includes(q) ||
        llm.protocol.toLowerCase().includes(q)
      );
    })
    .sort((a, b) => {
      let cmp = 0;
      if (sortField === 'max_context') {
        cmp = a.max_context - b.max_context;
      } else {
        cmp = a[sortField].localeCompare(b[sortField]);
      }
      return sortDir === 'asc' ? cmp : -cmp;
    });

  // ─── CRUD ────────────────────────────────────────────────────────────────────

  const handleCreateLLM = () => {
    setModalMode('create');
    setEditingLLM(null);
    setIsModalOpen(true);
  };

  const handleEditLLM = (llm: LLM, e: MouseEvent) => {
    e.stopPropagation();
    setModalMode('edit');
    setEditingLLM(llm);
    setIsModalOpen(true);
  };

  const handleDeleteLLM = (llm: LLM, e: MouseEvent) => {
    e.stopPropagation();
    setDeleteConfirmation({ isOpen: true, llm });
  };

  const confirmDeleteLLM = async () => {
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

  const handleModalSave = async (llmData: {
    name: string;
    endpoint: string;
    model: string;
    api_key: string;
    protocol: string;
    chat: boolean;
    system_role: boolean;
    tool_calling: string;
    json_schema: string;
    streaming: boolean;
    max_context: number;
    extra_config: string;
  }) => {
    if (modalMode === 'create') {
      await createLLM(llmData);
      toast.success('LLM created');
    } else if (modalMode === 'edit' && editingLLM) {
      await updateLLM(editingLLM.id, llmData);
      toast.success('LLM updated');
    }
    await loadLLMs();
  };

  // ─── Export / Import ────────────────────────────────────────────────────────

  /** Serialize current LLM list to a downloadable JSON file. */
  const handleExport = () => {
    const payload: LLMExportRecord[] = llms.map(
      ({ id: _id, created_at: _c, updated_at: _u, ...rest }) => rest,
    );
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pivot-llms-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success(`Exported ${llms.length} LLM${llms.length !== 1 ? 's' : ''}`);
  };

  /** Trigger the hidden file input to begin the import flow. */
  const handleImportClick = () => importInputRef.current?.click();

  /**
   * Read a JSON file and create each LLM entry via the API.
   * Duplicate names will surface as API errors which are collected and shown.
   */
  const handleImportFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset the input so the same file can be re-imported if needed
    e.target.value = '';

    try {
      setImporting(true);
      const text = await file.text();
      const parsed: unknown = JSON.parse(text);

      if (!Array.isArray(parsed)) {
        toast.error('Invalid format: expected a JSON array');
        return;
      }

      let created = 0;
      const errors: string[] = [];

      for (const item of parsed) {
        try {
          await createLLM(item as LLMExportRecord);
          created++;
        } catch (err) {
          const ex = err as Error;
          errors.push(ex.message);
        }
      }

      if (created > 0) {
        toast.success(`Imported ${created} LLM${created !== 1 ? 's' : ''}`);
        await loadLLMs();
      }
      if (errors.length > 0) {
        toast.error(`${errors.length} item${errors.length !== 1 ? 's' : ''} failed to import`);
      }
    } catch {
      toast.error('Failed to parse file — ensure it is valid JSON');
    } finally {
      setImporting(false);
    }
  };

  // ─── Render helpers ──────────────────────────────────────────────────────────

  /** Renders a short capability badge row for a given LLM. */
  const CapabilityBadges = ({ llm }: { llm: LLM }) => (
    <div className="flex flex-wrap gap-1">
      {llm.streaming && (
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-normal">
          Stream
        </Badge>
      )}
      {llm.tool_calling === 'native' && (
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-normal">
          Tools
        </Badge>
      )}
      {llm.json_schema === 'strong' && (
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-normal">
          JSON
        </Badge>
      )}
      {llm.chat && (
        <Badge variant="outline" className="text-[10px] px-1.5 py-0 h-4 font-normal">
          Chat
        </Badge>
      )}
    </div>
  );

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
        <Button size="sm" onClick={() => void loadLLMs()}>
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
              <Server className="w-4 h-4 text-primary" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-base font-semibold leading-tight">LLM Configurations</h1>
              <p className="text-xs text-muted-foreground mt-0.5">
                {llms.length} configuration{llms.length !== 1 ? 's' : ''}
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleExport}
              disabled={llms.length === 0}
              className="gap-1.5"
              aria-label="Export LLMs as JSON"
            >
              <Download className="w-3.5 h-3.5" aria-hidden="true" />
              Export
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleImportClick}
              disabled={importing}
              className="gap-1.5"
              aria-label="Import LLMs from JSON"
            >
              {importing ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" aria-hidden="true" />
              ) : (
                <Upload className="w-3.5 h-3.5" aria-hidden="true" />
              )}
              Import
            </Button>
            <Button size="sm" onClick={handleCreateLLM} className="gap-1.5" aria-label="Create a new LLM">
              <Plus className="w-3.5 h-3.5" aria-hidden="true" />
              New LLM
            </Button>
          </div>
        </div>

        {/* Search row */}
        <div className="relative max-w-sm">
          <Search
            className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground pointer-events-none z-10"
            aria-hidden="true"
          />
          <ButtonGroup>
            <Input
              placeholder="Search by name, model, endpoint…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-8 text-sm"
              autoComplete="off"
              aria-label="Search LLMs"
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
                {/* Sortable column header helper */}
                {(
                  [
                    { field: 'name' as const, label: 'Name', className: 'w-[200px] pl-4' },
                    { field: 'model' as const, label: 'Model', className: 'w-[200px]' },
                    { field: 'protocol' as const, label: 'Protocol', className: 'w-[160px]' },
                    { field: 'max_context' as const, label: 'Context', className: 'w-[100px]' },
                  ] as const
                ).map(({ field, label, className }) => (
                  <TableHead key={field} className={className}>
                    <button
                      onClick={() => handleSort(field)}
                      className="flex items-center gap-1.5 font-medium text-xs uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
                    >
                      {label}
                      <SortIcon field={field} />
                    </button>
                  </TableHead>
                ))}
                <TableHead className="text-xs uppercase tracking-wider font-medium text-muted-foreground">
                  Capabilities
                </TableHead>
                <TableHead className="w-[56px]" />
              </TableRow>
            </TableHeader>

            <TableBody>
              {filteredAndSorted.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={6} className="h-32 text-center">
                    <div className="flex flex-col items-center gap-2 text-muted-foreground">
                      <Server className="w-8 h-8 opacity-20" />
                      <span className="text-sm">
                        {searchQuery ? 'No LLMs match your search' : 'No LLMs configured yet'}
                      </span>
                      {!searchQuery && (
                        <Button variant="outline" size="sm" onClick={handleCreateLLM} className="mt-1">
                          <Plus className="w-3.5 h-3.5 mr-1.5" />
                          Add your first LLM
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ) : (
                filteredAndSorted.map((llm) => (
                  <TableRow
                    key={llm.id}
                    className="group cursor-default"
                    aria-label={`LLM ${llm.name}`}
                  >
                    {/* Name */}
                    <TableCell className="pl-4">
                      <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0">
                          <Server className="w-3.5 h-3.5 text-primary" aria-hidden="true" />
                        </div>
                        <div className="min-w-0">
                          <div className="font-medium text-sm truncate">{llm.name}</div>
                          <div
                            className="text-[11px] text-muted-foreground truncate max-w-[160px]"
                            title={llm.endpoint}
                          >
                            {llm.endpoint}
                          </div>
                        </div>
                      </div>
                    </TableCell>

                    {/* Model */}
                    <TableCell>
                      <span className="font-mono text-sm text-foreground/80">{llm.model}</span>
                    </TableCell>

                    {/* Protocol */}
                    <TableCell>
                      <Badge variant="secondary" className="font-mono text-[11px] font-normal">
                        {llm.protocol}
                      </Badge>
                    </TableCell>

                    {/* Context */}
                    <TableCell>
                      <span className="text-sm tabular-nums text-muted-foreground">
                        {llm.max_context.toLocaleString()}
                      </span>
                    </TableCell>

                    {/* Capabilities */}
                    <TableCell>
                      <CapabilityBadges llm={llm} />
                    </TableCell>

                    {/* Actions */}
                    <TableCell className="pr-3">
                      <DropdownMenu>
                        <DropdownMenuTrigger asChild>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                            onClick={(e) => e.stopPropagation()}
                            aria-label={`Options for ${llm.name}`}
                          >
                            <MoreHorizontal className="w-4 h-4" aria-hidden="true" />
                          </Button>
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                          <DropdownMenuItem
                            onClick={(e) => handleEditLLM(llm, e as unknown as MouseEvent)}
                          >
                            Edit
                          </DropdownMenuItem>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onClick={(e) => handleDeleteLLM(llm, e as unknown as MouseEvent)}
                            className="text-destructive focus:text-destructive"
                          >
                            Delete
                          </DropdownMenuItem>
                        </DropdownMenuContent>
                      </DropdownMenu>
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
            Showing {filteredAndSorted.length} of {llms.length} LLM
            {llms.length !== 1 ? 's' : ''}
            {searchQuery && ` matching "${searchQuery}"`}
          </p>
        )}
      </div>

      {/* ── Hidden import file input ── */}
      <input
        ref={importInputRef}
        type="file"
        accept=".json,application/json"
        className="sr-only"
        onChange={(e) => void handleImportFile(e)}
        aria-hidden="true"
      />

      {/* ── Dialogs ── */}
      <LLMModal
        isOpen={isModalOpen}
        mode={modalMode}
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
                chat: editingLLM.chat,
                system_role: editingLLM.system_role,
                tool_calling: editingLLM.tool_calling,
                json_schema: editingLLM.json_schema,
                streaming: editingLLM.streaming,
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
        onConfirm={() => void confirmDeleteLLM()}
        onCancel={() => setDeleteConfirmation({ isOpen: false, llm: null })}
        variant="danger"
      />
    </div>
  );
}

export default LLMList;
