import { useState, useEffect } from 'react';
import { Search, Plus, Pencil, Trash2, Loader2, Wrench, Code } from 'lucide-react';
import { Button } from '@/components/ui/button';
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

/**
 * Tools list component.
 * Displays all tools (shared + private) in a table format.
 * Allows CRUD operations with proper permission checks.
 */
function ToolsList() {
  const [tools, setTools] = useState<ToolWithOwnership[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Editor dialog state
  const [editorOpen, setEditorOpen] = useState<boolean>(false);
  const [editorMode, setEditorMode] = useState<'create' | 'edit'>('create');
  const [editingTool, setEditingTool] = useState<ToolWithOwnership | null>(null);
  const [editingSource, setEditingSource] = useState<string>('');

  // Delete confirmation state
  const [deleteConfirmation, setDeleteConfirmation] = useState<{
    isOpen: boolean;
    tool: ToolWithOwnership | null;
    isDeleting: boolean;
  }>({ isOpen: false, tool: null, isDeleting: false });

  /**
   * Fetch tools from API.
   */
  const fetchTools = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getToolsWithOwnership();
      // Sort: private first, then shared, then by name
      data.sort((a, b) => {
        if (a.tool_type !== b.tool_type) {
          return a.tool_type === 'private' ? -1 : 1;
        }
        return a.name.localeCompare(b.name);
      });
      setTools(data);
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to load tools');
      toast.error('Failed to load tools');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void fetchTools();
  }, []);

  /**
   * Filter tools by search query.
   */
  const filteredTools = tools.filter((tool) => {
    const query = searchQuery.toLowerCase();
    return (
      tool.name.toLowerCase().includes(query) ||
      tool.description.toLowerCase().includes(query) ||
      tool.tool_type.toLowerCase().includes(query) ||
      (tool.owner_username?.toLowerCase().includes(query) ?? false)
    );
  });

  /**
   * Handle create tool button click.
   */
  const handleCreateTool = () => {
    setEditingTool(null);
    setEditingSource('');
    setEditorMode('create');
    setEditorOpen(true);
  };

  /**
   * Handle edit tool button click.
   */
  const handleEditTool = async (tool: ToolWithOwnership) => {
    try {
      // Fetch source code
      const source: ToolSource = await getToolSource(tool.name);
      setEditingTool(tool);
      setEditingSource(source.source_code);
      setEditorMode('edit');
      setEditorOpen(true);
    } catch (err) {
      const error = err as Error;
      toast.error(error.message || 'Failed to load tool source');
    }
  };

  /**
   * Handle save tool (create or update).
   * Only source code is needed - name and description are extracted from @tool decorator.
   */
  const handleSaveTool = async (sourceCode: string) => {
    if (editorMode === 'create') {
      await createTool({
        source_code: sourceCode,
      });
      toast.success('Tool created successfully');
    } else if (editingTool) {
      await updateTool(editingTool.name, {
        source_code: sourceCode,
      });
      toast.success('Tool updated successfully');
    }
    void fetchTools();
  };

  /**
   * Handle delete tool button click.
   */
  const handleDeleteClick = (tool: ToolWithOwnership) => {
    setDeleteConfirmation({ isOpen: true, tool, isDeleting: false });
  };

  /**
   * Confirm delete tool.
   */
  const handleConfirmDelete = async () => {
    const tool = deleteConfirmation.tool;
    if (!tool) return;

    try {
      setDeleteConfirmation((prev) => ({ ...prev, isDeleting: true }));
      await deleteTool(tool.name);
      toast.success('Tool deleted successfully');
      setDeleteConfirmation({ isOpen: false, tool: null, isDeleting: false });
      void fetchTools();
    } catch (err) {
      const error = err as Error;
      toast.error(error.message || 'Failed to delete tool');
      setDeleteConfirmation((prev) => ({ ...prev, isDeleting: false }));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <p className="text-destructive">{error}</p>
        <Button onClick={() => void fetchTools()}>Retry</Button>
      </div>
    );
  }

  return (
    <div className="flex flex-col flex-1 bg-background text-foreground">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search tools..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button onClick={handleCreateTool}>
          <Plus className="w-4 h-4 mr-1.5" />
          New Tool
        </Button>
      </div>

      {/* Table */}
      <div className="border border-border rounded-lg overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="bg-muted/50 border-b border-border">
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">
                Name
              </th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground">
                Description
              </th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground w-24">
                Type
              </th>
              <th className="text-left px-4 py-3 text-sm font-medium text-muted-foreground w-28">
                Owner
              </th>
              <th className="text-right px-4 py-3 text-sm font-medium text-muted-foreground w-28">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {filteredTools.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center text-muted-foreground">
                  {searchQuery ? 'No tools found matching your search' : 'No tools yet. Create your first tool!'}
                </td>
              </tr>
            ) : (
              filteredTools.map((tool) => (
                <tr
                  key={tool.name}
                  className="border-b border-border last:border-b-0 hover:bg-muted/30 transition-colors"
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-7 h-7 rounded-md bg-primary/10 flex items-center justify-center flex-shrink-0">
                        {tool.tool_type === 'shared' ? (
                          <Code className="w-3.5 h-3.5 text-primary" />
                        ) : (
                          <Wrench className="w-3.5 h-3.5 text-primary" />
                        )}
                      </div>
                      <span className="font-mono text-sm font-medium">{tool.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-muted-foreground line-clamp-2">
                      {tool.description || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <Badge
                      variant={tool.tool_type === 'shared' ? 'secondary' : 'default'}
                      className="text-xs"
                    >
                      {tool.tool_type}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-sm text-muted-foreground">
                      {tool.owner_username || '-'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-1">
                      {tool.can_edit && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => void handleEditTool(tool)}
                          aria-label={`Edit ${tool.name}`}
                        >
                          <Pencil className="w-4 h-4" />
                        </Button>
                      )}
                      {tool.can_delete && (
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleDeleteClick(tool)}
                          aria-label={`Delete ${tool.name}`}
                          className="text-destructive hover:text-destructive"
                        >
                          <Trash2 className="w-4 h-4" />
                        </Button>
                      )}
                      {!tool.can_edit && !tool.can_delete && (
                        <span className="text-xs text-muted-foreground">-</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Tool count */}
      <div className="mt-4 text-sm text-muted-foreground">
        {filteredTools.length} tool{filteredTools.length !== 1 ? 's' : ''}
        {searchQuery && ` matching "${searchQuery}"`}
      </div>

      {/* Editor Dialog */}
      <ToolEditorDialog
        open={editorOpen}
        onOpenChange={setEditorOpen}
        mode={editorMode}
        tool={editingTool}
        initialSource={editingSource}
        onSave={handleSaveTool}
      />

      {/* Delete Confirmation Dialog */}
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
              Are you sure you want to delete the tool "{deleteConfirmation.tool?.name}"?
              This action cannot be undone.
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
                  <Loader2 className="w-4 h-4 mr-1.5 animate-spin" />
                  Deleting...
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
