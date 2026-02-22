import { useState, useEffect, useCallback } from 'react';
import { Wrench, Check, Search, Loader2, Globe, Lock } from 'lucide-react';
import DraggableDialog from './DraggableDialog';
import { Button } from './ui/button';
import { Input } from './ui/input';
import { Badge } from './ui/badge';
import { getAgentTools, updateAgentTools } from '../utils/api';
import type { AgentToolResponse } from '../types';
import { toast } from 'sonner';

/**
 * Props for ToolSelectorDialog component.
 */
interface ToolSelectorDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Callback when dialog should close */
  onOpenChange: (open: boolean) => void;
  /** Agent ID to manage tools for */
  agentId: number;
  /** Callback when tools are successfully updated */
  onToolsUpdated?: () => void;
}

/**
 * Dialog for selecting which tools an agent can use.
 *
 * Features:
 * - Displays all available tools grouped by type (shared/private)
 * - Search/filter functionality
 * - Checkbox selection for each tool
 * - Save/Cancel actions
 * - Theme-aware styling
 */
function ToolSelectorDialog({
  open,
  onOpenChange,
  agentId,
  onToolsUpdated,
}: ToolSelectorDialogProps) {
  const [tools, setTools] = useState<AgentToolResponse[]>([]);
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());
  const [searchQuery, setSearchQuery] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [originalSelection, setOriginalSelection] = useState<Set<string>>(new Set());

  /**
   * Fetch agent tools when dialog opens.
   */
  const fetchAgentTools = useCallback(async () => {
    if (!open) return;

    setIsLoading(true);
    try {
      const toolsData = await getAgentTools(agentId);
      setTools(toolsData);

      // Initialize selection from enabled tools
      const enabledTools = new Set(
        toolsData.filter((t) => t.is_enabled).map((t) => t.name)
      );
      setSelectedTools(enabledTools);
      setOriginalSelection(enabledTools);
      setHasChanges(false);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to fetch agent tools:', error);
      toast.error('Failed to load tools');
    } finally {
      setIsLoading(false);
    }
  }, [agentId, open]);

  useEffect(() => {
    void fetchAgentTools();
  }, [fetchAgentTools]);

  /**
   * Reset search when dialog closes.
   */
  useEffect(() => {
    if (!open) {
      setSearchQuery('');
    }
  }, [open]);

  /**
   * Check if selection has changed from original.
   */
  useEffect(() => {
    const hasChanged =
      selectedTools.size !== originalSelection.size ||
      [...selectedTools].some((tool) => !originalSelection.has(tool)) ||
      [...originalSelection].some((tool) => !selectedTools.has(tool));
    setHasChanges(hasChanged);
  }, [selectedTools, originalSelection]);

  /**
   * Toggle tool selection.
   */
  const toggleTool = (toolName: string) => {
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (next.has(toolName)) {
        next.delete(toolName);
      } else {
        next.add(toolName);
      }
      return next;
    });
  };

  /**
   * Select or deselect all filtered tools.
   */
  const toggleAllFiltered = (select: boolean) => {
    const filteredToolNames = filteredTools.map((t) => t.name);
    setSelectedTools((prev) => {
      const next = new Set(prev);
      if (select) {
        filteredToolNames.forEach((name) => next.add(name));
      } else {
        filteredToolNames.forEach((name) => next.delete(name));
      }
      return next;
    });
  };

  /**
   * Save tool selection to server.
   */
  const handleSave = async () => {
    setIsSaving(true);
    try {
      await updateAgentTools(agentId, {
        tool_names: [...selectedTools],
      });

      // Update original selection after save
      setOriginalSelection(new Set(selectedTools));
      setHasChanges(false);

      toast.success('Tools updated successfully');
      onToolsUpdated?.();
      onOpenChange(false);
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      console.error('Failed to update agent tools:', error);
      toast.error(`Failed to save tools: ${error.message}`);
    } finally {
      setIsSaving(false);
    }
  };

  /**
   * Handle cancel - reset to original selection.
   */
  const handleCancel = () => {
    setSelectedTools(new Set(originalSelection));
    setSearchQuery('');
    onOpenChange(false);
  };

  // Filter tools based on search query
  const filteredTools = tools.filter(
    (tool) =>
      tool.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      tool.description.toLowerCase().includes(searchQuery.toLowerCase())
  );

  // Group tools by type
  const sharedTools = filteredTools.filter((t) => t.tool_type === 'shared');
  const privateTools = filteredTools.filter((t) => t.tool_type === 'private');

  // Count selected tools
  const selectedCount = selectedTools.size;
  const totalCount = tools.length;

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title="Configure Agent Tools"
      size="default"
    >
      <div className="flex flex-col h-full">
        {/* Header section with search and stats */}
        <div className="p-4 border-b border-border space-y-3">
          {/* Search input */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
            <Input
              placeholder="Search tools..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9 h-9"
            />
          </div>

          {/* Selection stats and actions */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">
              {selectedCount} of {totalCount} tools selected
            </span>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => toggleAllFiltered(true)}
              >
                Select all
              </Button>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-xs"
                onClick={() => toggleAllFiltered(false)}
              >
                Deselect all
              </Button>
            </div>
          </div>
        </div>

        {/* Tool list */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : filteredTools.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-8 text-muted-foreground">
              <Wrench className="w-8 h-8 mb-2 opacity-50" />
              <p className="text-sm">
                {searchQuery ? 'No tools match your search' : 'No tools available'}
              </p>
            </div>
          ) : (
            <>
              {/* Shared tools section */}
              {sharedTools.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 px-1">
                    <Globe className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Shared Tools
                    </span>
                    <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                      {sharedTools.length}
                    </Badge>
                  </div>
                  <div className="space-y-1">
                    {sharedTools.map((tool) => (
                      <ToolItem
                        key={tool.name}
                        tool={tool}
                        isSelected={selectedTools.has(tool.name)}
                        onToggle={() => toggleTool(tool.name)}
                      />
                    ))}
                  </div>
                </div>
              )}

              {/* Private tools section */}
              {privateTools.length > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center gap-2 px-1">
                    <Lock className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Private Tools
                    </span>
                    <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                      {privateTools.length}
                    </Badge>
                  </div>
                  <div className="space-y-1">
                    {privateTools.map((tool) => (
                      <ToolItem
                        key={tool.name}
                        tool={tool}
                        isSelected={selectedTools.has(tool.name)}
                        onToggle={() => toggleTool(tool.name)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer with action buttons */}
        <div className="p-4 border-t border-border flex items-center justify-end gap-2">
          <Button variant="outline" size="sm" onClick={handleCancel}>
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={!hasChanges || isSaving}
          >
            {isSaving ? (
              <>
                <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                Saving...
              </>
            ) : (
              <>
                <Check className="w-4 h-4 mr-1.5" />
                Save Changes
              </>
            )}
          </Button>
        </div>
      </div>
    </DraggableDialog>
  );
}

/**
 * Props for ToolItem component.
 */
interface ToolItemProps {
  /** Tool data */
  tool: AgentToolResponse;
  /** Whether the tool is selected */
  isSelected: boolean;
  /** Callback when tool is toggled */
  onToggle: () => void;
}

/**
 * Individual tool item with checkbox.
 */
function ToolItem({ tool, isSelected, onToggle }: ToolItemProps) {
  return (
    <button
      onClick={onToggle}
      className={`
        w-full flex items-start gap-3 p-2.5 rounded-md
        text-left transition-colors
        ${
          isSelected
            ? 'bg-primary/10 border border-primary/30'
            : 'bg-muted/30 border border-transparent hover:bg-muted/50 hover:border-border'
        }
      `}
    >
      {/* Checkbox indicator */}
      <div
        className={`
          flex-shrink-0 w-4 h-4 mt-0.5 rounded border
          flex items-center justify-center transition-colors
          ${
            isSelected
              ? 'bg-primary border-primary text-primary-foreground'
              : 'border-muted-foreground/30 bg-background'
          }
        `}
      >
        {isSelected && <Check className="w-3 h-3" />}
      </div>

      {/* Tool info */}
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-foreground truncate">
            {tool.name}
          </span>
          <Badge
            variant="outline"
            className={`
              text-[10px] h-4 px-1.5 font-normal
              ${
                tool.tool_type === 'shared'
                  ? 'border-primary/30 text-primary'
                  : 'border-secondary/30 text-secondary'
              }
            `}
          >
            {tool.tool_type}
          </Badge>
        </div>
        <p className="text-xs text-muted-foreground line-clamp-2 mt-0.5">
          {tool.description}
        </p>
      </div>
    </button>
  );
}

export default ToolSelectorDialog;
