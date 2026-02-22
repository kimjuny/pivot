import { useState, useEffect, useMemo } from 'react';
import Editor from '@monaco-editor/react';
import { Loader2 } from 'lucide-react';
import DraggableDialog from './DraggableDialog';
import { Button } from './ui/button';
import { useTheme } from '@/lib/use-theme';
import type { ToolWithOwnership } from '@/types';

/**
 * Editor mode - create new tool or edit existing.
 */
type EditorMode = 'create' | 'edit';

/**
 * Props for ToolEditorDialog component.
 */
interface ToolEditorDialogProps {
  /** Whether the dialog is open */
  open: boolean;
  /** Callback when dialog open state changes */
  onOpenChange: (open: boolean) => void;
  /** Editor mode: create or edit */
  mode: EditorMode;
  /** Tool to edit (required in edit mode) */
  tool?: ToolWithOwnership | null;
  /** Initial source code (for edit mode) */
  initialSource?: string;
  /** Callback when tool is saved - only needs source code */
  onSave: (sourceCode: string) => Promise<void>;
}

/**
 * Default tool template for new tools.
 * Users only need to modify the name, description, and implementation.
 */
const DEFAULT_TOOL_TEMPLATE = `from app.orchestration.tool import tool


@tool(
    name="my_tool",
    description="Description of what this tool does",
    parameters={
        "type": "object",
        "properties": {
            "input": {
                "type": "string",
                "description": "Description of the input parameter"
            }
        },
        "required": ["input"],
        "additionalProperties": False
    }
)
def my_tool(input: str) -> str:
    """Tool function implementation.

    Args:
        input: Description of input parameter.

    Returns:
        Description of return value.
    """
    return f"Processed: {input}"
`;

/**
 * Tool editor dialog with Monaco Editor.
 *
 * Simplified UX: Users only write/edit the source code.
 * The name and description are automatically extracted from the @tool decorator.
 * Automatically adapts to dark/light theme.
 */
function ToolEditorDialog({
  open,
  onOpenChange,
  mode,
  tool,
  initialSource,
  onSave,
}: ToolEditorDialogProps) {
  const { theme } = useTheme();
  const [sourceCode, setSourceCode] = useState(DEFAULT_TOOL_TEMPLATE);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Determine Monaco theme based on app theme
  const editorTheme = useMemo(() => {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'vs-dark'
        : 'light';
    }
    return theme === 'dark' ? 'vs-dark' : 'light';
  }, [theme]);

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setError(null);
      if (mode === 'edit' && initialSource) {
        setSourceCode(initialSource);
      } else {
        setSourceCode(DEFAULT_TOOL_TEMPLATE);
      }
    }
  }, [open, mode, initialSource]);

  /**
   * Handle save button click.
   */
  const handleSave = async () => {
    if (!sourceCode.trim()) {
      setError('Source code is required');
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await onSave(sourceCode);
      onOpenChange(false);
    } catch (err) {
      const error = err as Error;
      setError(error.message || 'Failed to save tool');
    } finally {
      setIsSubmitting(false);
    }
  };

  /**
   * Handle cancel button click.
   */
  const handleCancel = () => {
    onOpenChange(false);
  };

  const title = mode === 'create' ? 'New Tool' : `Edit Tool: ${tool?.name || ''}`;

  return (
    <DraggableDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      size="large"
      headerAction={
        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCancel}
            disabled={isSubmitting}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            onClick={handleSave}
            disabled={isSubmitting}
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                Saving...
              </>
            ) : (
              'Save'
            )}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col h-full p-4 gap-4">
        {/* Help text */}
        <div className="px-3 py-2 bg-muted/50 border border-border rounded-md text-sm text-muted-foreground">
          Define your tool using the <code className="font-mono text-foreground">@tool</code> decorator.
          The <code className="font-mono text-foreground">name</code> and <code className="font-mono text-foreground">description</code> will be extracted automatically.
        </div>

        {/* Error message */}
        {error && (
          <div className="px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-md text-sm text-destructive">
            {error}
          </div>
        )}

        {/* Source code editor */}
        <div className="flex-1 flex flex-col gap-1.5 min-h-0">
          <label className="text-sm font-medium text-foreground">
            Source Code
          </label>
          <div className="flex-1 border border-border rounded-md overflow-hidden">
            <Editor
              height="100%"
              language="python"
              theme={editorTheme}
              value={sourceCode}
              onChange={(value) => setSourceCode(value || '')}
              options={{
                minimap: { enabled: false },
                fontSize: 13,
                lineNumbers: 'on',
                scrollBeyondLastLine: false,
                automaticLayout: true,
                tabSize: 4,
                insertSpaces: true,
                wordWrap: 'on',
                folding: true,
                renderLineHighlight: 'line',
                cursorBlinking: 'smooth',
                padding: { top: 8, bottom: 8 },
              }}
              loading={
                <div className="flex items-center justify-center h-full bg-background">
                  <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
                </div>
              }
            />
          </div>
        </div>
      </div>
    </DraggableDialog>
  );
}

export default ToolEditorDialog;
