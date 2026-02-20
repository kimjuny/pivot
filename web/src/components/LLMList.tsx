import { useState, useEffect, MouseEvent } from 'react';
import { Plus, Server, MoreHorizontal, Search } from 'lucide-react';
import { toast } from 'sonner';
import { getLLMs, deleteLLM, updateLLM, createLLM } from '../utils/api';
import type { LLM } from '../types';
import LLMModal from './LLMModal';
import ConfirmationModal from './ConfirmationModal';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Badge } from '@/components/ui/badge';

/**
 * LLM list component.
 * Displays all available LLM configurations with their details.
 * Allows CRUD operations on LLM configurations.
 */
function LLMList() {
  const [llms, setLLMs] = useState<LLM[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [isModalOpen, setIsModalOpen] = useState<boolean>(false);
  const [modalMode, setModalMode] = useState<'create' | 'edit'>('create');
  const [editingLLM, setEditingLLM] = useState<LLM | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    llm: LLM | null;
  }>({ isOpen: false, llm: null });

  /**
   * Load LLMs from server on component mount.
   * Fetches all available LLMs and updates state.
   */
  useEffect(() => {
    void loadLLMs();
  }, []);

  /**
   * Fetch LLMs from API and update state.
   * Handles loading and error states.
   */
  const loadLLMs = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getLLMs();
      setLLMs(data);
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to load LLMs');
    } finally {
      setLoading(false);
    }
  };

  /**
   * Handle create LLM button click.
   * Opens the LLM modal in create mode.
   */
  const handleCreateLLM = () => {
    setModalMode('create');
    setEditingLLM(null);
    setIsModalOpen(true);
  };

  /**
   * Handle edit LLM button click.
   * Opens the LLM modal in edit mode.
   */
  const handleEditLLM = (llm: LLM, e: MouseEvent) => {
    e.stopPropagation();
    setModalMode('edit');
    setEditingLLM(llm);
    setIsModalOpen(true);
  };

  /**
   * Handle delete LLM button click.
   * Opens confirmation modal.
   */
  const handleDeleteLLM = (llm: LLM, e: MouseEvent) => {
    e.stopPropagation();
    setDeleteConfirmation({ isOpen: true, llm });
  };

  /**
   * Confirm LLM deletion.
   * Deletes the LLM and reloads the list.
   */
  const confirmDeleteLLM = async () => {
    if (!deleteConfirmation.llm) return;

    try {
      await deleteLLM(deleteConfirmation.llm.id);
      setDeleteConfirmation({ isOpen: false, llm: null });
      toast.success('LLM deleted successfully');
      await loadLLMs();
    } catch (err) {
      const error = err as Error;
      toast.error(`Failed to delete LLM: ${error.message}`);
      setDeleteConfirmation({ isOpen: false, llm: null });
    }
  };

  /**
   * Cancel LLM deletion.
   */
  const cancelDeleteLLM = () => {
    setDeleteConfirmation({ isOpen: false, llm: null });
  };

  /**
   * Handle modal save.
   * Creates or updates LLM and reloads list.
   */
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
      toast.success('LLM created successfully');
      await loadLLMs();
    } else if (modalMode === 'edit' && editingLLM) {
      await updateLLM(editingLLM.id, llmData);
      toast.success('LLM updated successfully');
      await loadLLMs();
    }
  };

  const filteredLLMs = llms.filter((llm) =>
    llm.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    llm.model.toLowerCase().includes(searchQuery.toLowerCase()) ||
    llm.endpoint.toLowerCase().includes(searchQuery.toLowerCase())
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen bg-background">
        <div className="flex flex-col items-center space-y-4">
          <div className="spinner"></div>
          <div className="text-lg text-muted-foreground font-medium">Loading…</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-screen bg-background">
        <div className="text-xl text-destructive mb-4 font-medium">Error: {error}</div>
        <Button
          onClick={() => void loadLLMs()}
          className="font-medium"
        >
          Retry
        </Button>
      </div>
    );
  }

  return (
    <div className="flex-1 bg-background text-foreground">
      <div className="w-full px-4 py-8">
        <div className="flex items-center justify-between mb-8 gap-4">
          <div className="flex-1 max-w-md relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none" aria-hidden="true" />
            <Input
              placeholder="Search LLMs…"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-10"
              autoComplete="off"
              inputMode="search"
              name="search"
              aria-label="Search LLMs"
            />
          </div>
          <Button
            onClick={handleCreateLLM}
            size="sm"
            className="flex items-center gap-2"
            aria-label="Create a new LLM"
          >
            <Plus className="w-4 h-4" aria-hidden="true" />
            <span>New LLM</span>
          </Button>
        </div>

        {filteredLLMs.length === 0 && llms.length > 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-muted-foreground mb-4">🔍</div>
            <h3 className="text-xl font-semibold text-foreground mb-2">No Results</h3>
            <p className="text-muted-foreground">
              Try adjusting your search query
            </p>
          </div>
        ) : llms.length === 0 ? (
          <div className="text-center py-16">
            <div className="text-6xl text-muted-foreground mb-4">🤖</div>
            <h3 className="text-xl font-semibold text-foreground mb-2">No LLMs</h3>
            <p className="text-muted-foreground mb-6">
              Click the "New LLM" button to add your first LLM configuration
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3">
            {filteredLLMs.map((llm) => (
              <Card
                key={llm.id}
                className="transition-all duration-200 hover:bg-accent/50 motion-reduce:transition-none relative group p-3 flex flex-col min-h-[130px]"
                role="article"
                aria-label={`LLM ${llm.name}`}
              >
                {/* Top row: Icon + Name + Menu */}
                <div className="flex items-center gap-2.5">
                  <div className="w-8 h-8 rounded-md bg-primary/20 flex items-center justify-center flex-shrink-0">
                    <Server className="w-4 h-4 text-primary" aria-hidden="true" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="font-medium text-sm truncate">{llm.name}</span>
                    </div>
                    <div className="text-xs text-muted-foreground truncate">
                      {llm.model}
                    </div>
                  </div>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity flex-shrink-0"
                        onClick={(e) => e.stopPropagation()}
                        aria-label="LLM options"
                      >
                        <MoreHorizontal className="w-3.5 h-3.5" aria-hidden="true" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                      <DropdownMenuItem onClick={(e) => handleEditLLM(llm, e as unknown as MouseEvent)}>
                        Edit
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        onClick={(e) => handleDeleteLLM(llm, e as unknown as MouseEvent)}
                        className="text-destructive focus:text-destructive"
                      >
                        Delete
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>

                {/* Details - with flex-1 to push tags to bottom */}
                <div className="flex-1 mt-2">
                  <div className="space-y-1 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Protocol:</span>
                      <span className="text-[10px]">{llm.protocol}</span>
                    </div>
                    <div className="flex items-center justify-between">
                      <span className="text-muted-foreground">Context:</span>
                      <span className="text-[10px] tabular-nums">{llm.max_context.toLocaleString()}</span>
                    </div>
                  </div>
                </div>

                {/* Bottom row: Capabilities - always at bottom */}
                <div className="flex flex-wrap gap-1 mt-2">
                  {llm.streaming && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0.5">
                      Stream
                    </Badge>
                  )}
                  {llm.tool_calling === 'native' && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0.5">
                      Tools
                    </Badge>
                  )}
                  {llm.json_schema === 'strong' && (
                    <Badge variant="outline" className="text-[10px] px-1.5 py-0.5">
                      JSON
                    </Badge>
                  )}
                </div>
              </Card>
            ))}
          </div>
        )}
      </div>

      <LLMModal
        isOpen={isModalOpen}
        mode={modalMode}
        onClose={() => setIsModalOpen(false)}
        onSave={handleModalSave}
        initialData={editingLLM ? {
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
        } : undefined}
      />

      <ConfirmationModal
        isOpen={deleteConfirmation.isOpen}
        title="Delete LLM"
        message={`Are you sure you want to delete LLM "${deleteConfirmation.llm?.name}"? This action cannot be undone.`}
        confirmText="Delete LLM"
        cancelText="Cancel"
        onConfirm={() => void confirmDeleteLLM()}
        onCancel={cancelDeleteLLM}
        variant="danger"
      />
    </div>
  );
}

export default LLMList;
