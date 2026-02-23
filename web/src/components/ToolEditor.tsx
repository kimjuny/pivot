import { useCallback, useEffect, useRef, useState } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import type * as Monaco from 'monaco-editor';
import { AlertCircle, AlertTriangle, CheckCircle2, Loader2 } from 'lucide-react';
import { checkToolAst, checkToolRuff, checkToolPyright, type ToolDiagnostic } from '../utils/api';
import { useTheme } from '@/lib/use-theme';
import { Button } from '@/components/ui/button';

/**
 * Resolve 'system' theme to the OS preference so we can pass a concrete
 * value to Monaco.
 */
function useResolvedTheme(): 'dark' | 'light' {
  const { theme } = useTheme();
  if (theme === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return theme;
}

/**
 * Props for ToolEditor component.
 */
interface ToolEditorProps {
  /** Current Python source code */
  value: string;
  /** Called whenever the editor content changes */
  onChange: (value: string) => void;
  /** Called when the user requests to save (Ctrl+S / Cmd+S) */
  onSave?: (value: string) => void;
  /** Whether a save operation is currently in progress */
  isSaving?: boolean;
}

/**
 * Per-source diagnostic counts shown in the status bar.
 */
interface DiagnosticSummary {
  errors: number;
  warnings: number;
}

/**
 * Severity level mapping from backend strings to Monaco marker severities.
 * Monaco uses numeric constants; we fall back to Warning for unknown values.
 */
function toMonacoSeverity(
  monacoRef: typeof Monaco,
  severity: string
): Monaco.MarkerSeverity {
  switch (severity.toLowerCase()) {
    case 'error':
      return monacoRef.MarkerSeverity.Error;
    case 'warning':
      return monacoRef.MarkerSeverity.Warning;
    case 'information':
    case 'info':
      return monacoRef.MarkerSeverity.Info;
    default:
      return monacoRef.MarkerSeverity.Warning;
  }
}

/**
 * Convert backend diagnostics into Monaco IMarkerData objects.
 */
function toMarkers(
  monacoRef: typeof Monaco,
  diagnostics: ToolDiagnostic[]
): Monaco.editor.IMarkerData[] {
  return diagnostics.map((d) => ({
    startLineNumber: d.line,
    startColumn: d.col,
    endLineNumber: d.endLine ?? d.line,
    endColumn: d.endCol ?? d.col + 1,
    message: d.message,
    severity: toMonacoSeverity(monacoRef, d.severity),
    source: d.source,
  }));
}

/**
 * Count errors and warnings from a list of diagnostics.
 */
function countDiagnostics(diagnostics: ToolDiagnostic[]): DiagnosticSummary {
  return diagnostics.reduce(
    (acc, d) => {
      if (d.severity.toLowerCase() === 'error') acc.errors += 1;
      else acc.warnings += 1;
      return acc;
    },
    { errors: 0, warnings: 0 }
  );
}

/**
 * Python source code editor with three-tier live code checking.
 *
 * - 200 ms after typing stops → AST syntax check
 * - 2 000 ms after typing stops → ruff lint check
 * - Ctrl+S / Cmd+S → pyright type check + triggers onSave callback
 *
 * All checks are merged and rendered as Monaco editor markers so the
 * user sees inline squiggles. A status bar below the editor shows the
 * aggregated error / warning counts, and Save button.
 */
function ToolEditor({ value, onChange, onSave, isSaving = false }: ToolEditorProps) {
  const resolvedTheme = useResolvedTheme();
  const monacoRef = useRef<typeof Monaco | null>(null);
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);

  // Stable refs for debounce timers to avoid stale closures
  const astTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ruffTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Accumulated markers per source so partial updates don't clear each other
  const markersRef = useRef<{
    ast: Monaco.editor.IMarkerData[];
    ruff: Monaco.editor.IMarkerData[];
    pyright: Monaco.editor.IMarkerData[];
  }>({ ast: [], ruff: [], pyright: [] });

  // Diagnostic totals exposed in the status bar
  const [allDiagnostics, setAllDiagnostics] = useState<ToolDiagnostic[]>([]);
  // Track whether any check is running so we can show a spinner
  const [isChecking, setIsChecking] = useState(false);
  // Stable ref for the latest source value used by the save shortcut
  const valueRef = useRef(value);
  useEffect(() => { valueRef.current = value; }, [value]);

  /**
   * Push the latest merged markers to Monaco's model and update status bar.
   * Must be called after any per-source update.
   */
  const flushMarkers = useCallback((merged: ToolDiagnostic[]) => {
    if (!monacoRef.current || !editorRef.current) return;
    const model = editorRef.current.getModel();
    if (!model) return;
    const all = [
      ...markersRef.current.ast,
      ...markersRef.current.ruff,
      ...markersRef.current.pyright,
    ];
    monacoRef.current.editor.setModelMarkers(model, 'pivot-tool-check', all);
    setAllDiagnostics(merged);
  }, []);

  /** Mount callback – capture monaco and editor instances, bind Ctrl+S. */
  const handleMount: OnMount = useCallback(
    (editor, monaco) => {
      editorRef.current = editor;
      monacoRef.current = monaco;

      // Bind save shortcut; always reads the latest value via ref
      editor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
        () => {
          if (onSave) {
            const current = valueRef.current;
            setIsChecking(true);
            console.log('[ToolEditor] pyright check triggered by save shortcut');
            void checkToolPyright(current)
              .then((diagnostics) => {
                const count = countDiagnostics(diagnostics);
                if (diagnostics.length === 0) {
                  console.log('[ToolEditor] pyright: all clear ✓');
                } else {
                  console.log(
                    `[ToolEditor] pyright: ${count.errors} error(s), ${count.warnings} warning(s)`,
                    diagnostics
                  );
                }
                if (monacoRef.current) {
                  markersRef.current.pyright = toMarkers(monacoRef.current, diagnostics);
                  const merged = [
                    ...diagnostics,
                    // keep ast/ruff as ToolDiagnostic proxies via stored markers count
                  ];
                  flushMarkers(merged);
                }
                onSave(current);
              })
              .catch((err: unknown) => {
                console.error('[ToolEditor] pyright: request failed', err);
              })
              .finally(() => {
                setIsChecking(false);
              });
          }
        }
      );
    },
    [onSave, flushMarkers]
  );

  /** Debounced change handler – schedules AST and ruff checks. */
  const handleChange = useCallback(
    (newValue: string | undefined) => {
      const code = newValue ?? '';
      onChange(code);

      // Clear previous timers on each keystroke
      if (astTimerRef.current) clearTimeout(astTimerRef.current);
      if (ruffTimerRef.current) clearTimeout(ruffTimerRef.current);

      // AST check: fast, runs 200 ms after last keystroke
      astTimerRef.current = setTimeout(() => {
        setIsChecking(true);
        console.log('[ToolEditor] ast check triggered');
        void checkToolAst(code)
          .then((diagnostics) => {
            const count = countDiagnostics(diagnostics);
            if (diagnostics.length === 0) {
              console.log('[ToolEditor] ast: syntax OK ✓');
            } else {
              console.log(
                `[ToolEditor] ast: ${count.errors} syntax error(s)`,
                diagnostics
              );
            }
            if (monacoRef.current) {
              markersRef.current.ast = toMarkers(monacoRef.current, diagnostics);
              const merged = [
                ...diagnostics,
                ...markersRef.current.ruff.map((m) => ({
                  line: m.startLineNumber,
                  col: m.startColumn,
                  endLine: m.endLineNumber,
                  endCol: m.endColumn,
                  message: m.message ?? '',
                  severity: m.severity === monacoRef.current?.MarkerSeverity.Error ? 'error' : 'warning',
                  source: 'ruff',
                })),
                ...markersRef.current.pyright.map((m) => ({
                  line: m.startLineNumber,
                  col: m.startColumn,
                  endLine: m.endLineNumber,
                  endCol: m.endColumn,
                  message: m.message ?? '',
                  severity: m.severity === monacoRef.current?.MarkerSeverity.Error ? 'error' : 'warning',
                  source: 'pyright',
                })),
              ] as ToolDiagnostic[];
              flushMarkers(merged);
            }
          })
          .catch((err: unknown) => {
            console.error('[ToolEditor] ast: request failed', err);
          })
          .finally(() => setIsChecking(false));
      }, 200);

      // Ruff check: heavier, runs 2 000 ms after last keystroke
      ruffTimerRef.current = setTimeout(() => {
        setIsChecking(true);
        console.log('[ToolEditor] ruff check triggered');
        void checkToolRuff(code)
          .then((diagnostics) => {
            const count = countDiagnostics(diagnostics);
            if (diagnostics.length === 0) {
              console.log('[ToolEditor] ruff: all clear ✓');
            } else {
              console.log(
                `[ToolEditor] ruff: ${count.errors} error(s), ${count.warnings} warning(s)`,
                diagnostics
              );
            }
            if (monacoRef.current) {
              markersRef.current.ruff = toMarkers(monacoRef.current, diagnostics);
              const merged = [
                ...markersRef.current.ast.map((m) => ({
                  line: m.startLineNumber,
                  col: m.startColumn,
                  endLine: m.endLineNumber,
                  endCol: m.endColumn,
                  message: m.message ?? '',
                  severity: m.severity === monacoRef.current?.MarkerSeverity.Error ? 'error' : 'warning',
                  source: 'ast',
                })),
                ...diagnostics,
                ...markersRef.current.pyright.map((m) => ({
                  line: m.startLineNumber,
                  col: m.startColumn,
                  endLine: m.endLineNumber,
                  endCol: m.endColumn,
                  message: m.message ?? '',
                  severity: m.severity === monacoRef.current?.MarkerSeverity.Error ? 'error' : 'warning',
                  source: 'pyright',
                })),
              ] as ToolDiagnostic[];
              flushMarkers(merged);
            }
          })
          .catch((err: unknown) => {
            console.error('[ToolEditor] ruff: request failed', err);
          })
          .finally(() => setIsChecking(false));
      }, 2000);
    },
    [onChange, flushMarkers]
  );

  // Clear timers on unmount to prevent memory leaks
  useEffect(() => {
    return () => {
      if (astTimerRef.current) clearTimeout(astTimerRef.current);
      if (ruffTimerRef.current) clearTimeout(ruffTimerRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Status bar derived state
  // ---------------------------------------------------------------------------

  const totalErrors = allDiagnostics.filter((d) => d.severity.toLowerCase() === 'error').length;
  const totalWarnings = allDiagnostics.filter((d) => d.severity.toLowerCase() !== 'error').length;
  const allClear = allDiagnostics.length === 0;

  return (
    <div className="flex flex-col h-full">
      {/* Monaco editor – fills remaining space above the status bar */}
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          language="python"
          value={value}
          theme={resolvedTheme === 'dark' ? 'vs-dark' : 'light'}
          onChange={handleChange}
          onMount={handleMount}
          options={{
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            tabSize: 4,
            insertSpaces: true,
            automaticLayout: true,
            lineNumbers: 'on',
            renderWhitespace: 'boundary',
            formatOnPaste: true,
          }}
        />
      </div>

      {/* Status bar */}
      <div className="flex items-center justify-between px-3 py-1.5 border-t border-border bg-muted/30 text-xs flex-shrink-0">
        {/* Left: diagnostic summary */}
        <div className="flex items-center gap-3">
          {isChecking ? (
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <Loader2 className="w-3 h-3 animate-spin" />
              Checking…
            </span>
          ) : allClear ? (
            <span className="flex items-center gap-1.5 text-green-500">
              <CheckCircle2 className="w-3 h-3" />
              All checks passed
            </span>
          ) : (
            <>
              {totalErrors > 0 && (
                <span className="flex items-center gap-1 text-destructive">
                  <AlertCircle className="w-3 h-3" />
                  {totalErrors} error{totalErrors !== 1 ? 's' : ''}
                </span>
              )}
              {totalWarnings > 0 && (
                <span className="flex items-center gap-1 text-yellow-500">
                  <AlertTriangle className="w-3 h-3" />
                  {totalWarnings} warning{totalWarnings !== 1 ? 's' : ''}
                </span>
              )}
            </>
          )}
        </div>

        {/* Right: Save button */}
        <Button
          size="sm"
          variant="ghost"
          disabled={isSaving || isChecking}
          onClick={() => onSave && onSave(valueRef.current)}
          className="h-6 text-xs px-2 gap-1"
        >
          {isSaving ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin" />
              Saving…
            </>
          ) : (
            'Save  ⌘S'
          )}
        </Button>
      </div>
    </div>
  );
}

export default ToolEditor;
