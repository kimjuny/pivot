import { useCallback, useEffect, useRef } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import type * as Monaco from 'monaco-editor';
import { Loader2 } from "@/lib/lucide";
import { useTheme } from '@/lib/use-theme';
import { Button } from '@/components/ui/button';

/** Resolve system theme to a concrete value for Monaco. */
function useResolvedTheme(): 'dark' | 'light' {
  const { theme } = useTheme();
  if (theme === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return theme;
}

interface SkillEditorProps {
  /** Current markdown source content. */
  value: string;
  /** Called when source content changes. */
  onChange: (value: string) => void;
  /** Called when user triggers save (button or Cmd/Ctrl+S). */
  onSave?: (value: string) => void;
  /** Whether save operation is in progress. */
  isSaving?: boolean;
  /** Whether editor is read-only for visible but non-editable skills. */
  readOnly?: boolean;
}

/**
 * Markdown editor for Skill source files.
 *
 * Unlike ToolEditor, this editor does not run lint/type checks and focuses on
 * markdown authoring with lightweight save interaction.
 */
function SkillEditor({
  value,
  onChange,
  onSave,
  isSaving = false,
  readOnly = false,
}: SkillEditorProps) {
  const resolvedTheme = useResolvedTheme();
  const valueRef = useRef(value);
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);

  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  const handleMount: OnMount = useCallback((editor, monaco) => {
    const monacoApi = monaco as typeof Monaco;
    editorRef.current = editor;
    editor.addCommand(monacoApi.KeyMod.CtrlCmd | monacoApi.KeyCode.KeyS, () => {
      if (onSave && !readOnly) {
        onSave(valueRef.current);
      }
    });
  }, [onSave, readOnly]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          language="markdown"
          value={value}
          theme={resolvedTheme === 'dark' ? 'vs-dark' : 'light'}
          onChange={(next) => onChange(next ?? '')}
          onMount={handleMount}
          options={{
            fontSize: 13,
            minimap: { enabled: false },
            scrollBeyondLastLine: false,
            wordWrap: 'on',
            tabSize: 2,
            insertSpaces: true,
            automaticLayout: true,
            lineNumbers: 'on',
            renderWhitespace: 'boundary',
            readOnly,
          }}
        />
      </div>
      <div className="flex items-center justify-between px-3 py-1.5 border-t border-border bg-muted/30 text-xs flex-shrink-0">
        <span className="text-muted-foreground">
          {readOnly ? 'Read-only shared skill' : 'Markdown skill source'}
        </span>
        <Button
          size="sm"
          variant="ghost"
          disabled={isSaving || readOnly}
          onClick={() => onSave && onSave(valueRef.current)}
          className="h-6 text-xs px-2 gap-1"
        >
          {readOnly ? (
            'Read-only'
          ) : isSaving ? (
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

export default SkillEditor;
