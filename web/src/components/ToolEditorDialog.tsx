import { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import { Loader2, AlertCircle, AlertTriangle, CheckCircle2 } from 'lucide-react';
import DraggableDialog from './DraggableDialog';
import { Button } from './ui/button';
import { useTheme } from '@/lib/use-theme';
import { lintToolSource } from '@/utils/api';
import type { LintDiagnostic, ToolWithOwnership } from '@/types';

// ---------------------------------------------------------------------------
// Minimal Monaco interfaces — avoids unsafe-any from monaco-editor internals
// ---------------------------------------------------------------------------

/** Subset of monaco.editor.IMarkerData we need to push diagnostics. */
interface MonacoMarker {
  startLineNumber: number;
  startColumn: number;
  endLineNumber: number;
  endColumn: number;
  message: string;
  /** MonacoSeverity: Error=8, Warning=4, Info=2, Hint=1 */
  severity: number;
  source?: string;
}

/** Subset of monaco.editor.ITextModel we care about. */
interface MonacoModel {
  uri: unknown;
}

/** Narrow interface for the parts of the Monaco API we actually call. */
interface MinimalMonaco {
  editor: {
    setModelMarkers(model: MonacoModel, owner: string, markers: MonacoMarker[]): void;
  };
  MarkerSeverity: {
    readonly Error: 8;
    readonly Warning: 4;
    readonly Info: 2;
    readonly Hint: 1;
  };
}

/** Narrow interface for the parts of IStandaloneCodeEditor we actually call. */
interface MinimalEditor {
  getModel(): MonacoModel | null;
}

/** Editor mode — create new tool or edit existing. */
type EditorMode = 'create' | 'edit';

/** Aggregated diagnostic counts shown in the status bar. */
interface DiagnosticCounts {
  errors: number;
  warnings: number;
}

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
  /** Callback when tool is saved — only needs source code */
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

/** Stable Monaco marker severity values (enum integers). */
const MARKER_SEVERITY: Record<LintDiagnostic['severity'], 8 | 4 | 2> = {
  error: 8,    // MarkerSeverity.Error
  warning: 4,  // MarkerSeverity.Warning
  info: 2,     // MarkerSeverity.Info
};

/** Marker owner ID used with setModelMarkers — must be consistent across calls. */
const MARKER_OWNER = 'pivot-lint';

/**
 * Convert backend LintDiagnostics into Monaco marker objects.
 * Backend returns 1-based coordinates, which matches Monaco's input format.
 */
function buildMarkers(diagnostics: LintDiagnostic[]): MonacoMarker[] {
  return diagnostics.map((d) => ({
    startLineNumber: d.line,
    startColumn: d.col,
    endLineNumber: d.end_line,
    endColumn: d.end_col,
    message: d.code ? `[${d.code}] ${d.message}` : d.message,
    severity: MARKER_SEVERITY[d.severity],
    source: d.source,
  }));
}

/**
 * Tool editor dialog with Monaco Editor and real-time lint feedback.
 *
 * Three-tier check strategy driven by keystroke debouncing:
 * - 300 ms after last keystroke   → "ast"     (syntax only, fast in-process)
 * - 2 000 ms after last keystroke → "ruff"    (style / import / bug lints)
 * - On Save button click           → "pyright" (full type checking, ~1–3 s)
 *
 * Diagnostics from all three sources are merged and rendered directly inside
 * Monaco via `setModelMarkers`, giving an IDE-like inline error experience.
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
  const [saveError, setSaveError] = useState<string | null>(null);

  // Monaco editor / API instances captured via onMount (cast to minimal interfaces
  // to avoid unsafe-any from monaco-editor's internal types)
  const editorRef = useRef<MinimalEditor | null>(null);
  const monacoRef = useRef<MinimalMonaco | null>(null);

  // Per-source diagnostics — each check only overwrites its own slice so
  // results from sibling checks are preserved across independent refreshes.
  const diagnosticsRef = useRef<Record<string, LintDiagnostic[]>>({
    ast: [],
    ruff: [],
    pyright: [],
  });

  // Debounce timer handles cleared on every keystroke
  const astTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ruffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Which checks are currently in-flight — drives the status bar spinner
  const [checking, setChecking] = useState<Set<string>>(new Set());
  const [counts, setCounts] = useState<DiagnosticCounts>({ errors: 0, warnings: 0 });

  /** Recompute marker counts and push updated markers to Monaco. */
  const flushMarkers = useCallback(() => {
    const merged = [
      ...(diagnosticsRef.current.ast ?? []),
      ...(diagnosticsRef.current.ruff ?? []),
      ...(diagnosticsRef.current.pyright ?? []),
    ];

    setCounts({
      errors: merged.filter((d) => d.severity === 'error').length,
      warnings: merged.filter((d) => d.severity === 'warning').length,
    });

    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (!editor || !monaco) return;
    const model = editor.getModel();
    if (!model) return;

    monaco.editor.setModelMarkers(model, MARKER_OWNER, buildMarkers(merged));
  }, []);

  /**
   * Run one lint check tier and update the shared diagnostics map.
   *
   * @param checkType - Which checker to invoke.
   * @param code      - Current source code snapshot.
   */
  const runCheck = useCallback(
    async (checkType: 'ast' | 'ruff' | 'pyright', code: string) => {
      setChecking((prev) => new Set(prev).add(checkType));
      try {
        const res = await lintToolSource({ source_code: code, check: checkType });
        diagnosticsRef.current = {
          ...diagnosticsRef.current,
          [checkType]: res.diagnostics,
        };
        flushMarkers();
      } catch {
        // Network / server errors are silently ignored so the editor stays usable.
      } finally {
        setChecking((prev) => {
          const next = new Set(prev);
          next.delete(checkType);
          return next;
        });
      }
    },
    [flushMarkers],
  );

  /** Clear all diagnostics and Monaco markers (e.g. on dialog reset). */
  const clearDiagnostics = useCallback(() => {
    diagnosticsRef.current = { ast: [], ruff: [], pyright: [] };
    setCounts({ errors: 0, warnings: 0 });
    const editor = editorRef.current;
    const monaco = monacoRef.current;
    if (editor && monaco) {
      const model = editor.getModel();
      if (model) monaco.editor.setModelMarkers(model, MARKER_OWNER, []);
    }
  }, []);

  // Monaco theme adapts to the app's colour scheme
  const editorTheme = useMemo(() => {
    if (theme === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
        ? 'vs-dark'
        : 'light';
    }
    return theme === 'dark' ? 'vs-dark' : 'light';
  }, [theme]);

  // Reset all state when the dialog opens
  useEffect(() => {
    if (open) {
      setSaveError(null);
      clearDiagnostics();
      const initial =
        mode === 'edit' && initialSource ? initialSource : DEFAULT_TOOL_TEMPLATE;
      setSourceCode(initial);
      // Kick off an immediate ast check on the pre-loaded code
      void runCheck('ast', initial);
    }
  }, [open, mode, initialSource, clearDiagnostics, runCheck]);

  /**
   * Capture Monaco editor and API instances on first mount.
   * Cast to MinimalMonaco/MinimalEditor to avoid unsafe-any from monaco-editor
   * internals while still maintaining runtime safety.
   */
  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor as unknown as MinimalEditor;
    monacoRef.current = monaco as unknown as MinimalMonaco;
  };

  /**
   * Handle editor code changes with three-tier debounced lint.
   * Each keystroke resets both timers:
   *   300 ms quiet   → ast  (fast syntax-only check)
   *   2 000 ms quiet → ruff (slower style / lint check)
   */
  const handleCodeChange = (value: string | undefined) => {
    const code = value ?? '';
    setSourceCode(code);

    if (astTimerRef.current !== null) clearTimeout(astTimerRef.current);
    if (ruffTimerRef.current !== null) clearTimeout(ruffTimerRef.current);

    astTimerRef.current = setTimeout(() => {
      void runCheck('ast', code);
    }, 300);

    ruffTimerRef.current = setTimeout(() => {
      void runCheck('ruff', code);
    }, 2000);
  };

  /**
   * Save handler: fires pyright in the background then persists source code.
   * Pyright results will appear in the editor even if save completes first.
   */
  const handleSave = async () => {
    if (!sourceCode.trim()) {
      setSaveError('Source code is required');
      return;
    }

    setIsSubmitting(true);
    setSaveError(null);

    // Trigger pyright concurrently — do not await so save is not blocked
    void runCheck('pyright', sourceCode);

    try {
      await onSave(sourceCode);
      onOpenChange(false);
    } catch (err) {
      const error = err as Error;
      setSaveError(error.message || 'Failed to save tool');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleCancel = () => onOpenChange(false);

  const title = mode === 'create' ? 'New Tool' : `Edit Tool: ${tool?.name ?? ''}`;

  const isChecking = checking.size > 0;
  const hasErrors = counts.errors > 0;
  const hasWarnings = counts.warnings > 0;

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
          <Button size="sm" onClick={() => void handleSave()} disabled={isSubmitting}>
            {isSubmitting ? (
              <>
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                Saving…
              </>
            ) : (
              'Save'
            )}
          </Button>
        </div>
      }
    >
      <div className="flex flex-col h-full p-4 gap-3">
        {/* Help text */}
        <div className="px-3 py-2 bg-muted/50 border border-border rounded-md text-sm text-muted-foreground">
          Define your tool using the{' '}
          <code className="font-mono text-foreground">@tool</code> decorator.
          The <code className="font-mono text-foreground">name</code> and{' '}
          <code className="font-mono text-foreground">description</code> will be
          extracted automatically.
        </div>

        {/* Save error banner */}
        {saveError && (
          <div className="px-3 py-2 bg-destructive/10 border border-destructive/20 rounded-md text-sm text-destructive">
            {saveError}
          </div>
        )}

        {/* Source code editor */}
        <div className="flex flex-col flex-1 gap-1.5 min-h-0">
          <label className="text-sm font-medium text-foreground">Source Code</label>

          <div className="flex-1 border border-border rounded-md overflow-hidden flex flex-col min-h-0">
            {/* Monaco Editor */}
            <div className="flex-1 min-h-0">
              <Editor
                height="100%"
                language="python"
                theme={editorTheme}
                value={sourceCode}
                onChange={handleCodeChange}
                onMount={handleEditorMount}
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

            {/* Diagnostic status bar — styled after VS Code's bottom bar */}
            <div className="flex items-center gap-3 px-3 py-1 border-t border-border bg-muted/30 text-xs select-none shrink-0">
              {isChecking && (
                <span className="flex items-center gap-1 text-muted-foreground">
                  <Loader2 className="w-3 h-3 animate-spin" aria-hidden="true" />
                  {[...checking].join(', ')}…
                </span>
              )}

              {hasErrors && (
                <span className="flex items-center gap-1 text-destructive">
                  <AlertCircle className="w-3 h-3" aria-hidden="true" />
                  {counts.errors} error{counts.errors !== 1 ? 's' : ''}
                </span>
              )}

              {hasWarnings && (
                <span className="flex items-center gap-1 text-yellow-500">
                  <AlertTriangle className="w-3 h-3" aria-hidden="true" />
                  {counts.warnings} warning{counts.warnings !== 1 ? 's' : ''}
                </span>
              )}

              {!isChecking && !hasErrors && !hasWarnings && (
                <span className="flex items-center gap-1 text-muted-foreground/60">
                  <CheckCircle2 className="w-3 h-3" aria-hidden="true" />
                  No issues
                </span>
              )}

              <span className="ml-auto text-muted-foreground/50">Save to run pyright</span>
            </div>
          </div>
        </div>
      </div>
    </DraggableDialog>
  );
}

export default ToolEditorDialog;
