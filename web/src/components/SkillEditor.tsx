import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Editor, { type OnMount } from '@monaco-editor/react';
import * as Monaco from 'monaco-editor';
import { toast } from 'sonner';
import {
  FilePlus,
  FileText,
  Folder,
  FolderOpen,
  FolderPlus,
  Loader2,
  MoreHorizontal,
  Trash2,
} from "@/lib/lucide";
import { useTheme } from '@/lib/use-theme';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import ConfirmationModal from '@/components/ConfirmationModal';
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import {
  createSkillDirectory,
  createSkillFileContent,
  deleteSkillPath,
  getSkillFileContent,
  getSkillFileTree,
  updateSkillFileContent,
  type SkillFileTreeEntry,
  type ManagedSkill,
} from '@/utils/api';

interface FileTreeNode {
  kind: 'file';
  name: string;
  path: string;
}

interface DirectoryTreeNode {
  kind: 'directory';
  name: string;
  path: string;
  items: TreeNode[];
}

type TreeNode = FileTreeNode | DirectoryTreeNode;
type PendingCreate = { parentPath: string; kind: 'file' | 'directory' };

const LANGUAGE_BY_EXTENSION: Record<string, string> = {
  css: 'css',
  html: 'html',
  js: 'javascript',
  json: 'json',
  jsx: 'javascript',
  md: 'markdown',
  py: 'python',
  sh: 'shell',
  ts: 'typescript',
  tsx: 'typescript',
  txt: 'plaintext',
  yaml: 'yaml',
  yml: 'yaml',
};

/** Resolve system theme to a concrete value for Monaco. */
function useResolvedTheme(): 'dark' | 'light' {
  const { theme } = useTheme();
  if (theme === 'system') {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }
  return theme;
}

function getLanguageForPath(path: string | null): string {
  const extension = path?.split('.').pop()?.toLowerCase() ?? '';
  return LANGUAGE_BY_EXTENSION[extension] ?? 'plaintext';
}

function isPreviewSupported(path: string | null): boolean {
  if (!path) return false;
  const extension = path.split('.').pop()?.toLowerCase() ?? '';
  return extension in LANGUAGE_BY_EXTENSION;
}

function fileNameFromPath(path: string): string {
  return path.split('/').filter(Boolean).pop() ?? path;
}

function childPath(parentPath: string, name: string): string {
  return parentPath ? `${parentPath}/${name}` : name;
}

function isSameOrDescendant(path: string, ancestorPath: string): boolean {
  return path === ancestorPath || path.startsWith(`${ancestorPath}/`);
}

function isValidNewItemName(name: string): boolean {
  return Boolean(name) && !name.includes('/') && !name.includes('\\') && name !== '.' && name !== '..';
}

function createDirectoryNode(name: string, path: string): DirectoryTreeNode {
  return {
    kind: 'directory',
    name,
    path,
    items: [],
  };
}

function createFileNode(name: string, path: string): FileTreeNode {
  return {
    kind: 'file',
    name,
    path,
  };
}

function sortTreeNodes(nodes: TreeNode[]): TreeNode[] {
  return nodes
    .map((node) =>
      node.kind === 'directory'
        ? { ...node, items: sortTreeNodes(node.items) }
        : node
    )
    .sort((left, right) => {
      if (left.kind !== right.kind) {
        return left.kind === 'directory' ? -1 : 1;
      }
      return left.name.localeCompare(right.name);
    });
}

function buildTree(entries: SkillFileTreeEntry[]): TreeNode[] {
  const root = createDirectoryNode('', '');
  const directoryMap = new Map<string, DirectoryTreeNode>([['', root]]);

  entries.forEach((entry) => {
    const segments = entry.path.split('/').filter(Boolean);
    if (segments.length === 0) return;

    let parent = root;
    segments.forEach((segment, index) => {
      const path = segments.slice(0, index + 1).join('/');
      const isLeaf = index === segments.length - 1;
      const kind = isLeaf ? entry.kind : 'directory';

      if (kind === 'directory') {
        let directory = directoryMap.get(path);
        if (!directory) {
          directory = createDirectoryNode(segment, path);
          directoryMap.set(path, directory);
          parent.items.push(directory);
        }
        parent = directory;
        return;
      }

      if (!parent.items.some((item) => item.path === path)) {
        parent.items.push(createFileNode(segment, path));
      }
    });
  });

  return sortTreeNodes(root.items);
}

function defaultFilePath(entries: SkillFileTreeEntry[]): string | null {
  const files = entries.filter((entry) => entry.kind === 'file');
  return (
    files.find((entry) => entry.path === 'SKILL.md')?.path ??
    files.find((entry) => entry.path.toLowerCase().endsWith('/skill.md'))?.path ??
    files[0]?.path ??
    null
  );
}

function mergeDirectoryEntries(
  current: SkillFileTreeEntry[],
  directoryPath: string | null,
  nextEntries: SkillFileTreeEntry[],
): SkillFileTreeEntry[] {
  const nextParentPath = directoryPath || null;
  const retained = current.filter((entry) => entry.parent_path !== nextParentPath);
  const merged = new Map<string, SkillFileTreeEntry>();
  [...retained, ...nextEntries].forEach((entry) => {
    merged.set(entry.path, entry);
  });
  return Array.from(merged.values());
}

interface SkillEditorProps {
  /** Existing skill name. When absent, the editor works on a virtual new skill. */
  skillName?: string | null;
  /** Virtual SKILL.md content for unsaved new skills. */
  value: string;
  /** Called when virtual new skill content changes. */
  onChange: (value: string) => void;
  /** Called when user saves virtual new skill content. */
  onSave?: (value: string, path?: string) => void;
  /** Called after an existing skill file is saved. */
  onSaved?: (metadata: ManagedSkill) => Promise<void> | void;
  /** Whether save operation is in progress. */
  isSaving?: boolean;
  /** Whether editor is read-only for visible but non-editable skills. */
  readOnly?: boolean;
}

/**
 * Directory-aware Skill editor. Skills are bundles, so the editor exposes the
 * whole skill tree instead of treating SKILL.md as the only editable asset.
 */
function SkillEditor({
  skillName = null,
  value,
  onChange,
  onSave,
  onSaved,
  isSaving = false,
  readOnly = false,
}: SkillEditorProps) {
  const resolvedTheme = useResolvedTheme();
  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const activeValueRef = useRef(value);
  const [treeEntries, setTreeEntries] = useState<SkillFileTreeEntry[]>([]);
  const [fileContents, setFileContents] = useState<Record<string, string>>({});
  const [activePath, setActivePath] = useState<string>('SKILL.md');
  const [expandedDirectories, setExpandedDirectories] = useState<Record<string, boolean>>({});
  const [loadedDirectories, setLoadedDirectories] = useState<Record<string, boolean>>({});
  const [isLoadingTree, setIsLoadingTree] = useState(false);
  const [isLoadingFile, setIsLoadingFile] = useState(false);
  const [isSavingFile, setIsSavingFile] = useState(false);
  const [pendingCreate, setPendingCreate] = useState<PendingCreate | null>(null);
  const [isCreatingPath, setIsCreatingPath] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<TreeNode | null>(null);
  const [isDeletingPath, setIsDeletingPath] = useState(false);

  const treeNodes = useMemo(() => buildTree(treeEntries), [treeEntries]);
  const activeValue = fileContents[activePath] ?? '';
  const activePreviewSupported = isPreviewSupported(activePath);
  const monacoPath = skillName
    ? `/skills/${skillName}/${activePath}`
    : `/skills/draft/${activePath}`;

  useEffect(() => {
    activeValueRef.current = activeValue;
  }, [activeValue]);

  useEffect(() => {
    if (skillName) return;
    setTreeEntries([
      {
        path: 'SKILL.md',
        name: 'SKILL.md',
        kind: 'file',
        parent_path: null,
        size_bytes: new Blob([value]).size,
      },
    ]);
    setFileContents({ 'SKILL.md': value });
    setActivePath('SKILL.md');
    setExpandedDirectories({});
    setLoadedDirectories({ '': true });
    setPendingCreate(null);
    setDeleteTarget(null);
  }, [skillName, value]);

  useEffect(() => {
    if (!skillName) return;

    let cancelled = false;
    const loadTree = async () => {
      setIsLoadingTree(true);
      try {
        setFileContents({});
        setActivePath('');
        setExpandedDirectories({});
        setLoadedDirectories({});
        setPendingCreate(null);
        setDeleteTarget(null);
        const result = await getSkillFileTree(skillName);
        if (cancelled) return;
        setTreeEntries(result.entries);
        const nextPath = defaultFilePath(result.entries);
        setActivePath(nextPath ?? '');
        setExpandedDirectories({});
        setLoadedDirectories({ '': true });
      } catch {
        if (!cancelled) {
          toast.error(`Failed to load skill files for "${skillName}"`);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingTree(false);
        }
      }
    };

    void loadTree();
    return () => {
      cancelled = true;
    };
  }, [skillName]);

  useEffect(() => {
    if (!skillName || !activePath || fileContents[activePath] !== undefined) {
      return;
    }
    if (!isPreviewSupported(activePath)) {
      return;
    }

    let cancelled = false;
    const loadFile = async () => {
      setIsLoadingFile(true);
      try {
        const result = await getSkillFileContent(skillName, activePath);
        if (!cancelled) {
          setFileContents((current) => ({
            ...current,
            [activePath]: result.content,
          }));
        }
      } catch {
        if (!cancelled) {
          toast.error(`Failed to load ${activePath}`);
        }
      } finally {
        if (!cancelled) {
          setIsLoadingFile(false);
        }
      }
    };

    void loadFile();
    return () => {
      cancelled = true;
    };
  }, [activePath, fileContents, skillName]);

  const saveActiveFile = useCallback(async () => {
    if (readOnly || !activePath || !isPreviewSupported(activePath)) return;
    if (!skillName) {
      onSave?.(activeValueRef.current, activePath);
      return;
    }

    setIsSavingFile(true);
    try {
      const result = await updateSkillFileContent(
        skillName,
        activePath,
        activeValueRef.current,
      );
      toast.success(`${activePath} saved`);
      await onSaved?.(result.metadata);
    } catch {
      toast.error(`Failed to save ${activePath}`);
    } finally {
      setIsSavingFile(false);
    }
  }, [activePath, onSave, onSaved, readOnly, skillName]);

  const toggleDirectory = useCallback(async (path: string, nextOpen: boolean) => {
    setExpandedDirectories((current) => ({
      ...current,
      [path]: nextOpen,
    }));
    if (!skillName || !nextOpen || loadedDirectories[path]) {
      return;
    }

    try {
      const result = await getSkillFileTree(skillName, path);
      setTreeEntries((current) => mergeDirectoryEntries(current, path, result.entries));
      setLoadedDirectories((current) => ({
        ...current,
        [path]: true,
      }));
    } catch {
      toast.error(`Failed to load ${path}`);
      setExpandedDirectories((current) => ({
        ...current,
        [path]: false,
      }));
    }
  }, [loadedDirectories, skillName]);

  const loadDirectory = useCallback(async (path: string) => {
    if (!skillName) return;
    const result = await getSkillFileTree(skillName, path || undefined);
    setTreeEntries((current) => mergeDirectoryEntries(current, path || null, result.entries));
    setLoadedDirectories((current) => ({
      ...current,
      [path]: true,
    }));
  }, [skillName]);

  const startCreate = useCallback(async (parentPath: string, kind: PendingCreate['kind']) => {
    if (readOnly || !skillName) return;
    setExpandedDirectories((current) => ({
      ...current,
      [parentPath]: true,
    }));
    if (!loadedDirectories[parentPath]) {
      try {
        await loadDirectory(parentPath);
      } catch {
        toast.error(`Failed to load ${parentPath || 'files'}`);
        return;
      }
    }
    setPendingCreate({ parentPath, kind });
  }, [loadDirectory, loadedDirectories, readOnly, skillName]);

  const cancelCreate = useCallback(() => {
    setPendingCreate(null);
  }, []);

  const commitCreate = useCallback(async (name: string) => {
    if (!pendingCreate || !skillName || isCreatingPath) return;
    const nextName = name.trim();
    if (!isValidNewItemName(nextName)) {
      toast.error('Use a simple file or folder name.');
      return;
    }

    const nextPath = childPath(pendingCreate.parentPath, nextName);
    setIsCreatingPath(true);
    try {
      const result = pendingCreate.kind === 'directory'
        ? await createSkillDirectory(skillName, nextPath)
        : await createSkillFileContent(skillName, nextPath);
      await onSaved?.(result.metadata);
      setPendingCreate(null);
      await loadDirectory(pendingCreate.parentPath);
      if (pendingCreate.kind === 'file') {
        setFileContents((current) => ({ ...current, [nextPath]: '' }));
        setActivePath(nextPath);
      }
    } catch {
      toast.error(`Failed to create ${nextName}`);
    } finally {
      setIsCreatingPath(false);
    }
  }, [isCreatingPath, loadDirectory, onSaved, pendingCreate, skillName]);

  const confirmDeletePath = useCallback(async () => {
    if (!deleteTarget || !skillName) return;
    setIsDeletingPath(true);
    try {
      const targetPath = deleteTarget.path;
      const result = await deleteSkillPath(skillName, targetPath);
      await onSaved?.(result.metadata);
      setTreeEntries((current) => {
        const nextEntries = current.filter((entry) => !isSameOrDescendant(entry.path, targetPath));
        if (activePath && isSameOrDescendant(activePath, targetPath)) {
          const nextActivePath = defaultFilePath(nextEntries) ?? '';
          setActivePath(nextActivePath);
        }
        return nextEntries;
      });
      setFileContents((current) => {
        const nextContents = { ...current };
        Object.keys(nextContents).forEach((path) => {
          if (isSameOrDescendant(path, targetPath)) {
            delete nextContents[path];
          }
        });
        return nextContents;
      });
      setExpandedDirectories((current) => {
        const nextExpanded = { ...current };
        Object.keys(nextExpanded).forEach((path) => {
          if (isSameOrDescendant(path, targetPath)) {
            delete nextExpanded[path];
          }
        });
        return nextExpanded;
      });
      setLoadedDirectories((current) => {
        const nextLoaded = { ...current };
        Object.keys(nextLoaded).forEach((path) => {
          if (isSameOrDescendant(path, targetPath)) {
            delete nextLoaded[path];
          }
        });
        return nextLoaded;
      });
      setDeleteTarget(null);
    } catch {
      toast.error(`Failed to delete ${deleteTarget.path}`);
    } finally {
      setIsDeletingPath(false);
    }
  }, [activePath, deleteTarget, onSaved, skillName]);

  const handleMount: OnMount = useCallback((
    editor: Monaco.editor.IStandaloneCodeEditor,
  ) => {
    editorRef.current = editor;
    editor.addCommand(Monaco.KeyMod.CtrlCmd | Monaco.KeyCode.KeyS, () => {
      void saveActiveFile();
    });
  }, [saveActiveFile]);

  const handleContentChange = (next: string) => {
    setFileContents((current) => ({
      ...current,
      [activePath]: next,
    }));
    if (!skillName && activePath === 'SKILL.md') {
      onChange(next);
    }
  };

  const busy = isSaving || isSavingFile;

  return (
    <div className="flex h-full min-h-0 overflow-hidden">
      <aside className="group/file-tree flex w-56 shrink-0 flex-col border-r border-border bg-muted/20">
        <div className="flex items-center justify-between border-b border-border px-3 py-2 text-xs font-medium text-muted-foreground">
          <span>Files</span>
          <RootFileMenu
            disabled={readOnly || !skillName}
            onNewFile={() => void startCreate('', 'file')}
            onNewFolder={() => void startCreate('', 'directory')}
          />
        </div>
        <div className="tree-root min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 py-2">
          {isLoadingTree ? (
            <div className="flex items-center px-2 py-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            </div>
          ) : treeNodes.length === 0 ? (
            <>
              {pendingCreate?.parentPath === '' ? (
                <PendingCreateInput
                  depth={0}
                  kind={pendingCreate.kind}
                  onCancel={cancelCreate}
                  onCommit={(name) => void commitCreate(name)}
                />
              ) : (
                <div className="px-2 py-2 text-xs text-muted-foreground">No files.</div>
              )}
            </>
          ) : (
            <>
              {pendingCreate?.parentPath === '' ? (
                <PendingCreateInput
                  depth={0}
                  kind={pendingCreate.kind}
                  onCancel={cancelCreate}
                  onCommit={(name) => void commitCreate(name)}
                />
              ) : null}
              {treeNodes.map((node) => (
                <ExplorerNode
                  key={node.path}
                  node={node}
                  depth={0}
                  expandedDirectories={expandedDirectories}
                  selectedFilePath={activePath}
                  pendingCreate={pendingCreate}
                  readOnly={readOnly || !skillName}
                  onToggleDirectory={(path, nextOpen) => void toggleDirectory(path, nextOpen)}
                  onOpenFile={setActivePath}
                  onStartCreate={(path, kind) => void startCreate(path, kind)}
                  onDelete={setDeleteTarget}
                  onCancelCreate={cancelCreate}
                  onCommitCreate={(name) => void commitCreate(name)}
                />
              ))}
            </>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1">
          {activePath && isLoadingFile ? (
            <div className="flex flex-1 items-center justify-center text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : activePath && !activePreviewSupported ? (
            <div className="flex flex-1 items-center justify-center px-6 text-center text-sm text-muted-foreground">
              {fileNameFromPath(activePath)} is not supported for preview.
            </div>
          ) : activePath ? (
            <Editor
              path={monacoPath}
              height="100%"
              language={getLanguageForPath(activePath)}
              value={activeValue}
              theme={resolvedTheme === 'dark' ? 'vs-dark' : 'light'}
              onChange={(next) => handleContentChange(next ?? '')}
              onMount={handleMount}
              loading={<Loader2 className="m-auto h-5 w-5 animate-spin text-muted-foreground" />}
              options={{
                fontSize: 13,
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                wordWrap: activePath.endsWith('.md') ? 'on' : 'off',
                tabSize: 2,
                insertSpaces: true,
                automaticLayout: true,
                lineNumbers: 'on',
                renderWhitespace: 'boundary',
                readOnly: readOnly || isLoadingFile,
              }}
            />
          ) : (
            <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
              Select a file to edit.
            </div>
          )}
        </div>
        <div className="flex items-center justify-between border-t border-border bg-muted/30 px-3 py-1.5 text-xs">
          <span className="truncate text-muted-foreground">
            {readOnly ? 'Read-only skill' : activePath || 'Ready'}
          </span>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy || readOnly || !activePath || isLoadingFile || !activePreviewSupported}
            onClick={() => void saveActiveFile()}
            className="h-6 gap-1 px-2 text-xs"
          >
            {readOnly ? (
              'Read-only'
            ) : busy ? (
              <>
                <Loader2 className="h-3 w-3 animate-spin" />
                Saving…
              </>
            ) : (
              'Save  ⌘S'
            )}
          </Button>
        </div>
      </div>
      <ConfirmationModal
        isOpen={deleteTarget !== null}
        title={`Delete ${deleteTarget?.kind ?? 'path'}?`}
        message={
          deleteTarget
            ? `Delete "${deleteTarget.path}" from this Skill? This cannot be undone.`
            : ''
        }
        confirmText="Delete"
        onConfirm={() => void confirmDeletePath()}
        onCancel={() => {
          if (!isDeletingPath) setDeleteTarget(null);
        }}
        isLoading={isDeletingPath}
      />
    </div>
  );
}

interface ExplorerNodeProps {
  node: TreeNode;
  depth: number;
  expandedDirectories: Record<string, boolean>;
  selectedFilePath: string;
  pendingCreate: PendingCreate | null;
  readOnly: boolean;
  onToggleDirectory: (path: string, nextOpen: boolean) => void;
  onOpenFile: (path: string) => void;
  onStartCreate: (path: string, kind: PendingCreate['kind']) => void;
  onDelete: (node: TreeNode) => void;
  onCancelCreate: () => void;
  onCommitCreate: (name: string) => void;
}

function ExplorerNode({
  node,
  depth,
  expandedDirectories,
  selectedFilePath,
  pendingCreate,
  readOnly,
  onToggleDirectory,
  onOpenFile,
  onStartCreate,
  onDelete,
  onCancelCreate,
  onCommitCreate,
}: ExplorerNodeProps) {
  const depthStyle = {
    paddingLeft: `${8 + depth * 14}px`,
  };

  if (node.kind === 'directory') {
    const isOpen = expandedDirectories[node.path] ?? false;
    return (
      <Collapsible
        open={isOpen}
        onOpenChange={(nextOpen) => onToggleDirectory(node.path, nextOpen)}
      >
        <div className="group/file-item flex items-center rounded-md hover:bg-accent">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex min-w-0 flex-1 items-center gap-2 rounded-md bg-transparent px-2.5 py-1.5 text-left text-[13px] text-foreground transition-colors"
              style={depthStyle}
              title={node.path}
            >
              {isOpen ? (
                <FolderOpen className="h-3.5 w-3.5 shrink-0" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0" />
              )}
              <span className="min-w-0 flex-1 truncate">{node.name}</span>
            </button>
          </CollapsibleTrigger>
          <FileItemMenu
            disabled={readOnly}
            isDirectory
            onNewFile={() => onStartCreate(node.path, 'file')}
            onNewFolder={() => onStartCreate(node.path, 'directory')}
            onDelete={() => onDelete(node)}
          />
        </div>
        <CollapsibleContent className="space-y-0.5">
          {pendingCreate?.parentPath === node.path ? (
            <PendingCreateInput
              depth={depth + 1}
              kind={pendingCreate.kind}
              onCancel={onCancelCreate}
              onCommit={onCommitCreate}
            />
          ) : null}
          {node.items.map((childNode) => (
            <ExplorerNode
              key={childNode.path}
              node={childNode}
              depth={depth + 1}
              expandedDirectories={expandedDirectories}
              selectedFilePath={selectedFilePath}
              pendingCreate={pendingCreate}
              readOnly={readOnly}
              onToggleDirectory={onToggleDirectory}
              onOpenFile={onOpenFile}
              onStartCreate={onStartCreate}
              onDelete={onDelete}
              onCancelCreate={onCancelCreate}
              onCommitCreate={onCommitCreate}
            />
          ))}
        </CollapsibleContent>
      </Collapsible>
    );
  }

  const isSelected = selectedFilePath === node.path;
  return (
    <div
      className={`group/file-item flex items-center rounded-md transition-colors ${
        isSelected ? 'bg-accent text-accent-foreground ring-1 ring-border' : 'hover:bg-accent'
      }`}
    >
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-2 rounded-md bg-transparent px-2.5 py-1.5 text-left text-[13px] transition-colors"
        style={depthStyle}
        onClick={() => onOpenFile(node.path)}
        title={node.path}
      >
        <FileText className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
      </button>
      <FileItemMenu
        disabled={readOnly}
        isDirectory={false}
        onDelete={() => onDelete(node)}
      />
    </div>
  );
}

interface FileItemMenuProps {
  disabled: boolean;
  isDirectory: boolean;
  onDelete: () => void;
  onNewFile?: () => void;
  onNewFolder?: () => void;
}

function FileItemMenu({
  disabled,
  isDirectory,
  onDelete,
  onNewFile,
  onNewFolder,
}: FileItemMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="mr-1 h-6 w-6 shrink-0 p-0 opacity-0 transition-opacity group-hover/file-item:opacity-100 data-[state=open]:opacity-100"
          onClick={(event) => event.stopPropagation()}
          aria-label="File actions"
        >
          <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="end"
        size="medium"
        className="w-40"
        onClick={(event) => event.stopPropagation()}
      >
        {isDirectory ? (
          <>
            <DropdownMenuItem onClick={onNewFile}>
              <FilePlus className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
              New File
            </DropdownMenuItem>
            <DropdownMenuItem onClick={onNewFolder}>
              <FolderPlus className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
              New Folder
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        ) : null}
        <DropdownMenuItem
          onClick={onDelete}
          className="text-destructive focus:text-destructive"
        >
          <Trash2 className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
          Delete
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface RootFileMenuProps {
  disabled: boolean;
  onNewFile: () => void;
  onNewFolder: () => void;
}

function RootFileMenu({
  disabled,
  onNewFile,
  onNewFolder,
}: RootFileMenuProps) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={disabled}
          className="h-6 w-6 shrink-0 p-0 opacity-0 transition-opacity group-hover/file-tree:opacity-100 data-[state=open]:opacity-100"
          aria-label="Root file actions"
        >
          <MoreHorizontal className="h-3.5 w-3.5" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" size="medium" className="w-40">
        <DropdownMenuItem onClick={onNewFile}>
          <FilePlus className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
          Add File
        </DropdownMenuItem>
        <DropdownMenuItem onClick={onNewFolder}>
          <FolderPlus className="mr-2 h-3.5 w-3.5" aria-hidden="true" />
          Add Folder
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface PendingCreateInputProps {
  depth: number;
  kind: PendingCreate['kind'];
  onCancel: () => void;
  onCommit: (name: string) => void;
}

function PendingCreateInput({
  depth,
  kind,
  onCancel,
  onCommit,
}: PendingCreateInputProps) {
  const [name, setName] = useState('');
  const depthStyle = {
    marginLeft: `${8 + depth * 14}px`,
  };

  return (
    <div className="flex items-center gap-2 rounded-md px-2.5 py-1" style={depthStyle}>
      {kind === 'directory' ? (
        <Folder className="h-3.5 w-3.5 shrink-0" />
      ) : (
        <FileText className="h-3.5 w-3.5 shrink-0" />
      )}
      <Input
        autoFocus
        value={name}
        onChange={(event) => setName(event.target.value)}
        onBlur={() => {
          if (name.trim()) {
            onCommit(name);
            return;
          }
          onCancel();
        }}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault();
            onCommit(name);
          }
          if (event.key === 'Escape') {
            event.preventDefault();
            onCancel();
          }
        }}
        placeholder={kind === 'directory' ? 'Folder name' : 'File name'}
        className="h-7 min-w-0 flex-1 px-2 text-xs"
      />
    </div>
  );
}

export default SkillEditor;
